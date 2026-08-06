#!/usr/bin/env python
"""Verify Aegis AI Milestone 1 infrastructure."""

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Awaitable, Callable

ROOT = Path(__file__).resolve().parents[1]
VERIFY_ROOT = Path(tempfile.gettempdir()) / "aegis_ai_m1_verify"
VERIFY_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
os.environ["AEGIS_DB_URL"] = f"sqlite+aiosqlite:///{(VERIFY_ROOT / 'verify_m1.db').as_posix()}"
os.environ["AEGIS_STORAGE_BACKEND"] = "local"
os.environ["AEGIS_LOCAL_STORAGE_PATH"] = str(VERIFY_ROOT / "verify_data")
os.environ["AEGIS_DEBUG"] = "false"

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from src.api.main import app  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.database.base import Base  # noqa: E402
from src.database.models import (  # noqa: E402
    AgentType,
    AuditLog,
    Dataset,
    Job,
    Lineage,
    Pipeline,
    PipelineStatus,
    Project,
    Task,
    TaskStatus,
    User,
    UserRole,
)
from src.database.repository import (  # noqa: E402
    AuditLogRepository,
    DatasetRepository,
    JobRepository,
    LineageRepository,
    PipelineRepository,
    ProjectRepository,
    TaskRepository,
    UserRepository,
)
from src.database.session import AsyncSessionLocal, async_engine  # noqa: E402
from src.llm.client import LLMClient  # noqa: E402
from src.storage import get_storage  # noqa: E402

Check = Callable[[], Awaitable[None]]


async def test_config_loading() -> None:
    """Verify settings load expected defaults and helpers."""

    settings = get_settings()
    assert settings.AEGIS_ENV == "development"
    assert settings.is_sqlite
    assert settings.is_async_db
    assert settings.AEGIS_STORAGE_BACKEND == "local"


async def test_create_all_tables() -> None:
    """Verify metadata can create the SQLite schema."""

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    expected = {
        "users",
        "projects",
        "datasets",
        "pipelines",
        "jobs",
        "tasks",
        "models",
        "deployments",
        "experiments",
        "lineage",
        "audit_logs",
        "alerts",
        "documents",
        "metrics",
        "schedules",
    }
    assert expected.issubset(set(Base.metadata.tables.keys()))


async def test_repository_crud() -> None:
    """Verify repository helpers can create and query core graph entities."""

    async with AsyncSessionLocal() as session:
        users = UserRepository(session)
        projects = ProjectRepository(session)
        datasets = DatasetRepository(session)
        pipelines = PipelineRepository(session)
        jobs = JobRepository(session)
        tasks = TaskRepository(session)
        audit_logs = AuditLogRepository(session)
        lineage = LineageRepository(session)

        user = await users.create(
            User(email="owner@example.com", hashed_password="hashed", full_name="Owner", role=UserRole.ADMIN)
        )
        assert (await users.get_by_email("owner@example.com")).id == user.id

        project = await projects.create(Project(name="Demo", description="Verification", owner_id=user.id, config={}))
        assert len(await projects.list_by_owner(user.id)) == 1

        dataset = await datasets.create(Dataset(project_id=project.id, name="orders", source_type="csv"))
        target_dataset = await datasets.create(
            Dataset(project_id=project.id, name="orders_gold", source_type="derived", version=2)
        )
        assert (await datasets.get_latest_version(project.id, "orders")).id == dataset.id

        pipeline = await pipelines.create(
            Pipeline(project_id=project.id, dataset_id=dataset.id, name="orders-pipeline", status=PipelineStatus.RUNNING)
        )
        assert len(await pipelines.list_active()) >= 1

        job = await jobs.create(Job(pipeline_id=pipeline.id, agent_type=AgentType.INGESTION, status=TaskStatus.RUNNING))
        assert len(await jobs.list_by_pipeline(pipeline.id)) == 1

        task = await tasks.create(Task(job_id=job.id, agent_type=AgentType.INGESTION, status=TaskStatus.PENDING))
        assert (await tasks.update(task.id, {"status": TaskStatus.COMPLETED})) is not None

        audit = await audit_logs.log_action(
            action="create",
            resource_type="dataset",
            resource_id=dataset.id,
            user_id=user.id,
            after_json={"name": dataset.name},
        )
        assert audit.id
        assert len(await audit_logs.list_by_resource("dataset", dataset.id, 10)) == 1

        edge = await lineage.create(
            Lineage(
                source_dataset_id=dataset.id,
                target_dataset_id=target_dataset.id,
                transformation_type="aggregate",
                config_json={"group_by": ["date"]},
            )
        )
        assert edge.id
        assert len(await lineage.get_downstream(dataset.id)) == 1
        assert len(await lineage.get_upstream(target_dataset.id)) == 1

        assert await tasks.delete(task.id)
        result = await session.execute(select(AuditLog).where(AuditLog.id == audit.id))
        assert result.scalar_one_or_none() is not None


async def test_storage_adapter() -> None:
    """Verify configured storage can write, read, list, exist, and delete."""

    storage = get_storage()
    key = "verify/sample.txt"
    await storage.write(key, b"aegis", "text/plain")
    assert await storage.exists(key)
    assert await storage.read(key) == b"aegis"
    assert key in await storage.list_keys("verify")
    assert await storage.get_url(key)
    assert await storage.delete(key)
    assert not await storage.exists(key)


async def test_llm_client_initialization() -> None:
    """Verify the LLM client can be initialized and closed."""

    client = LLMClient()
    assert client.settings.AEGIS_LLM_MODEL
    await client.close()


async def test_fastapi_health_endpoint() -> None:
    """Verify the FastAPI app imports and serves the health endpoint."""

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["checks"]["database"]["status"] == "healthy"
    assert payload["checks"]["storage"]["status"] == "healthy"


async def run_check(name: str, check: Check) -> bool:
    """Run a check and print a PASS/FAIL line."""

    try:
        await check()
        print(f"PASS {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


async def main() -> int:
    """Run all verification checks and return a process exit code."""

    db_path = VERIFY_ROOT / "verify_m1.db"
    storage_path = VERIFY_ROOT / "verify_data"
    if db_path.exists():
        db_path.unlink()
    if storage_path.exists():
        shutil.rmtree(storage_path)
    VERIFY_ROOT.mkdir(parents=True, exist_ok=True)

    checks: list[tuple[str, Check]] = [
        ("config loading", test_config_loading),
        ("create all SQLite tables and metadata table count", test_create_all_tables),
        ("repository CRUD", test_repository_crud),
        ("storage adapter", test_storage_adapter),
        ("LLM client initialization", test_llm_client_initialization),
        ("FastAPI app import and health endpoint", test_fastapi_health_endpoint),
    ]
    results = [await run_check(name, check) for name, check in checks]
    passed = sum(1 for result in results if result)
    failed = len(results) - passed
    print(f"SUMMARY passed={passed} failed={failed}")
    await async_engine.dispose()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
