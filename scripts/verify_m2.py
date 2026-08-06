#!/usr/bin/env python
"""Verify Aegis AI Milestone 2 agent completion."""

import asyncio
import io
import json
import os
import pickle
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

ROOT = Path(__file__).resolve().parents[1]
VERIFY_ROOT = Path(tempfile.gettempdir()) / "aegis_ai_m2_verify"
VERIFY_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
os.environ["AEGIS_DB_URL"] = f"sqlite+aiosqlite:///{(VERIFY_ROOT / 'verify_m2.db').as_posix()}"
os.environ["AEGIS_STORAGE_BACKEND"] = "local"
os.environ["AEGIS_LOCAL_STORAGE_PATH"] = str(VERIFY_ROOT / "verify_data")
os.environ["AEGIS_DEBUG"] = "false"

import httpx  # noqa: E402
import pandas as pd  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from src.agents.deploy import DeployAgent  # noqa: E402
from src.agents.drift import DriftAgent  # noqa: E402
from src.agents.explain import ExplainAgent  # noqa: E402
from src.agents.monitor import MonitorAgent  # noqa: E402
from src.agents.transform import TransformAgent  # noqa: E402
from src.api.main import app  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.database.base import Base  # noqa: E402
from src.database.models import (  # noqa: E402
    AgentType,
    AuditLog,
    Dataset,
    Job,
    Lineage,
    Metric,
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
    MetricRepository,
    PipelineRepository,
    ProjectRepository,
    TaskRepository,
    UserRepository,
)
from src.database.session import AsyncSessionLocal, async_engine  # noqa: E402
from src.llm.client import LLMClient  # noqa: E402
from src.storage import get_storage  # noqa: E402
from src.storage.base import StorageAdapter  # noqa: E402

Check = Callable[[], Awaitable[None]]


class MemoryStorage(StorageAdapter):
    """Small async storage adapter for deterministic verifier fixtures."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def write(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.objects[key.lstrip("/")] = data
        return key.lstrip("/")

    async def read(self, key: str) -> bytes:
        return self.objects[key.lstrip("/")]

    async def delete(self, key: str) -> bool:
        return self.objects.pop(key.lstrip("/"), None) is not None

    async def exists(self, key: str) -> bool:
        return key.lstrip("/") in self.objects

    async def list_keys(self, prefix: str = "") -> list[str]:
        return sorted(key for key in self.objects if key.startswith(prefix))

    async def get_url(self, key: str) -> str:
        return key.lstrip("/")


class MockLLM:
    """Deterministic LLM stand-in for verifier checks."""

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        expect_json: bool = False,
    ) -> str:
        if "Return JSON keys drift_detected" in prompt:
            return json.dumps(
                {
                    "drift_detected": True,
                    "affected_features": ["amount"],
                    "severity": "significant",
                    "recommendation": "Retrain the model with recent data.",
                }
            )
        if "code, explanation, output_columns" in prompt:
            return json.dumps(
                {
                    "code": "result = df.groupby('category', as_index=False)['amount'].sum()",
                    "explanation": "Grouped by category and summed amount.",
                    "output_columns": ["category", "amount"],
                }
            )
        return json.dumps(
            {
                "summary": "The model is most influenced by amount and age.",
                "top_features": [
                    {"name": "amount", "importance": 0.5, "direction": "positive"},
                    {"name": "age", "importance": 0.2, "direction": "positive"},
                ],
                "business_insight": "Higher amount values increase the predicted class likelihood.",
            }
        )

    async def close(self) -> None:
        pass


async def reset_database() -> None:
    """Recreate all verifier tables."""

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def seed_project_dataset(session: Any, dataset_name: str = "orders") -> tuple[User, Project, Dataset]:
    """Create a minimal owner, project, and dataset graph."""

    user = await UserRepository(session).create(
        User(email=f"{dataset_name}@example.com", hashed_password="hashed", full_name="Owner", role=UserRole.ADMIN)
    )
    project = await ProjectRepository(session).create(Project(name=f"{dataset_name}-project", owner_id=user.id, config={}))
    dataset = await DatasetRepository(session).create(
        Dataset(project_id=project.id, name=dataset_name, source_type="csv", bronze_path=f"{dataset_name}.csv")
    )
    return user, project, dataset


class SimpleModel:
    """Pickle-friendly model fixture with a predict method."""

    def predict(self, frame: pd.DataFrame) -> list[int]:
        return [1 if row["amount"] > 20 else 0 for _, row in frame.iterrows()]


def dump_model(obj: Any) -> bytes:
    """Serialize an object to bytes."""

    return pickle.dumps(obj)


async def test_config_loading() -> None:
    """Verify settings load expected defaults and helpers."""

    settings = get_settings()
    assert settings.AEGIS_ENV == "development"
    assert settings.is_sqlite
    assert settings.is_async_db
    assert settings.AEGIS_STORAGE_BACKEND == "local"


async def test_create_all_tables() -> None:
    """Verify metadata can create the SQLite schema."""

    await reset_database()
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

    await reset_database()
    async with AsyncSessionLocal() as session:
        users = UserRepository(session)
        projects = ProjectRepository(session)
        datasets = DatasetRepository(session)
        pipelines = PipelineRepository(session)
        jobs = JobRepository(session)
        tasks = TaskRepository(session)
        audit_logs = AuditLogRepository(session)
        lineage = LineageRepository(session)

        user = await users.create(User(email="owner@example.com", hashed_password="hashed", role=UserRole.ADMIN))
        assert (await users.get_by_email("owner@example.com")).id == user.id
        project = await projects.create(Project(name="Demo", description="Verification", owner_id=user.id, config={}))
        dataset = await datasets.create(Dataset(project_id=project.id, name="orders", source_type="csv"))
        target_dataset = await datasets.create(Dataset(project_id=project.id, name="orders_gold", source_type="derived"))
        pipeline = await pipelines.create(
            Pipeline(project_id=project.id, dataset_id=dataset.id, name="orders-pipeline", status=PipelineStatus.RUNNING)
        )
        job = await jobs.create(Job(pipeline_id=pipeline.id, agent_type=AgentType.INGESTION, status=TaskStatus.RUNNING))
        task = await tasks.create(Task(job_id=job.id, agent_type=AgentType.INGESTION, status=TaskStatus.PENDING))
        audit = await audit_logs.log_action("create", "dataset", dataset.id, after_json={"name": dataset.name})
        edge = await lineage.create(
            Lineage(source_dataset_id=dataset.id, target_dataset_id=target_dataset.id, transformation_type="aggregate")
        )
        assert len(await projects.list_by_owner(user.id)) == 1
        assert len(await pipelines.list_active()) >= 1
        assert len(await jobs.list_by_pipeline(pipeline.id)) == 1
        assert (await tasks.update(task.id, {"status": TaskStatus.COMPLETED})) is not None
        assert audit.id and edge.id


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
        agents_response = await client.get("/agents/")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    assert agents_response.status_code == 200
    assert "explain" in agents_response.json()["agent_types"]


async def test_m1_agents_placeholder() -> None:
    """Verify M1-to-M2 agent package import surface."""

    import src.agents  # noqa: F401


async def test_explain_agent() -> None:
    """Verify ExplainAgent stores top features and audits the decision."""

    await reset_database()
    storage = MemoryStorage()
    sample = pd.DataFrame({"amount": [10, 20, 30, 40], "age": [21, 33, 45, 57]})
    model = SimpleModel()
    await storage.write("models/model.pkl", dump_model(model))
    await storage.write("samples/sample.csv", sample.to_csv(index=False).encode())
    async with AsyncSessionLocal() as session:
        result = await ExplainAgent("explain", MockLLM(), session, storage).execute(
            {
                "model_id": "model-1",
                "dataset_id": "dataset-1",
                "model_artifact_path": "models/model.pkl",
                "sample_data_path": "samples/sample.csv",
            }
        )
        assert isinstance(result["top_features"], list)
        audits = await AuditLogRepository(session).list_by_resource("agent", "explain")
        assert audits


async def test_deploy_agent() -> None:
    """Verify DeployAgent emits service artifacts."""

    await reset_database()
    storage = MemoryStorage()
    await storage.write("models/model.pkl", dump_model({"model": True}))
    async with AsyncSessionLocal() as session:
        result = await DeployAgent("deploy", MockLLM(), session, storage).execute(
            {
                "model_id": "model-2",
                "model_artifact_path": "models/model.pkl",
                "encoder_artifacts": {},
                "feature_columns": ["amount", "age"],
                "target_column": "approved",
                "model_type": "classification",
            }
        )
    service_code = (await storage.read(result["service_code_path"])).decode()
    dockerfile = (await storage.read(result["dockerfile_path"])).decode()
    assert "class InputModel" in service_code
    assert '"/predict"' in service_code
    assert "FROM python:3.11-slim" in dockerfile


async def test_monitor_agent() -> None:
    """Verify MonitorAgent records metrics for successful probes."""

    await reset_database()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "healthy"})
        if request.url.path == "/predict":
            return httpx.Response(200, json={"prediction": 1, "confidence": 0.9})
        return httpx.Response(404)

    async with AsyncSessionLocal() as session:
        result = await MonitorAgent("monitor", MockLLM(), session, MemoryStorage()).execute(
            {
                "deployment_id": None,
                "model_id": "model-3",
                "endpoint_url": "http://model.test",
                "alert_thresholds": {"latency_p95_ms": 500},
                "dummy_payload": {"amount": 10},
                "_transport": httpx.MockTransport(handler),
            }
        )
        metrics = (await session.execute(select(Metric))).scalars().all()
    assert "latency_ms" in result
    assert result["is_healthy"] is True
    assert metrics


async def test_drift_agent() -> None:
    """Verify DriftAgent calculates PSI for shifted distributions."""

    await reset_database()
    storage = MemoryStorage()
    baseline = pd.DataFrame({"amount": list(range(100)), "category": ["a"] * 90 + ["b"] * 10})
    current = pd.DataFrame({"amount": list(range(100, 200)), "category": ["a"] * 20 + ["b"] * 80})
    await storage.write("baseline.csv", baseline.to_csv(index=False).encode())
    await storage.write("current.csv", current.to_csv(index=False).encode())
    async with AsyncSessionLocal() as session:
        result = await DriftAgent("drift", MockLLM(), session, storage).execute(
            {
                "model_id": "model-4",
                "dataset_id": "dataset-4",
                "current_data_path": "current.csv",
                "baseline_data_path": "baseline.csv",
                "categorical_columns": ["category"],
                "numerical_columns": ["amount"],
            }
        )
    assert isinstance(result["psi_scores"], dict)
    assert isinstance(result["drift_detected"], bool)


async def test_transform_agent() -> None:
    """Verify TransformAgent creates a transformed dataset and lineage."""

    await reset_database()
    storage = MemoryStorage()
    await storage.write(
        "orders.csv",
        pd.DataFrame({"category": ["a", "a", "b"], "amount": [10, 5, 7]}).to_csv(index=False).encode(),
    )
    async with AsyncSessionLocal() as session:
        _, _, source_dataset = await seed_project_dataset(session)
        result = await TransformAgent("transform", MockLLM(), session, storage).execute(
            {
                "source_dataset_id": source_dataset.id,
                "source_data_path": "orders.csv",
                "transformation_request": "groupby category and sum amount",
                "join_datasets": [],
                "output_name": "orders_by_category",
            }
        )
        lineage = (await session.execute(select(Lineage))).scalars().all()
    assert result["output_dataset_id"]
    assert lineage
    assert await storage.exists(result["output_path"])


async def run_check(name: str, check: Check) -> bool:
    """Run a check and print a PASS/FAIL line."""

    try:
        await check()
        print(f"{name}: PASS")
        return True
    except Exception as exc:
        print(f"{name}: FAIL ({exc})")
        return False


async def main() -> int:
    """Run all M2 verification checks and return a process exit code."""

    db_path = VERIFY_ROOT / "verify_m2.db"
    storage_path = VERIFY_ROOT / "verify_data"
    if db_path.exists():
        db_path.unlink()
    if storage_path.exists():
        shutil.rmtree(storage_path)
    VERIFY_ROOT.mkdir(parents=True, exist_ok=True)
    print("=== AEGIS AI M2 VERIFICATION ===")
    checks: list[tuple[str, Check]] = [
        ("Config", test_config_loading),
        ("Database", test_create_all_tables),
        ("Repository", test_repository_crud),
        ("Storage", test_storage_adapter),
        ("LLM", test_llm_client_initialization),
        ("API", test_fastapi_health_endpoint),
        ("M1 Agents", test_m1_agents_placeholder),
        ("ExplainAgent", test_explain_agent),
        ("DeployAgent", test_deploy_agent),
        ("MonitorAgent", test_monitor_agent),
        ("DriftAgent", test_drift_agent),
        ("TransformAgent", test_transform_agent),
    ]
    results = [await run_check(name, check) for name, check in checks]
    failed = len(results) - sum(1 for result in results if result)
    if failed == 0:
        print("ALL M2 CHECKS PASSED")
    await async_engine.dispose()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
