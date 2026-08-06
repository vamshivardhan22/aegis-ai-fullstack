"""Human approval API for paused pipelines."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.rag import ingest_human_decision
from src.core.security import require_role
from src.database.models import Pipeline, PipelineStatus
from src.database.models import User, UserRole
from src.database.repository import AuditLogRepository, PipelineRepository
from src.database.session import get_async_session
from src.orchestrator.langgraph import resume_from_checkpoint

router = APIRouter()


class ApprovalDecision(BaseModel):
    """Approval or rejection payload."""

    decision: str
    modifications: Optional[dict[str, Any]] = None
    alternative_action: Optional[str] = None
    rationale: str
    user_id: Optional[str] = None


@router.get("/pending")
async def pending_approvals(
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, list[dict[str, Any]]]:
    """List pipelines waiting for human approval."""

    del current_user
    result = await session.execute(select(Pipeline).where(Pipeline.status == PipelineStatus.APPROVAL_REQUIRED))
    pipelines = result.scalars().all()
    return {
        "pipelines": [
            {
                "pipeline_id": pipeline.id,
                "project_id": pipeline.project_id,
                "dataset_id": pipeline.dataset_id,
                "current_state": pipeline.current_state,
                "error_message": pipeline.error_message,
            }
            for pipeline in pipelines
        ]
    }


@router.get("/{pipeline_id}")
async def approval_detail(
    pipeline_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, Any]:
    """Return context for a paused pipeline."""

    del current_user
    pipeline = await PipelineRepository(session).get_by_id(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail={"error": "Pipeline not found"})
    checkpoint = pipeline.checkpoint_data or {}
    return {
        "pipeline_id": pipeline.id,
        "status": pipeline.status.value,
        "current_state": pipeline.current_state,
        "proposed_action": checkpoint.get("current_step", "resume"),
        "alternatives": checkpoint.get("alternatives", []),
        "impact": checkpoint.get("impact", {}),
        "checkpoint": checkpoint,
    }


@router.post("/{pipeline_id}/approve")
async def approve_pipeline(
    pipeline_id: str,
    decision: ApprovalDecision,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, str]:
    """Approve a paused pipeline and resume it from checkpoint."""

    pipeline_repo = PipelineRepository(session)
    pipeline = await pipeline_repo.get_by_id(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail={"error": "Pipeline not found"})
    before = {"status": pipeline.status.value, "checkpoint_data": pipeline.checkpoint_data}
    checkpoint = dict(pipeline.checkpoint_data or {})
    checkpoint.setdefault("human_decisions", {})
    checkpoint["human_decisions"]["latest"] = decision.model_dump()
    if decision.modifications:
        checkpoint.update(decision.modifications)
    await pipeline_repo.update(pipeline_id, {"status": PipelineStatus.RUNNING, "checkpoint_data": checkpoint})
    await AuditLogRepository(session).log_action(
        action="HUMAN_DECISION",
        resource_type="pipeline",
        resource_id=pipeline_id,
        user_id=current_user.id,
        before_json=before,
        after_json={"status": PipelineStatus.RUNNING.value, "decision": decision.model_dump()},
        rationale=decision.rationale,
        confidence=1.0,
    )
    await ingest_human_decision(session, pipeline_id, decision.model_dump())
    try:
        await resume_from_checkpoint(pipeline_id)
    except Exception:
        await pipeline_repo.update(pipeline_id, {"status": PipelineStatus.RUNNING})
    return {"status": "resumed", "pipeline_id": pipeline_id}


@router.post("/{pipeline_id}/reject")
async def reject_pipeline(
    pipeline_id: str,
    decision: ApprovalDecision,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, str]:
    """Reject a paused pipeline or route it to an alternative action."""

    pipeline_repo = PipelineRepository(session)
    pipeline = await pipeline_repo.get_by_id(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail={"error": "Pipeline not found"})
    before = {"status": pipeline.status.value, "checkpoint_data": pipeline.checkpoint_data}
    new_status = PipelineStatus.RUNNING if decision.alternative_action else PipelineStatus.FAILED
    checkpoint = dict(pipeline.checkpoint_data or {})
    checkpoint.setdefault("human_decisions", {})
    checkpoint["human_decisions"]["latest"] = decision.model_dump()
    checkpoint["alternative_action"] = decision.alternative_action
    await pipeline_repo.update(
        pipeline_id,
        {"status": new_status, "checkpoint_data": checkpoint, "error_message": None if decision.alternative_action else decision.rationale},
    )
    await AuditLogRepository(session).log_action(
        action="HUMAN_DECISION",
        resource_type="pipeline",
        resource_id=pipeline_id,
        user_id=current_user.id,
        before_json=before,
        after_json={"status": new_status.value, "decision": decision.model_dump()},
        rationale=decision.rationale,
        confidence=1.0,
    )
    await ingest_human_decision(session, pipeline_id, decision.model_dump())
    return {"status": new_status.value, "pipeline_id": pipeline_id}
