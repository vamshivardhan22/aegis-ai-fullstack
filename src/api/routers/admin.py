"""Administrative API routes."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import require_role
from src.database.models import AuditLog, User, UserRole
from src.database.repository import AuditLogRepository, UserRepository
from src.database.session import get_async_session

router = APIRouter()


class RoleUpdate(BaseModel):
    """User role update payload."""

    role: UserRole


@router.get("/users")
async def list_users(
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> dict[str, list[dict[str, str | bool | None]]]:
    """List all platform users."""

    del current_user
    users = await UserRepository(session).list_all(limit=500)
    return {
        "users": [
            {
                "id": user.id,
                "email": user.email,
                "full_name": user.full_name,
                "role": user.role.value,
                "is_active": user.is_active,
            }
            for user in users
        ]
    }


@router.put("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    payload: RoleUpdate,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> dict[str, str]:
    """Change a user's role."""

    repo = UserRepository(session)
    before = await repo.get_by_id(user_id)
    if before is None:
        raise HTTPException(status_code=404, detail={"detail": "User not found", "code": "NOT_FOUND"})
    user = await repo.update(user_id, {"role": payload.role})
    await AuditLogRepository(session).log_action(
        action="USER_ROLE_CHANGED",
        resource_type="user",
        resource_id=user_id,
        user_id=current_user.id,
        before_json={"role": before.role.value},
        after_json={"role": payload.role.value},
        rationale="Admin role update",
        confidence=1.0,
    )
    return {"id": user.id, "role": user.role.value}


@router.delete("/users/{user_id}")
async def deactivate_user(
    user_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> dict[str, str]:
    """Deactivate a user without deleting the audit trail."""

    repo = UserRepository(session)
    user = await repo.get_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail={"detail": "User not found", "code": "NOT_FOUND"})
    await repo.update(user_id, {"is_active": False})
    await AuditLogRepository(session).log_action(
        action="USER_DEACTIVATED",
        resource_type="user",
        resource_id=user_id,
        user_id=current_user.id,
        before_json={"is_active": True},
        after_json={"is_active": False},
        rationale="Admin deactivation",
        confidence=1.0,
    )
    return {"id": user_id, "status": "deactivated"}


@router.get("/audit-logs")
async def audit_logs(
    resource_type: Optional[str] = None,
    user_id: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    limit: int = Query(default=100, le=500),
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
) -> dict[str, list[dict[str, object]]]:
    """Return paginated audit logs with optional filters."""

    del current_user
    query = select(AuditLog)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if start_date:
        query = query.where(AuditLog.created_at >= start_date)
    if end_date:
        query = query.where(AuditLog.created_at <= end_date)
    result = await session.execute(query.order_by(AuditLog.created_at.desc()).limit(limit))
    logs = result.scalars().all()
    return {
        "audit_logs": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "before_json": log.before_json,
                "after_json": log.after_json,
                "created_at": log.created_at.isoformat(),
            }
            for log in logs
        ]
    }
