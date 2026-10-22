"""Pipeline API: create, inspect, execute, and resume governed CSV workflows."""
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.security import get_current_user, require_role
from src.core.tenancy import require_dataset_access, require_project_access
from src.database.models import Pipeline, PipelineStatus, User, UserRole
from src.database.repository import AuditLogRepository, PipelineRepository
from src.database.session import get_async_session
from src.workflows.csv_pipeline import resume_csv_pipeline, run_csv_pipeline

router = APIRouter()


class PipelineCreateRequest(BaseModel):
    """Payload for starting a governed pipeline from a dataset."""

    dataset_id: str
    name: str | None = Field(default=None, min_length=1, max_length=255)
    config: dict[str, Any] = Field(default_factory=dict)


def _progress(status: PipelineStatus) -> int:
    return {
        PipelineStatus.PENDING: 5,
        PipelineStatus.PLANNING: 10,
        PipelineStatus.RUNNING: 45,
        PipelineStatus.PAUSED: 60,
        PipelineStatus.APPROVAL_REQUIRED: 80,
        PipelineStatus.COMPLETED: 100,
        PipelineStatus.FAILED: 100,
    }.get(status, 0)


def _serialize(pipeline: Pipeline) -> dict[str, Any]:
    return {
        "id": pipeline.id,
        "name": pipeline.name,
        "dataset_id": pipeline.dataset_id,
        "dataset": pipeline.dataset.name if pipeline.dataset else pipeline.dataset_id,
        "project_id": pipeline.project_id,
        "status": pipeline.status.value,
        "progress": _progress(pipeline.status),
        "current_state": pipeline.current_state,
        "started_at": pipeline.started_at.isoformat() if pipeline.started_at else None,
        "completed_at": pipeline.completed_at.isoformat() if pipeline.completed_at else None,
        "created_at": pipeline.created_at.isoformat() if pipeline.created_at else None,
        "error_message": pipeline.error_message,
        "checkpoint": pipeline.checkpoint_data or {},
    }


@router.get("/")
async def list_pipelines(
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List only pipelines in projects the caller can access."""
    query = select(Pipeline).options(selectinload(Pipeline.dataset)).order_by(Pipeline.created_at.desc())
    if current_user.role != UserRole.ADMIN:
        query = query.where(Pipeline.project.has(owner_id=current_user.id))
    result = await session.execute(query.limit(200))
    return {"pipelines": [_serialize(pipeline) for pipeline in result.scalars().all()]}


@router.post("/")
async def create_pipeline(
    payload: PipelineCreateRequest,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, Any]:
    """Create and execute a governed CSV workflow; sensitive output pauses for approval."""
    dataset = await require_dataset_access(session, current_user, payload.dataset_id)
    if not dataset.bronze_path:
        raise HTTPException(status_code=422, detail="Dataset has no Bronze CSV artifact")
    pipeline = await PipelineRepository(session).create(Pipeline(
        project_id=dataset.project_id,
        dataset_id=dataset.id,
        name=payload.name or f"{dataset.name} Pipeline",
        status=PipelineStatus.PENDING,
        current_state="queued",
        config=payload.config,
        checkpoint_data={},
        started_at=datetime.now(UTC),
    ))
    await AuditLogRepository(session).log_action(
        action="PIPELINE_CREATED",
        resource_type="pipeline",
        resource_id=pipeline.id,
        user_id=current_user.id,
        before_json={},
        after_json={"dataset_id": dataset.id, "project_id": dataset.project_id, "status": pipeline.status.value},
        rationale="Authorized user started governed CSV workflow",
        confidence=1.0,
    )
    try:
        execution = await run_csv_pipeline(pipeline.id, current_user.id)
    except Exception as exc:
        await PipelineRepository(session).update(pipeline.id, {
            "status": PipelineStatus.FAILED,
            "current_state": "failed",
            "error_message": str(exc)[:1000],
            "completed_at": datetime.now(UTC),
        })
        await AuditLogRepository(session).log_action(
            action="PIPELINE_FAILED",
            resource_type="pipeline",
            resource_id=pipeline.id,
            user_id=current_user.id,
            before_json={},
            after_json={"error": str(exc)[:500]},
            rationale="Pipeline execution failed closed",
            confidence=1.0,
        )
        refreshed = await session.execute(
            select(Pipeline).options(selectinload(Pipeline.dataset)).where(Pipeline.id == pipeline.id)
        )
        return {"pipeline": _serialize(refreshed.scalar_one()), "execution": {"status": "failed"}}
    refreshed = await session.execute(
        select(Pipeline).options(selectinload(Pipeline.dataset)).where(Pipeline.id == pipeline.id)
    )
    return {"pipeline": _serialize(refreshed.scalar_one()), "execution": execution}


@router.get("/{pipeline_id}")
async def get_pipeline(
    pipeline_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Get pipeline details only when the caller can access its project."""
    result = await session.execute(
        select(Pipeline).options(selectinload(Pipeline.dataset)).where(Pipeline.id == pipeline_id)
    )
    pipeline = result.scalar_one_or_none()
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    await require_project_access(session, current_user, pipeline.project_id)
    return {"pipeline": _serialize(pipeline)}


@router.post("/{pipeline_id}/resume")
async def resume_pipeline(
    pipeline_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, Any]:
    """Retry a failed/running CSV workflow or publish a previously approved checkpoint."""
    pipeline = await PipelineRepository(session).get_by_id(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    await require_project_access(session, current_user, pipeline.project_id)
    if pipeline.status == PipelineStatus.COMPLETED:
        return {"pipeline_id": pipeline.id, "status": pipeline.status.value}
    try:
        if pipeline.status == PipelineStatus.RUNNING and (
            (pipeline.checkpoint_data or {}).get("human_decisions", {}).get("latest", {}).get("decision")
            in {"approve", "approved"}
        ):
            result = await resume_csv_pipeline(pipeline.id, current_user.id)
        elif pipeline.status in {PipelineStatus.FAILED, PipelineStatus.PENDING, PipelineStatus.RUNNING}:
            await PipelineRepository(session).update(pipeline.id, {
                "status": PipelineStatus.PENDING, "error_message": None, "checkpoint_data": {}
            })
            result = await run_csv_pipeline(pipeline.id, current_user.id)
        else:
            raise HTTPException(status_code=409, detail=f"Pipeline cannot resume from state {pipeline.status.value}")
    except HTTPException:
        raise
    except Exception as exc:
        await PipelineRepository(session).update(pipeline.id, {
            "status": PipelineStatus.FAILED,
            "current_state": "failed",
            "error_message": str(exc)[:1000],
            "completed_at": datetime.now(UTC),
        })
        raise HTTPException(status_code=422, detail="Pipeline resume failed; inspect the pipeline error record") from exc
    return {"pipeline_id": pipeline.id, "execution": result}
