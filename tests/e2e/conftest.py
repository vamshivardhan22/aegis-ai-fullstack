"""E2E pytest fixtures for Aegis AI."""

import os
import tempfile
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

ROOT = Path(tempfile.gettempdir()) / "aegis_ai_e2e"
ROOT.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("AEGIS_DB_URL", f"sqlite+aiosqlite:///{(ROOT / 'e2e.db').as_posix()}")
os.environ.setdefault("AEGIS_STORAGE_BACKEND", "local")
os.environ.setdefault("AEGIS_LOCAL_STORAGE_PATH", str(ROOT / "storage"))
os.environ.setdefault("AEGIS_DEBUG", "false")

from src.api.main import app  # noqa: E402
from src.database.base import Base  # noqa: E402
from src.database.session import async_engine  # noqa: E402


@pytest.fixture()
async def client() -> AsyncClient:
    """Return an isolated ASGI test client."""

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as test_client:
        yield test_client
