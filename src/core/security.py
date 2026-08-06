"""Authentication, password hashing, JWTs, and RBAC helpers."""

from collections.abc import Callable
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any, Optional

import bcrypt as bcrypt_backend
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.core.exceptions import ValidationError
from src.database.models import User, UserRole
from src.database.repository import UserRepository
from src.database.session import get_async_session

settings = get_settings()
ALGORITHM = settings.AEGIS_JWT_ALGORITHM or "HS256"
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
if not hasattr(bcrypt_backend, "__about__"):
    bcrypt_backend.__about__ = SimpleNamespace(__version__=getattr(bcrypt_backend, "__version__", "4"))
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    """Hash a password with bcrypt."""

    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain password against a bcrypt hash."""

    return pwd_context.verify(plain, hashed)


def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token with an expiration."""

    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.AEGIS_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.AEGIS_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token."""

    try:
        payload = jwt.decode(token, settings.AEGIS_SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("sub"):
            raise ValidationError("Invalid credentials", {"status_code": 401})
        return payload
    except JWTError as exc:
        raise ValidationError("Invalid credentials", {"status_code": 401}) from exc


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    """Resolve the authenticated user from a bearer token."""

    payload = decode_access_token(token)
    user = await UserRepository(session).get_by_email(str(payload.get("sub")))
    if user is None or not user.is_active:
        raise ValidationError("Invalid credentials", {"status_code": 401})
    return user


def require_role(*allowed_roles: UserRole) -> Callable[[User], User]:
    """Return a dependency that enforces the current user's role."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise ValidationError("Insufficient permissions", {"status_code": 403})
        return current_user

    return dependency


def auth_http_exception(exc: ValidationError) -> HTTPException:
    """Convert auth validation errors into consistent HTTP responses."""

    status_code = int(exc.details.get("status_code", status.HTTP_401_UNAUTHORIZED))
    code = "UNAUTHORIZED" if status_code == status.HTTP_401_UNAUTHORIZED else "FORBIDDEN"
    return HTTPException(status_code=status_code, detail={"detail": exc.message, "code": code})


def google_login_stub(token: str) -> dict[str, str]:
    """Placeholder for future Google OAuth2/OIDC integration."""

    return {"provider": "google", "status": "not_configured", "token_hint": token[:8]}


def saml_login_stub() -> dict[str, str]:
    """Placeholder for future SAML integration."""

    return {"provider": "saml", "status": "not_configured"}
