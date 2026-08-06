"""FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.routers import admin, agents, approval, auth, chat, datasets, lineage
from src.api.routers.health import router as health_router
from src.config import get_settings
from src.core.exceptions import ValidationError
from src.core.logging import configure_logging
from src.core.rate_limit import RateLimitMiddleware
from src.database.base import Base
from src.database.session import async_engine

settings = get_settings()
logger = configure_logging(settings.AEGIS_DEBUG)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown."""

    logger.info("aegis_startup", env=settings.AEGIS_ENV)
    if settings.is_sqlite:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    try:
        yield
    finally:
        logger.info("aegis_shutdown")
        await async_engine.dispose()


app = FastAPI(title="Aegis AI", version="2.0.0-m4", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware, requests_per_minute=240)
app.include_router(health_router)
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(agents.router, prefix="/agents", tags=["agents"])
app.include_router(approval.router, prefix="/approvals", tags=["approvals"])
app.include_router(chat.router, prefix="/chat", tags=["chat"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])
app.include_router(lineage.router, prefix="/lineage", tags=["lineage"])
app.include_router(datasets.router, prefix="/datasets", tags=["datasets"])


@app.exception_handler(ValidationError)
async def validation_error_handler(request, exc: ValidationError) -> JSONResponse:
    """Return consistent JSON for validation and authorization failures."""

    del request
    status_code = int(exc.details.get("status_code", exc.status_code))
    code = "UNAUTHORIZED" if status_code == 401 else "FORBIDDEN" if status_code == 403 else exc.code
    return JSONResponse(status_code=status_code, content={"detail": exc.message, "code": code})


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException) -> JSONResponse:
    """Normalize auth HTTP errors while preserving other error details."""

    del request
    if exc.status_code in {401, 403}:
        code = "UNAUTHORIZED" if exc.status_code == 401 else "FORBIDDEN"
        detail = exc.detail
        if isinstance(detail, dict):
            message = str(detail.get("detail", detail.get("message", code)))
            code = str(detail.get("code", code))
        else:
            message = str(detail)
        return JSONResponse(status_code=exc.status_code, content={"detail": message, "code": code})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/")
async def root() -> dict[str, str]:
    """Return basic application metadata."""

    return {"name": "Aegis AI", "version": "2.0.0-m5", "milestone": "M5: Production Hardening"}
