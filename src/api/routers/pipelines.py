"""Pipeline API routes."""

from datetime import UTC, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.security import get_current_user, require_role
from src.database.models import Pipeline, PipelineStatus, User, UserRole
from src.database.repository import AuditLogRepository, DatasetRepository, PipelineRepository
from src.database.session import get_async_session

router = APIRouter()


class PipelineCreateRequest(BaseModel):
    """Payload for starting a pipeline from an existing dataset."""

    dataset_id: str
    name: Optional[str] = None
    config: Optional[dict[str, Any]] = None


def _progress_for_status(status: PipelineStatus) -> int:
    """Return a display progress estimate for the current status."""

    return {
        PipelineStatus.PENDING: 8,
        PipelineStatus.PLANNING: 18,
        PipelineStatus.RUNNING: 35,
        PipelineStatus.PAUSED: 55,
        PipelineStatus.APPROVAL_REQUIRED: 75,
        PipelineStatus.COMPLETED: 100,
        PipelineStatus.FAILED: 35,
    }.get(status, 0)


def _serialize_pipeline(pipeline: Pipeline) -> dict[str, Any]:
    """Convert a pipeline model into the frontend table shape."""

    return {
        "id": pipeline.id,
        "display_id": f"PL-{pipeline.created_at.strftime('%H%M%S')}" if pipeline.created_at else pipeline.id[:8],
        "name": pipeline.name,
        "dataset": pipeline.dataset.name if pipeline.dataset else pipeline.dataset_id,
        "dataset_id": pipeline.dataset_id,
        "status": pipeline.status.value,
        "progress": _progress_for_status(pipeline.status),
        "current_state": pipeline.current_state,
        "started_at": pipeline.started_at.isoformat() if pipeline.started_at else None,
        "created_at": pipeline.created_at.isoformat() if pipeline.created_at else None,
        "error_message": pipeline.error_message,
    }


@router.get("/")
async def list_pipelines(
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """List pipelines visible to the current user."""

    query = select(Pipeline).options(selectinload(Pipeline.dataset)).order_by(Pipeline.created_at.desc())
    if current_user.role != UserRole.ADMIN:
        query = query.where(Pipeline.project.has(owner_id=current_user.id))
    result = await session.execute(query)
    pipelines = result.scalars().all()
    return {"pipelines": [_serialize_pipeline(pipeline) for pipeline in pipelines]}


@router.post("/")
async def create_pipeline(
    payload: PipelineCreateRequest,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, Any]:
    """Start a pipeline for an uploaded dataset."""

    dataset = await DatasetRepository(session).get_by_id(payload.dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail={"error": "Dataset not found"})

    pipeline = await PipelineRepository(session).create(
        Pipeline(
            project_id=dataset.project_id,
            dataset_id=dataset.id,
            name=payload.name or f"{dataset.name} Pipeline",
            status=PipelineStatus.RUNNING,
            current_state="ingestion",
            config=payload.config or {},
            checkpoint_data={},
            started_at=datetime.now(UTC),
        )
    )
    await AuditLogRepository(session).log_action(
        action="PIPELINE_STARTED",
        resource_type="pipeline",
        resource_id=pipeline.id,
        user_id=current_user.id,
        before_json={},
        after_json={"dataset_id": dataset.id, "name": pipeline.name, "status": pipeline.status.value},
        rationale="Pipeline started from uploaded dataset",
        confidence=1.0,
    )

    result = await session.execute(
        select(Pipeline).options(selectinload(Pipeline.dataset)).where(Pipeline.id == pipeline.id)
    )
    created = result.scalar_one()
    return {"pipeline": _serialize_pipeline(created)}
