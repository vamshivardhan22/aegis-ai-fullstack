"""Authentication API routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.core.security import create_access_token, get_current_user, get_password_hash, oauth2_scheme, verify_password
from src.database.models import User, UserRole
from src.database.repository import AuditLogRepository, UserRepository
from src.database.session import get_async_session

router = APIRouter()


class RegisterRequest(BaseModel):
    """User registration payload."""

    email: str
    password: str = Field(min_length=8)
    full_name: Optional[str] = None
    role: Optional[UserRole] = UserRole.VIEWER

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Validate a simple email address without extra runtime dependencies."""

        if "@" not in value or "." not in value.rsplit("@", 1)[-1]:
            raise ValueError("Invalid email address")
        return value.lower()


class LoginRequest(BaseModel):
    """User login payload for JSON clients."""

    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        """Normalize email usernames for authentication."""

        return value.lower()


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, session: AsyncSession = Depends(get_async_session)) -> dict[str, str]:
    """Register a new platform user."""

    repo = UserRepository(session)
    try:
        user = await repo.create(
            User(
                email=payload.email,
                hashed_password=get_password_hash(payload.password),
                full_name=payload.full_name,
                role=payload.role or UserRole.VIEWER,
            )
        )
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail={"detail": "User already exists", "code": "USER_EXISTS"}) from exc
    await AuditLogRepository(session).log_action(
        action="USER_REGISTERED",
        resource_type="user",
        resource_id=user.id,
        user_id=user.id,
        before_json={},
        after_json={"email": user.email, "role": user.role.value},
        rationale="User registration",
        confidence=1.0,
    )
    return {"id": user.id, "email": user.email, "role": user.role.value}


@router.post("/login")
async def login(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, str | int]:
    """Authenticate a user and return a bearer token."""

    content_type = request.headers.get("content-type", "")
    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        form_data = await request.form()
        email = str(form_data.get("username") or form_data.get("email") or "").lower()
        password = str(form_data.get("password") or "")
    else:
        try:
            payload = LoginRequest.model_validate(await request.json())
        except Exception as exc:
            raise HTTPException(status_code=422, detail={"detail": "Invalid login payload", "code": "VALIDATION_ERROR"}) from exc
        email = payload.email
        password = payload.password

    user = await UserRepository(session).get_by_email(email)
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=401, detail={"detail": "Invalid credentials", "code": "UNAUTHORIZED"})
    token = create_access_token({"sub": user.email, "role": user.role.value, "user_id": user.id})
    await AuditLogRepository(session).log_action(
        action="USER_LOGIN",
        resource_type="user",
        resource_id=user.id,
        user_id=user.id,
        before_json={},
        after_json={"email": user.email},
        rationale="Successful login",
        confidence=1.0,
    )
    return {"access_token": token, "token_type": "bearer", "expires_in": get_settings().AEGIS_ACCESS_TOKEN_EXPIRE_MINUTES}


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)) -> dict[str, str | None]:
    """Return the current authenticated user's profile."""

    return {
        "id": current_user.id,
        "email": current_user.email,
        "full_name": current_user.full_name,
        "role": current_user.role.value,
        "org_id": current_user.org_id,
    }


@router.post("/refresh")
async def refresh(
    token: str = Depends(oauth2_scheme),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Refresh a valid bearer token."""

    del token
    refreshed = create_access_token({"sub": current_user.email, "role": current_user.role.value, "user_id": current_user.id})
    return {"access_token": refreshed, "token_type": "bearer"}
