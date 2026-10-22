"""Project-scoped human approval API for governed pipelines."""
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.rag import ingest_human_decision
from src.core.security import require_role
from src.core.tenancy import require_project_access
from src.database.models import Pipeline, PipelineStatus, Project, User, UserRole
from src.database.repository import AuditLogRepository, PipelineRepository
from src.database.session import get_async_session
from src.workflows.csv_pipeline import resume_csv_pipeline

router = APIRouter()


class ApprovalDecision(BaseModel):
    """Approval/rejection request. Actor identity is always taken from the JWT."""

    decision: str
    modifications: dict[str, Any] | None = None
    alternative_action: str | None = None
    rationale: str = Field(min_length=1, max_length=2000)
    user_id: str | None = None


@router.get("/pending")
async def pending_approvals(
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, list[dict[str, Any]]]:
    """List only approvals in projects the caller can access."""
    query = select(Pipeline).join(Project, Project.id == Pipeline.project_id).where(
        Pipeline.status == PipelineStatus.APPROVAL_REQUIRED
    )
    if current_user.role != UserRole.ADMIN:
        query = query.where(Project.owner_id == current_user.id)
    result = await session.execute(query.order_by(Pipeline.created_at.desc()).limit(200))
    return {"pipelines": [
        {
            "pipeline_id": item.id,
            "project_id": item.project_id,
            "dataset_id": item.dataset_id,
            "current_state": item.current_state,
            "error_message": item.error_message,
        } for item in result.scalars().all()
    ]}


@router.get("/{pipeline_id}")
async def approval_detail(
    pipeline_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, Any]:
    """Return checkpoint details only to an authorized project user."""
    pipeline = await PipelineRepository(session).get_by_id(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    await require_project_access(session, current_user, pipeline.project_id)
    checkpoint = pipeline.checkpoint_data or {}
    return {
        "pipeline_id": pipeline.id,
        "status": pipeline.status.value,
        "current_state": pipeline.current_state,
        "proposed_action": checkpoint.get("stage", "resume"),
        "pii_columns": checkpoint.get("pii_columns", {}),
        "quality_score": checkpoint.get("quality_score"),
        "candidate_artifact": checkpoint.get("candidate_artifact"),
    }


@router.post("/{pipeline_id}/approve")
async def approve_pipeline(
    pipeline_id: str,
    decision: ApprovalDecision,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, Any]:
    """Approve a pending checkpoint and publish its validated staged artifact."""
    repo = PipelineRepository(session)
    pipeline = await repo.get_by_id(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    await require_project_access(session, current_user, pipeline.project_id)
    if pipeline.status != PipelineStatus.APPROVAL_REQUIRED:
        raise HTTPException(status_code=409, detail="Pipeline is not waiting for approval")
    if decision.decision.lower() not in {"approve", "approved"}:
        raise HTTPException(status_code=422, detail="decision must be approve or approved")
    decision_data = decision.model_dump(exclude={"user_id"})
    decision_data["decision"] = "approved"
    decision_data["user_id"] = current_user.id
    checkpoint = dict(pipeline.checkpoint_data or {})
    checkpoint.setdefault("human_decisions", {})
    checkpoint["human_decisions"]["latest"] = decision_data
    if decision.modifications:
        raise HTTPException(status_code=422, detail="Approval-time data modifications are not supported; create a new run")
    await repo.update(pipeline_id, {
        "status": PipelineStatus.RUNNING,
        "current_state": "publishing",
        "checkpoint_data": checkpoint,
        "error_message": None,
    })
    await AuditLogRepository(session).log_action(
        action="HUMAN_APPROVAL_GRANTED",
        resource_type="pipeline",
        resource_id=pipeline_id,
        user_id=current_user.id,
        before_json={"status": PipelineStatus.APPROVAL_REQUIRED.value},
        after_json={"status": PipelineStatus.RUNNING.value, "decision": decision_data},
        rationale=decision.rationale,
        confidence=1.0,
    )
    await ingest_human_decision(session, pipeline_id, decision_data)
    result = await resume_csv_pipeline(pipeline_id, current_user.id)
    return {"status": result.get("status", "unknown"), "pipeline_id": pipeline_id, "execution": result}


@router.post("/{pipeline_id}/reject")
async def reject_pipeline(
    pipeline_id: str,
    decision: ApprovalDecision,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, str]:
    """Reject a pending checkpoint; rejected staged data is never published."""
    repo = PipelineRepository(session)
    pipeline = await repo.get_by_id(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    await require_project_access(session, current_user, pipeline.project_id)
    if pipeline.status != PipelineStatus.APPROVAL_REQUIRED:
        raise HTTPException(status_code=409, detail="Pipeline is not waiting for approval")
    if decision.decision.lower() not in {"reject", "rejected"}:
        raise HTTPException(status_code=422, detail="decision must be reject or rejected")
    if decision.alternative_action:
        raise HTTPException(status_code=422, detail="Alternative actions are not implemented; reject and create a new run")
    decision_data = decision.model_dump(exclude={"user_id"})
    decision_data["decision"] = "rejected"
    decision_data["user_id"] = current_user.id
    checkpoint = dict(pipeline.checkpoint_data or {})
    checkpoint.setdefault("human_decisions", {})
    checkpoint["human_decisions"]["latest"] = decision_data
    checkpoint["stage"] = "rejected"
    await repo.update(pipeline_id, {
        "status": PipelineStatus.FAILED,
        "current_state": "rejected",
        "checkpoint_data": checkpoint,
        "error_message": decision.rationale,
        "completed_at": datetime.now(UTC),
    })
    await AuditLogRepository(session).log_action(
        action="HUMAN_APPROVAL_REJECTED",
        resource_type="pipeline",
        resource_id=pipeline_id,
        user_id=current_user.id,
        before_json={"status": PipelineStatus.APPROVAL_REQUIRED.value},
        after_json={"status": PipelineStatus.FAILED.value, "decision": decision_data},
        rationale=decision.rationale,
        confidence=1.0,
    )
    await ingest_human_decision(session, pipeline_id, decision_data)
    return {"status": PipelineStatus.FAILED.value, "pipeline_id": pipeline_id}
