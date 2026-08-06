"""SQLAlchemy declarative base and reusable mixins."""

from datetime import datetime
from typing import Optional
from uuid import uuid4

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all ORM models."""


class UUIDMixin:
    """Adds a UUID string primary key."""

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))


class TimestampMixin:
    """Adds created and updated timestamps."""

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class AuditMixin:
    """Adds basic actor audit columns."""

    created_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
