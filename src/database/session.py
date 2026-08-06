"""Database engine and session helpers."""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker

from src.config import get_settings
from src.core.exceptions import AegisError, DatabaseError

settings = get_settings()


def _to_async_url(url: str) -> str:
    """Convert a database URL to a SQLAlchemy async driver URL when needed."""

    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _to_sync_url(url: str) -> str:
    """Strip async SQLAlchemy driver fragments for sync usage."""

    return url.replace("+aiosqlite", "").replace("+asyncpg", "")


def _engine_kwargs(url: str) -> dict[str, Any]:
    """Return connection-pool arguments appropriate for the database backend."""

    kwargs: dict[str, Any] = {"pool_pre_ping": True, "echo": settings.AEGIS_DEBUG}
    if not url.startswith("sqlite"):
        kwargs["pool_size"] = settings.AEGIS_DB_POOL_SIZE
        kwargs["max_overflow"] = settings.AEGIS_DB_MAX_OVERFLOW
    return kwargs


async_engine: AsyncEngine = create_async_engine(_to_async_url(settings.AEGIS_DB_URL), **_engine_kwargs(settings.AEGIS_DB_URL))
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

sync_engine: Engine = create_engine(_to_sync_url(settings.AEGIS_DB_URL), **_engine_kwargs(_to_sync_url(settings.AEGIS_DB_URL)))
SessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session for FastAPI dependencies."""

    async with AsyncSessionLocal() as session:
        try:
            yield session
        except (AegisError, HTTPException, RequestValidationError):
            await session.rollback()
            raise
        except Exception as exc:
            await session.rollback()
            raise DatabaseError("Async database session failed", {"error": str(exc)}) from exc
        finally:
            await session.close()


@asynccontextmanager
async def async_session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async transactional session scope."""

    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as exc:
            await session.rollback()
            raise DatabaseError("Async database transaction failed", {"error": str(exc)}) from exc
        finally:
            await session.close()


def get_sync_session() -> Generator[Session, None, None]:
    """Yield a sync session for scripts and Alembic-adjacent workflows."""

    session = SessionLocal()
    try:
        yield session
    except Exception as exc:
        session.rollback()
        raise DatabaseError("Sync database session failed", {"error": str(exc)}) from exc
    finally:
        session.close()
