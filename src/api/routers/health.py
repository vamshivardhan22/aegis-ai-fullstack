"""Health check endpoints."""

from typing import Any

from fastapi import APIRouter
from sqlalchemy import text

from src.database.session import AsyncSessionLocal
from src.storage import get_storage

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, Any]:
    """Return service health across database and storage dependencies."""

    checks: dict[str, dict[str, Any]] = {}
    healthy = True

    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = {"status": "healthy"}
    except Exception as exc:
        healthy = False
        checks["database"] = {"status": "unhealthy", "error": str(exc)}

    try:
        storage = get_storage()
        key = "health-check/test.txt"
        await storage.write(key, b"ok", "text/plain")
        data = await storage.read(key)
        await storage.delete(key)
        checks["storage"] = {"status": "healthy" if data == b"ok" else "unhealthy"}
        healthy = healthy and data == b"ok"
    except Exception as exc:
        healthy = False
        checks["storage"] = {"status": "unhealthy", "error": str(exc)}

    return {
        "status": "healthy" if healthy else "degraded",
        "version": "2.0.0-m1",
        "checks": checks,
    }
