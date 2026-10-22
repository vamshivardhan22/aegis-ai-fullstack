"""Project-scoped authorization helpers.

Resources are intentionally hidden with 404 when a caller cannot access them,
so the API does not reveal cross-project identifiers.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException

from src.database.models import Dataset, Project, User, UserRole


async def require_project_access(session: AsyncSession, user: User, project_id: str) -> Project:
    """Return a project only when the caller owns it or is a platform admin."""
    project = await session.get(Project, project_id)
    if project is None or (user.role != UserRole.ADMIN and project.owner_id != user.id):
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def require_dataset_access(session: AsyncSession, user: User, dataset_id: str) -> Dataset:
    """Return a dataset only when the caller can access its parent project."""
    result = await session.execute(
        select(Dataset, Project.owner_id)
        .join(Project, Project.id == Dataset.project_id)
        .where(Dataset.id == dataset_id, Dataset.is_deleted.is_(False))
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    dataset, owner_id = row
    if user.role != UserRole.ADMIN and owner_id != user.id:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset


async def require_dataset_path_access(
    session: AsyncSession, user: User, dataset_id: str, artifact_path: str
) -> Dataset:
    """Ensure a requested artifact path is one of the authorized dataset's known layers."""
    dataset = await require_dataset_access(session, user, dataset_id)
    allowed_paths = {dataset.bronze_path, dataset.silver_path, dataset.gold_path}
    if not artifact_path or artifact_path not in allowed_paths:
        raise HTTPException(status_code=404, detail="Dataset artifact not found")
    return dataset
