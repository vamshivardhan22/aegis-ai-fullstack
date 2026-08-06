"""Dataset upload and metadata API routes."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_current_user, require_role
from src.database.models import Dataset, Project, User, UserRole
from src.database.repository import AuditLogRepository, DatasetRepository, ProjectRepository
from src.database.session import get_async_session
from src.storage import get_storage

router = APIRouter()


class DatasetCreateRequest(BaseModel):
    """JSON dataset creation payload."""

    name: str
    project_id: Optional[str] = None
    source_type: str = "csv"
    content: Optional[str] = None
    schema_json: Optional[dict[str, Any]] = None


@router.post("/")
async def create_dataset(
    payload: DatasetCreateRequest,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, Any]:
    """Create dataset metadata and optionally store CSV content."""

    project_id = payload.project_id or await _ensure_project(session, current_user)
    key = f"bronze/{project_id}/{payload.name}.csv"
    if payload.content is not None:
        await get_storage().write(key, payload.content.encode(), "text/csv")
    dataset = await DatasetRepository(session).create(
        Dataset(
            project_id=project_id,
            name=payload.name,
            source_type=payload.source_type,
            bronze_path=key if payload.content is not None else None,
            schema_json=payload.schema_json,
        )
    )
    await AuditLogRepository(session).log_action(
        action="DATASET_CREATED",
        resource_type="dataset",
        resource_id=dataset.id,
        user_id=current_user.id,
        before_json={},
        after_json={"name": dataset.name, "project_id": project_id},
        rationale="Dataset created through API",
        confidence=1.0,
    )
    return {"id": dataset.id, "project_id": project_id, "name": dataset.name, "bronze_path": dataset.bronze_path}


@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    name: str = Form(...),
    project_id: Optional[str] = Form(default=None),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, Any]:
    """Upload a CSV file and create a dataset record."""

    resolved_project_id = project_id or await _ensure_project(session, current_user)
    data = await file.read()
    key = f"bronze/{resolved_project_id}/{name}.csv"
    await get_storage().write(key, data, file.content_type or "text/csv")
    dataset = await DatasetRepository(session).create(
        Dataset(project_id=resolved_project_id, name=name, source_type="csv", bronze_path=key, size_bytes=len(data))
    )
    await AuditLogRepository(session).log_action(
        action="DATASET_UPLOADED",
        resource_type="dataset",
        resource_id=dataset.id,
        user_id=current_user.id,
        before_json={},
        after_json={"name": dataset.name, "size_bytes": len(data)},
        rationale="Dataset uploaded through API",
        confidence=1.0,
    )
    return {"id": dataset.id, "project_id": resolved_project_id, "name": dataset.name, "bronze_path": key}


@router.get("/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return dataset metadata."""

    del current_user
    dataset = await DatasetRepository(session).get_by_id(dataset_id)
    if dataset is None:
        return {"error": "not_found"}
    return {
        "id": dataset.id,
        "project_id": dataset.project_id,
        "name": dataset.name,
        "source_type": dataset.source_type,
        "bronze_path": dataset.bronze_path,
        "quality_score": dataset.quality_score,
    }


async def _ensure_project(session: AsyncSession, user: User) -> str:
    """Create a default project for uploads that do not specify one."""

    project = await ProjectRepository(session).create(
        Project(name=f"{user.email}-default", owner_id=user.id, config={"created_by": "datasets_api"})
    )
    return project.id
