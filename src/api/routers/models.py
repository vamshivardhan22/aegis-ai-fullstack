"""Project-scoped model registry and artifact download endpoints."""
from __future__ import annotations

import hashlib
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.security import get_current_user
from src.core.tenancy import require_project_access
from src.database.models import Dataset, Model, Project, User, UserRole
from src.database.session import get_async_session
from src.storage import get_storage

router = APIRouter()


def _serialize(model: Model) -> dict[str, Any]:
    dataset = model.dataset
    return {
        "id": model.id,
        "name": model.name,
        "algorithm": model.algorithm,
        "problem_type": model.problem_type,
        "status": model.status.value,
        "is_active": model.is_active,
        "metrics": model.metrics_json or {},
        "parameters": model.parameters_json or {},
        "artifact_available": bool(model.artifact_path),
        "dataset_id": model.dataset_id,
        "dataset_name": dataset.name if dataset else None,
        "project_id": dataset.project_id if dataset else None,
        "created_at": model.created_at.isoformat() if model.created_at else None,
    }


@router.get("/")
async def list_models(
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    """List models only from projects the current user can access."""
    query = (
        select(Model)
        .join(Dataset, Dataset.id == Model.dataset_id)
        .join(Project, Project.id == Dataset.project_id)
        .options(selectinload(Model.dataset))
        .where(Dataset.is_deleted.is_(False))
    )
    if current_user.role != UserRole.ADMIN:
        query = query.where(Project.owner_id == current_user.id)
    result = await session.execute(query.order_by(Model.created_at.desc()).limit(200))
    return {"models": [_serialize(model) for model in result.scalars().all()]}


@router.get("/{model_id}")
async def get_model(
    model_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return model metadata after checking the source dataset's project."""
    result = await session.execute(
        select(Model).options(selectinload(Model.dataset)).where(Model.id == model_id)
    )
    model = result.scalar_one_or_none()
    if model is None or model.dataset is None or model.dataset.is_deleted:
        raise HTTPException(status_code=404, detail="Model not found")
    await require_project_access(session, current_user, model.dataset.project_id)
    return _serialize(model)


@router.get("/{model_id}/download")
async def download_model(
    model_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Download a registered model artifact without deserializing it on the server."""
    result = await session.execute(
        select(Model).options(selectinload(Model.dataset)).where(Model.id == model_id)
    )
    model = result.scalar_one_or_none()
    if model is None or model.dataset is None or model.dataset.is_deleted or not model.artifact_path:
        raise HTTPException(status_code=404, detail="Model artifact not found")
    await require_project_access(session, current_user, model.dataset.project_id)
    data = await get_storage().read(model.artifact_path)
    digest = hashlib.sha256(data).hexdigest()
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", model.name)[:100] or "model"
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}.joblib"',
            "X-Content-SHA256": digest,
        },
    )
