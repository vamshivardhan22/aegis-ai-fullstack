"""Dataset ingestion and metadata routes with project isolation and bounded CSV parsing."""
from __future__ import annotations

import hashlib
import io
import re
from typing import Any
from uuid import uuid4

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_current_user, require_role
from src.core.tenancy import require_dataset_access, require_project_access
from src.database.models import Dataset, Project, User, UserRole
from src.database.repository import AuditLogRepository, DatasetRepository, ProjectRepository
from src.database.session import get_async_session
from src.storage import get_storage

router = APIRouter()
MAX_CSV_BYTES = 10 * 1024 * 1024
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,99}$")


class DatasetCreateRequest(BaseModel):
    """JSON dataset creation payload."""

    name: str = Field(min_length=1, max_length=100)
    project_id: str | None = None
    source_type: str = "csv"
    content: str | None = None
    schema_json: dict[str, Any] | None = None


def _validate_name(name: str) -> str:
    """Prevent path traversal and ambiguous storage keys."""
    if not _SAFE_NAME.fullmatch(name) or ".." in name or name.endswith((".", " ")):
        raise HTTPException(status_code=422, detail="Dataset name contains unsupported characters")
    return name


def _profile_csv(data: bytes) -> tuple[dict[str, str], dict[str, Any], int, int]:
    """Parse and profile a bounded CSV payload; reject empty or malformed data."""
    try:
        frame = pd.read_csv(io.BytesIO(data))
    except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Upload must be a valid UTF-8 CSV file") from exc
    if frame.empty and len(frame.columns) == 0:
        raise HTTPException(status_code=422, detail="CSV must contain a header row")
    if len(frame.columns) == 0:
        raise HTTPException(status_code=422, detail="CSV must contain at least one column")
    if len(frame.columns) > 500:
        raise HTTPException(status_code=422, detail="CSV exceeds the 500-column limit")
    schema = {str(column): str(dtype) for column, dtype in frame.dtypes.items()}
    profile = {
        "row_count": len(frame),
        "column_count": len(frame.columns),
        "null_counts": {str(column): int(count) for column, count in frame.isna().sum().items()},
        "duplicate_rows": int(frame.duplicated().sum()),
        "sha256": hashlib.sha256(data).hexdigest(),
        "profile_version": 1,
    }
    return schema, profile, len(frame), len(frame.columns)


@router.post("/")
async def create_dataset(
    payload: DatasetCreateRequest,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, Any]:
    """Create dataset metadata and optionally store validated CSV content."""
    name = _validate_name(payload.name)
    project_id = payload.project_id or await _ensure_project(session, current_user)
    await require_project_access(session, current_user, project_id)
    data = payload.content.encode("utf-8") if payload.content is not None else None
    if data is not None and payload.source_type.lower() != "csv":
        raise HTTPException(status_code=422, detail="Inline content is supported only for CSV datasets")
    if data is not None and len(data) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV exceeds the 10 MiB upload limit")
    schema, profile, rows, columns = _profile_csv(data) if data is not None else ({}, {}, 0, 0)
    key = f"bronze/{project_id}/{uuid4().hex}/{name}.csv"
    if data is not None:
        await get_storage().write(key, data, "text/csv")
    dataset = await DatasetRepository(session).create(
        Dataset(
            project_id=project_id,
            name=name,
            source_type=payload.source_type,
            bronze_path=key if data is not None else None,
            schema_json=schema or payload.schema_json,
            profile_json=profile or None,
            row_count=rows if data is not None else None,
            column_count=columns if data is not None else None,
            size_bytes=len(data) if data is not None else None,
        )
    )
    await AuditLogRepository(session).log_action(
        action="DATASET_CREATED",
        resource_type="dataset",
        resource_id=dataset.id,
        user_id=current_user.id,
        before_json={},
        after_json={"name": dataset.name, "project_id": project_id, "profile": profile},
        rationale="Dataset created through validated API ingestion",
        confidence=1.0,
    )
    return {
        "id": dataset.id,
        "project_id": project_id,
        "name": dataset.name,
        "bronze_path": dataset.bronze_path,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "size_bytes": dataset.size_bytes,
        "schema": dataset.schema_json,
        "profile": dataset.profile_json,
    }


@router.post("/upload")
async def upload_dataset(
    file: UploadFile = File(...),
    name: str = Form(...),
    project_id: str | None = Form(default=None),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, Any]:
    """Upload a bounded CSV file and persist its schema/profile metadata."""
    name = _validate_name(name)
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Only .csv uploads are supported")
    resolved_project_id = project_id or await _ensure_project(session, current_user)
    await require_project_access(session, current_user, resolved_project_id)
    data = await file.read(MAX_CSV_BYTES + 1)
    if len(data) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV exceeds the 10 MiB upload limit")
    if not data:
        raise HTTPException(status_code=422, detail="CSV upload is empty")
    schema, profile, rows, columns = _profile_csv(data)
    key = f"bronze/{resolved_project_id}/{uuid4().hex}/{name}.csv"
    await get_storage().write(key, data, "text/csv")
    dataset = await DatasetRepository(session).create(
        Dataset(
            project_id=resolved_project_id,
            name=name,
            source_type="csv",
            bronze_path=key,
            schema_json=schema,
            profile_json=profile,
            row_count=rows,
            column_count=columns,
            size_bytes=len(data),
        )
    )
    await AuditLogRepository(session).log_action(
        action="DATASET_UPLOADED",
        resource_type="dataset",
        resource_id=dataset.id,
        user_id=current_user.id,
        before_json={},
        after_json={"name": dataset.name, "size_bytes": len(data), "profile": profile},
        rationale="CSV uploaded, parsed, and profiled",
        confidence=1.0,
    )
    return {
        "id": dataset.id,
        "project_id": resolved_project_id,
        "name": dataset.name,
        "bronze_path": key,
        "row_count": rows,
        "column_count": columns,
        "size_bytes": len(data),
        "schema": schema,
        "profile": profile,
    }


@router.get("/")
async def list_datasets(
    project_id: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    """List datasets only in projects the caller can access."""
    query = select(Dataset).join(Project, Project.id == Dataset.project_id).where(Dataset.is_deleted.is_(False))
    if current_user.role != UserRole.ADMIN:
        query = query.where(Project.owner_id == current_user.id)
    if project_id:
        await require_project_access(session, current_user, project_id)
        query = query.where(Dataset.project_id == project_id)
    result = await session.execute(query.order_by(Dataset.created_at.desc()).limit(200))
    datasets = result.scalars().all()
    return {"datasets": [
        {
            "id": item.id,
            "project_id": item.project_id,
            "name": item.name,
            "source_type": item.source_type,
            "row_count": item.row_count,
            "column_count": item.column_count,
            "quality_score": item.quality_score,
            "has_bronze_artifact": bool(item.bronze_path),\n            "has_csv_artifact": bool(item.bronze_path or item.silver_path or item.gold_path),
        } for item in datasets
    ]}


@router.get("/{dataset_id}/download")
async def download_dataset(
    dataset_id: str,
    layer: str = "silver",
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    """Download an authorized dataset layer as CSV."""
    if layer not in {"bronze", "silver", "gold"}:
        raise HTTPException(status_code=422, detail="layer must be bronze, silver, or gold")
    dataset = await require_dataset_access(session, current_user, dataset_id)
    artifact_path = getattr(dataset, f"{layer}_path")
    if not artifact_path:
        raise HTTPException(status_code=404, detail=f"No {layer} artifact is available")
    data = await get_storage().read(artifact_path)
    digest = hashlib.sha256(data).hexdigest()
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", dataset.name)[:100]
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}-{layer}.csv"',
            "X-Content-SHA256": digest,
        },
    )


@router.get("/{dataset_id}")
async def get_dataset(
    dataset_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return metadata for a dataset visible to the caller."""
    dataset = await require_dataset_access(session, current_user, dataset_id)
    return {
        "id": dataset.id,
        "project_id": dataset.project_id,
        "name": dataset.name,
        "source_type": dataset.source_type,
        "bronze_path": dataset.bronze_path,
        "silver_path": dataset.silver_path,
        "gold_path": dataset.gold_path,
        "schema_json": dataset.schema_json,
        "profile_json": dataset.profile_json,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "size_bytes": dataset.size_bytes,
        "quality_score": dataset.quality_score,
        "version": dataset.version,
    }


async def _ensure_project(session: AsyncSession, user: User) -> str:
    """Reuse the user's default project or create it once."""
    result = await session.execute(
        select(Project).where(Project.owner_id == user.id, Project.name == f"{user.email}-default")
    )
    project = result.scalar_one_or_none()
    if project is None:
        project = await ProjectRepository(session).create(
            Project(name=f"{user.email}-default", owner_id=user.id, config={"created_by": "datasets_api"})
        )
    return project.id
