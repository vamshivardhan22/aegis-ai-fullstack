"""LangGraph-backed, database-checkpointed governed CSV workflow."""
from __future__ import annotations

import hashlib
import hmac
import io
import re
from datetime import UTC, datetime
from typing import Any, TypedDict

import pandas as pd
from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.safe_transform import apply_transformation_plan
from src.config import get_settings
from src.core.logging import configure_logging
from src.database.models import Dataset, Lineage, Pipeline, PipelineStatus
from src.database.repository import AuditLogRepository, DatasetRepository, LineageRepository, PipelineRepository
from src.database.session import AsyncSessionLocal
from src.storage import get_storage

logger = configure_logging(get_settings().AEGIS_DEBUG)
settings = get_settings()
MAX_PIPELINE_BYTES = 50 * 1024 * 1024
MAX_PIPELINE_COLUMNS = 500
_PII_NAME_HINT = re.compile(
    r"(^|[_\s-])(email|e_mail|phone|mobile|ssn|social_security|address|full_name|first_name|last_name|"
    r"customer_name|name|date_of_birth|dob|credit_card|card_number|account_number|tax_id|passport|medical_record|ip_address)([_\s-]|$)"
)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[0-9][0-9\s().-]{7,}[0-9]$")
_CARD = re.compile(r"^(?:[0-9][ -]*?){13,19}$")


class CSVWorkflowState(TypedDict, total=False):
    """JSON-safe workflow state persisted on the pipeline record after each stage."""

    pipeline_id: str
    actor_id: str | None
    dataset_id: str
    project_id: str
    source_path: str
    source_sha256: str
    input_schema: dict[str, str]
    profile: dict[str, Any]
    pii_columns: dict[str, str]
    candidate_artifact: str
    output_schema: dict[str, str]
    output_row_count: int
    output_column_count: int
    output_size_bytes: int
    output_sha256: str
    quality_score: float
    transformation_plan: dict[str, Any]
    needs_approval: bool
    stage: str
    resume: bool
    human_decisions: dict[str, Any]
    result: dict[str, Any]
    error_message: str
    config: dict[str, Any]
    masking_applied: bool


def _detect_pii(frame: pd.DataFrame) -> dict[str, str]:
    """Detect likely PII using column-name hints and full-column pattern ratios."""
    detected: dict[str, str] = {}
    for column in frame.columns:
        normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(column)).lower().replace(" ", "_")
        if _PII_NAME_HINT.search(normalized):
            token = normalized.strip("_").split("_")
            if "email" in token or "e_mail" in normalized:
                kind = "email"
            elif "phone" in token or "mobile" in token:
                kind = "phone"
            elif "ssn" in token or "social_security" in normalized:
                kind = "ssn"
            elif "card" in token or "credit_card" in normalized or "account_number" in normalized or "tax_id" in normalized or "passport" in normalized:
                kind = "financial_identifier"
            elif "address" in token:
                kind = "address"
            elif "dob" in token or "date_of_birth" in normalized:
                kind = "date_of_birth"
            elif "medical_record" in normalized:
                kind = "medical_record"
            elif "ip_address" in normalized:
                kind = "ip_address"
            else:
                kind = "person_name"
            detected[str(column)] = kind
            continue
        values = frame[column].dropna().astype(str)
        if values.empty:
            continue
        sample = values.iloc[::max(1, len(values) // 1000)].head(1000)
        for kind, pattern in (("email", _EMAIL), ("phone", _PHONE), ("financial_identifier", _CARD)):
            ratio = float(sample.str.fullmatch(pattern).mean()) if len(sample) else 0.0
            if ratio >= 0.7:
                detected[str(column)] = kind
                break
    return detected


def _mask_value(value: Any, kind: str) -> Any:
    """Return a deterministic non-reversible representation for likely sensitive values."""
    if pd.isna(value):
        return value
    text = str(value)
    if kind in {"phone", "ssn", "financial_identifier"}:
        if len(re.sub(r"\D", "", text)) >= 4:
            return "*" * max(0, len(text) - 4) + text[-4:]
        return "<redacted>"
    if kind in {"date_of_birth", "address", "medical_record", "ip_address"}:
        return "<redacted>"
    digest = hmac.new(
        settings.AEGIS_SECRET_KEY.encode("utf-8"), text.encode("utf-8"), hashlib.sha256
    ).hexdigest()[:20]
    return "token:" + digest


def _profile(frame: pd.DataFrame, source_bytes: bytes) -> dict[str, Any]:
    """Calculate deterministic row, null, duplicate, quality, and checksum metrics."""
    total_cells = max(1, int(frame.shape[0] * frame.shape[1]))
    null_count = int(frame.isna().sum().sum())
    duplicate_rows = int(frame.duplicated().sum())
    duplicate_ratio = duplicate_rows / max(1, len(frame))
    null_ratio = null_count / total_cells
    score = max(0.0, min(1.0, 1.0 - 0.7 * null_ratio - 0.3 * duplicate_ratio))
    return {
        "profile_version": 1,
        "row_count": int(len(frame)),
        "column_count": int(len(frame.columns)),
        "null_counts": {str(column): int(count) for column, count in frame.isna().sum().items()},
        "null_cells": null_count,
        "duplicate_rows": duplicate_rows,
        "null_ratio": round(null_ratio, 6),
        "duplicate_ratio": round(duplicate_ratio, 6),
        "quality_score": round(score, 4),
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
    }


async def _audit(
    session: AsyncSession, pipeline: Pipeline, actor_id: str | None, action: str, details: dict[str, Any]
) -> None:
    await AuditLogRepository(session).log_action(
        action=action,
        resource_type="pipeline",
        resource_id=pipeline.id,
        user_id=actor_id,
        before_json={},
        after_json=details,
        rationale="Governed CSV pipeline execution",
        confidence=1.0,
    )


async def _persist_state(state: CSVWorkflowState, stage: str, status: PipelineStatus = PipelineStatus.RUNNING) -> None:
    """Persist a JSON-safe checkpoint after a graph stage so a later request can resume."""
    state["stage"] = stage
    async with AsyncSessionLocal() as session:
        pipeline = await PipelineRepository(session).get_by_id(state["pipeline_id"])
        if pipeline is None:
            raise ValueError("Pipeline record disappeared during execution")
        await PipelineRepository(session).update(
            pipeline.id,
            {
                "status": status,
                "current_state": stage,
                "checkpoint_data": dict(state),
                "error_message": state.get("error_message"),
            },
        )
        await _audit(session, pipeline, state.get("actor_id"), "PIPELINE_CHECKPOINT_SAVED", {"stage": stage})


async def _profile_node(state: CSVWorkflowState) -> CSVWorkflowState:
    async with AsyncSessionLocal() as session:
        pipeline = await PipelineRepository(session).get_by_id(state["pipeline_id"])
        if pipeline is None:
            raise ValueError("Pipeline not found")
        dataset = await DatasetRepository(session).get_by_id(pipeline.dataset_id)
        if dataset is None or dataset.project_id != pipeline.project_id:
            raise ValueError("Pipeline source dataset is unavailable")
        config = dict(pipeline.config or {})
        source_layer = config.get("source_layer")
        if source_layer is not None and source_layer not in {"bronze", "silver", "gold"}:
            raise ValueError("source_layer must be bronze, silver, or gold")
        if source_layer:
            source_path = getattr(dataset, f"{source_layer}_path")
        else:
            source_path = dataset.gold_path or dataset.silver_path or dataset.bronze_path
        if not source_path:
            raise ValueError("Pipeline source dataset has no stored CSV artifact")
        raw = await get_storage().read(source_path)
        if len(raw) > MAX_PIPELINE_BYTES:
            raise ValueError("Source CSV exceeds the 50 MiB pipeline execution limit")
        if not raw:
            raise ValueError("Source CSV is empty")
        try:
            frame = pd.read_csv(io.BytesIO(raw))
        except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
            raise ValueError("Source artifact is not a valid UTF-8 CSV") from exc
        if frame.empty:
            raise ValueError("CSV contains a header but no data rows")
        if len(frame.columns) == 0 or len(frame.columns) > MAX_PIPELINE_COLUMNS:
            raise ValueError("CSV must contain between 1 and 500 columns")
        if frame.columns.duplicated().any():
            raise ValueError("CSV contains duplicate column names")
        required_columns = config.get("required_columns", [])
        if not isinstance(required_columns, list) or not all(isinstance(item, str) for item in required_columns):
            raise ValueError("required_columns must be a list of column names")
        missing = [column for column in required_columns if column not in frame.columns]
        if missing:
            raise ValueError("Required columns are missing: " + ", ".join(missing))
        profile = _profile(frame, raw)
        minimum_quality = float(config.get("minimum_quality_score", 0.6))
        if not 0 <= minimum_quality <= 1:
            raise ValueError("minimum_quality_score must be between 0 and 1")
        if profile["quality_score"] < minimum_quality:
            raise ValueError(
                f"Quality gate failed: score {profile['quality_score']} is below configured minimum {minimum_quality}"
            )
        state.update({
            "dataset_id": dataset.id,
            "project_id": pipeline.project_id,
            "source_path": source_path,
            "source_sha256": profile["source_sha256"],
            "input_schema": {str(column): str(dtype) for column, dtype in frame.dtypes.items()},
            "profile": profile,
            "quality_score": profile["quality_score"],
            "config": config,
        })
        await PipelineRepository(session).update(pipeline.id, {
            "status": PipelineStatus.RUNNING,
            "current_state": "profile",
            "checkpoint_data": dict(state),
            "error_message": None,
        })
        await _audit(session, pipeline, state.get("actor_id"), "PIPELINE_STAGE_COMPLETED", {"stage": "profile", "profile": profile})
    return state


async def _transform_node(state: CSVWorkflowState) -> CSVWorkflowState:
    raw = await get_storage().read(state["source_path"])
    if hashlib.sha256(raw).hexdigest() != state.get("source_sha256"):
        raise ValueError("Source artifact changed after profiling; transformation blocked")
    frame = pd.read_csv(io.BytesIO(raw))
    pii_columns = _detect_pii(frame)
    masked = frame.copy(deep=True)
    for column, kind in pii_columns.items():
        masked[column] = masked[column].map(lambda value: _mask_value(value, kind))
    config = state.get("config", {})
    plan = config.get("transformation_plan", {"operations": []})
    if not isinstance(plan, dict):
        raise ValueError("transformation_plan must be a declarative plan object")
    transformed = apply_transformation_plan(masked, plan)
    output_bytes = transformed.to_csv(index=False).encode("utf-8")
    candidate_path = f"staging/{state['project_id']}/{state['pipeline_id']}.csv"
    await get_storage().write(candidate_path, output_bytes, "text/csv")
    state.update({
        "pii_columns": pii_columns,
        "masking_applied": bool(pii_columns),
        "candidate_artifact": candidate_path,
        "output_schema": {str(column): str(dtype) for column, dtype in transformed.dtypes.items()},
        "output_row_count": int(len(transformed)),
        "output_column_count": int(len(transformed.columns)),
        "output_size_bytes": len(output_bytes),
        "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
        "transformation_plan": plan,
        "needs_approval": bool(pii_columns or config.get("require_approval")),
        "human_decisions": state.get("human_decisions", {}),
    })
    await _persist_state(state, "transform")
    return state


async def _approval_node(state: CSVWorkflowState) -> CSVWorkflowState:
    async with AsyncSessionLocal() as session:
        pipeline = await PipelineRepository(session).get_by_id(state["pipeline_id"])
        if pipeline is None:
            raise ValueError("Pipeline not found at approval gate")
        await PipelineRepository(session).update(
            pipeline.id,
            {
                "status": PipelineStatus.APPROVAL_REQUIRED,
                "current_state": "human_approval",
                "checkpoint_data": {**state, "stage": "awaiting_approval"},
            },
        )
        await _audit(session, pipeline, state.get("actor_id"), "PIPELINE_APPROVAL_REQUIRED", {
            "pii_columns": list(state.get("pii_columns", {})),
            "candidate_artifact": state.get("candidate_artifact"),
        })
    state["stage"] = "awaiting_approval"
    return state


async def _publish_node(state: CSVWorkflowState) -> CSVWorkflowState:
    async with AsyncSessionLocal() as session:
        pipeline = await PipelineRepository(session).get_by_id(state["pipeline_id"])
        if pipeline is None:
            raise ValueError("Pipeline not found at publication gate")
        source = await DatasetRepository(session).get_by_id(pipeline.dataset_id)
        if source is None:
            raise ValueError("Source dataset not found at publication gate")
        result = await _publish_candidate(session, pipeline, source, dict(state), state.get("actor_id"))
    state["stage"] = "published"
    state["result"] = result
    return state


def _route_start(state: CSVWorkflowState) -> str:
    return "publish" if state.get("resume") else "profile"


def _route_after_transform(state: CSVWorkflowState) -> str:
    return "approval" if state.get("needs_approval") else "publish"


def _build_graph():
    """Build the canonical LangGraph; durable state is checkpointed in the pipeline row."""
    graph = StateGraph(CSVWorkflowState)
    graph.add_node("route_start", lambda state: state)
    graph.add_node("profile", _profile_node)
    graph.add_node("transform", _transform_node)
    graph.add_node("approval", _approval_node)
    graph.add_node("publish", _publish_node)
    graph.add_edge(START, "route_start")
    graph.add_conditional_edges("route_start", _route_start, {"profile": "profile", "publish": "publish"})
    graph.add_edge("profile", "transform")
    graph.add_conditional_edges("transform", _route_after_transform, {"approval": "approval", "publish": "publish"})
    graph.add_edge("approval", END)
    graph.add_edge("publish", END)
    return graph.compile()


async def run_csv_pipeline(pipeline_id: str, actor_id: str | None = None) -> dict[str, Any]:
    """Execute the LangGraph CSV workflow and persist stage checkpoints in PostgreSQL."""
    async with AsyncSessionLocal() as session:
        pipeline = await PipelineRepository(session).get_by_id(pipeline_id)
        if pipeline is None:
            raise HTTPException(status_code=404, detail="Pipeline not found")
        if pipeline.status == PipelineStatus.COMPLETED:
            return {"pipeline_id": pipeline.id, "status": pipeline.status.value, "checkpoint": pipeline.checkpoint_data or {}}
        state: CSVWorkflowState = {"pipeline_id": pipeline.id, "actor_id": actor_id, "stage": "queued"}
        await PipelineRepository(session).update(
            pipeline.id,
            {"status": PipelineStatus.RUNNING, "current_state": "queued", "error_message": None, "checkpoint_data": dict(state)},
        )
        await _audit(session, pipeline, actor_id, "PIPELINE_STAGE_STARTED", {"stage": "queued"})
    try:
        final_state = await _build_graph().ainvoke(state)
    except Exception as exc:
        async with AsyncSessionLocal() as session:
            pipeline = await PipelineRepository(session).get_by_id(pipeline_id)
            if pipeline is not None:
                await PipelineRepository(session).update(pipeline_id, {
                    "status": PipelineStatus.FAILED,
                    "current_state": "failed",
                    "error_message": str(exc)[:1000],
                    "completed_at": datetime.now(UTC),
                })
                await _audit(session, pipeline, actor_id, "PIPELINE_FAILED", {"error": str(exc)[:500]})
        raise
    if final_state.get("stage") == "awaiting_approval":
        return {
            "pipeline_id": pipeline_id,
            "status": PipelineStatus.APPROVAL_REQUIRED.value,
            "checkpoint": {key: value for key, value in final_state.items() if key != "actor_id"},
        }
    return final_state.get("result", {"pipeline_id": pipeline_id, "status": "unknown"})


async def resume_csv_pipeline(pipeline_id: str, actor_id: str | None = None) -> dict[str, Any]:
    """Resume from the persisted checkpoint after an authorized approval decision."""
    async with AsyncSessionLocal() as session:
        pipeline = await PipelineRepository(session).get_by_id(pipeline_id)
        if pipeline is None:
            raise HTTPException(status_code=404, detail="Pipeline not found")
        if pipeline.status == PipelineStatus.COMPLETED:
            return {"pipeline_id": pipeline.id, "status": pipeline.status.value}
        if pipeline.status != PipelineStatus.RUNNING:
            raise HTTPException(status_code=409, detail="Pipeline is not in a resumable state")
        checkpoint = dict(pipeline.checkpoint_data or {})
        decision = (checkpoint.get("human_decisions") or {}).get("latest", {})
        if decision.get("decision") not in {"approve", "approved"}:
            raise HTTPException(status_code=409, detail="An approval decision is required before publication")
        checkpoint["pipeline_id"] = pipeline.id
        checkpoint["actor_id"] = actor_id
        checkpoint["resume"] = True
    final_state = await _build_graph().ainvoke(checkpoint)
    return final_state.get("result", {"pipeline_id": pipeline_id, "status": "unknown"})


async def _publish_candidate(
    session: AsyncSession, pipeline: Pipeline, source: Dataset, checkpoint: dict[str, Any], actor_id: str | None
) -> dict[str, Any]:
    """Idempotently create the derived dataset, lineage, and terminal run state."""
    candidate_path = checkpoint.get("candidate_artifact")
    if not candidate_path:
        raise ValueError("Pipeline checkpoint is missing the staged output artifact")
    output_bytes = await get_storage().read(candidate_path)
    expected_size = checkpoint.get("output_size_bytes")
    if expected_size is not None and len(output_bytes) != expected_size:
        raise ValueError("Staged artifact changed after validation; publication blocked")
    expected_hash = checkpoint.get("output_sha256")
    if expected_hash and hashlib.sha256(output_bytes).hexdigest() != expected_hash:
        raise ValueError("Staged artifact checksum mismatch; publication blocked")
    name = f"{source.name}-run-{pipeline.id[:8]}"
    result = await session.execute(select(Dataset).where(Dataset.project_id == pipeline.project_id, Dataset.name == name))
    target = result.scalar_one_or_none()
    dataset_values = {
        "silver_path": candidate_path,
        "schema_json": checkpoint.get("output_schema"),
        "profile_json": {**(checkpoint.get("profile") or {}), "output_sha256": checkpoint.get("output_sha256")},
        "row_count": checkpoint.get("output_row_count"),
        "column_count": checkpoint.get("output_column_count"),
        "size_bytes": len(output_bytes),
        "quality_score": checkpoint.get("quality_score"),
        "version": source.version + 1,
    }
    if target is None:
        target = await DatasetRepository(session).create(Dataset(
            project_id=pipeline.project_id,
            name=name,
            source_type="transformed",
            **dataset_values,
        ))
    else:
        await DatasetRepository(session).update(target.id, dataset_values)
        target = await DatasetRepository(session).get_by_id(target.id)
        if target is None:
            raise ValueError("Published dataset disappeared during idempotent recovery")
    edge_query = await session.execute(select(Lineage).where(
        Lineage.source_dataset_id == source.id, Lineage.target_dataset_id == target.id
    ))
    if edge_query.scalar_one_or_none() is None:
        await LineageRepository(session).create(Lineage(
            source_dataset_id=source.id,
            target_dataset_id=target.id,
            transformation_type="governed_csv_pipeline",
            agent_id="pipeline",
            sql_code="Validated declarative transformation plan",
            config_json={
                "pipeline_id": pipeline.id,
                "transformation_plan": checkpoint.get("transformation_plan", {}),
                "pii_columns": checkpoint.get("pii_columns", {}),
                "source_sha256": checkpoint.get("source_sha256"),
            },
        ))
    final_checkpoint = {
        **checkpoint,
        "stage": "published",
        "output_dataset_id": target.id,
        "published_at": datetime.now(UTC).isoformat(),
    }
    await PipelineRepository(session).update(pipeline.id, {
        "status": PipelineStatus.COMPLETED,
        "current_state": "published",
        "checkpoint_data": final_checkpoint,
        "error_message": None,
        "completed_at": datetime.now(UTC),
    })
    await _audit(session, pipeline, actor_id, "PIPELINE_PUBLISHED", {
        "output_dataset_id": target.id, "row_count": target.row_count, "pii_masked": bool(checkpoint.get("pii_columns")),
    })
    return {
        "pipeline_id": pipeline.id,
        "status": PipelineStatus.COMPLETED.value,
        "output_dataset_id": target.id,
        "output_path": target.silver_path,
        "row_count": target.row_count,
        "column_count": target.column_count,
        "quality_score": checkpoint.get("quality_score"),
        "pii_masked": bool(checkpoint.get("pii_columns")),
    }
