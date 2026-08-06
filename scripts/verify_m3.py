#!/usr/bin/env python
"""Verify Aegis AI Milestone 3 intelligence layer."""

import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

ROOT = Path(__file__).resolve().parents[1]
VERIFY_ROOT = Path(tempfile.gettempdir()) / "aegis_ai_m3_verify"
VERIFY_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
os.environ["AEGIS_DB_URL"] = f"sqlite+aiosqlite:///{(VERIFY_ROOT / 'verify_m3.db').as_posix()}"
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
from src.agents.rag import AsyncVectorStore, RAGKnowledgeAgent, VECTOR_SIZE  # noqa: E402
from src.agents.transform import TransformAgent  # noqa: E402
from src.api.main import app  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.database.base import Base  # noqa: E402
from src.database.models import (  # noqa: E402
    AgentType,
    AuditLog,
    Dataset,
    Document,
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
    PipelineRepository,
    ProjectRepository,
    TaskRepository,
    UserRepository,
)
from src.database.session import AsyncSessionLocal, async_engine  # noqa: E402
from src.llm.client import LLMClient  # noqa: E402
from src.orchestrator.langgraph import PipelineState, build_pipeline_graph, create_checkpoint  # noqa: E402
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
    """Deterministic LLM and embedding stand-in."""

    async def embed(self, text: str, model: str | None = None) -> list[float]:
        seed = sum(ord(char) for char in text) or 1
        return [((seed + index) % 97) / 97.0 for index in range(VECTOR_SIZE)]

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
                    "recommendation": "Retrain with recent data.",
                }
            )
        if "code, explanation, output_columns" in prompt:
            return json.dumps(
                {
                    "code": "result = df.groupby('category', as_index=False)['amount'].sum()",
                    "explanation": "Grouped category spend.",
                    "output_columns": ["category", "amount"],
                }
            )
        if expect_json:
            return json.dumps(
                {
                    "summary": "Amount is the strongest feature.",
                    "top_features": [{"name": "amount", "importance": 0.7, "direction": "positive"}],
                    "business_insight": "Higher amounts lift the score.",
                }
            )
        return "The knowledge base contains schema information for orders."

    async def close(self) -> None:
        pass


class SimpleModel:
    """Tiny model fixture with a predict method."""

    def predict(self, frame: pd.DataFrame) -> list[int]:
        return [1 for _ in range(len(frame))]


async def reset_database() -> None:
    """Recreate all verifier tables."""

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def seed_project_dataset(name: str = "orders", quality_score: float | None = 0.82) -> tuple[User, Project, Dataset]:
    """Create a minimal owner, project, and dataset graph."""

    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).create(
            User(email=f"{name}@example.com", hashed_password="hashed", full_name="Owner", role=UserRole.ADMIN)
        )
        project = await ProjectRepository(session).create(Project(name=f"{name}-project", owner_id=user.id, config={}))
        dataset = await DatasetRepository(session).create(
            Dataset(project_id=project.id, name=name, source_type="csv", bronze_path=f"{name}.csv", quality_score=quality_score)
        )
        return user, project, dataset


async def test_config_loading() -> None:
    """Verify settings load expected M3 values."""

    settings = get_settings()
    assert settings.is_sqlite
    assert settings.AEGIS_QDRANT_COLLECTION == "aegis-knowledge"
    assert settings.AEGIS_EMBEDDING_MODEL == "nomic-embed-text"


async def test_create_all_tables() -> None:
    """Verify metadata can create the schema."""

    await reset_database()
    assert "documents" in Base.metadata.tables
    assert "pipelines" in Base.metadata.tables


async def test_repository_crud() -> None:
    """Verify core repository helpers still work."""

    await reset_database()
    user, project, dataset = await seed_project_dataset("repo_orders")
    async with AsyncSessionLocal() as session:
        pipeline = await PipelineRepository(session).create(
            Pipeline(project_id=project.id, dataset_id=dataset.id, name="repo-pipeline", status=PipelineStatus.RUNNING)
        )
        job = await JobRepository(session).create(Job(pipeline_id=pipeline.id, agent_type=AgentType.INGESTION, status=TaskStatus.RUNNING))
        task = await TaskRepository(session).create(Task(job_id=job.id, agent_type=AgentType.INGESTION, status=TaskStatus.PENDING))
        assert (await UserRepository(session).get_by_email(user.email)).id == user.id
        assert (await TaskRepository(session).update(task.id, {"status": TaskStatus.COMPLETED})) is not None


async def test_storage_adapter() -> None:
    """Verify configured storage adapter."""

    storage = get_storage()
    await storage.write("m3/sample.txt", b"aegis", "text/plain")
    assert await storage.read("m3/sample.txt") == b"aegis"
    assert await storage.delete("m3/sample.txt")


async def test_llm_client_initialization() -> None:
    """Verify the LLM client exposes generation and embedding configuration."""

    client = LLMClient()
    assert client.settings.AEGIS_LLM_MODEL
    assert client.settings.AEGIS_EMBEDDING_MODEL
    await client.close()


async def test_api() -> None:
    """Verify mounted API routers respond."""

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/health")
        agents = await client.get("/agents/")
        approvals = await client.get("/approvals/pending")
        history = await client.get("/chat/history")
    assert health.status_code == 200
    assert agents.status_code == 200
    assert approvals.status_code == 200
    assert history.status_code == 200


async def test_m1_agents() -> None:
    """Verify the agent package import surface remains present."""

    import src.agents  # noqa: F401


async def test_m2_agents() -> None:
    """Smoke-test M2 agent classes."""

    await reset_database()
    storage = MemoryStorage()
    sample = pd.DataFrame({"amount": [1, 2, 3], "age": [20, 30, 40]})
    import pickle

    await storage.write("model.pkl", pickle.dumps(SimpleModel()))
    await storage.write("sample.csv", sample.to_csv(index=False).encode())
    await storage.write("baseline.csv", pd.DataFrame({"amount": [1, 2, 3], "category": ["a", "a", "b"]}).to_csv(index=False).encode())
    await storage.write("current.csv", pd.DataFrame({"amount": [9, 10, 11], "category": ["b", "b", "b"]}).to_csv(index=False).encode())
    await storage.write("orders.csv", pd.DataFrame({"category": ["a", "a", "b"], "amount": [2, 3, 4]}).to_csv(index=False).encode())
    _, project, dataset = await seed_project_dataset("m2_orders")
    async with AsyncSessionLocal() as session:
        explain = await ExplainAgent("explain", MockLLM(), session, storage).execute(
            {"model_id": "m", "dataset_id": dataset.id, "model_artifact_path": "model.pkl", "sample_data_path": "sample.csv"}
        )
        deploy = await DeployAgent("deploy", MockLLM(), session, storage).execute(
            {
                "model_id": "m",
                "model_artifact_path": "model.pkl",
                "encoder_artifacts": {},
                "feature_columns": ["amount"],
                "target_column": "target",
                "model_type": "classification",
            }
        )
        drift = await DriftAgent("drift", MockLLM(), session, storage).execute(
            {
                "model_id": "m",
                "dataset_id": dataset.id,
                "current_data_path": "current.csv",
                "baseline_data_path": "baseline.csv",
                "categorical_columns": ["category"],
                "numerical_columns": ["amount"],
            }
        )
        transform = await TransformAgent("transform", MockLLM(), session, storage).execute(
            {
                "source_dataset_id": dataset.id,
                "source_data_path": "orders.csv",
                "transformation_request": "groupby category and sum amount",
                "join_datasets": [],
                "output_name": "m2_orders_out",
            }
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "healthy"} if request.url.path == "/health" else {"prediction": 1})

        monitor = await MonitorAgent("monitor", MockLLM(), session, storage).execute(
            {"deployment_id": None, "model_id": "m", "endpoint_url": "http://m.test", "_transport": httpx.MockTransport(handler)}
        )
    assert explain["top_features"]
    assert deploy["feature_count"] == 1
    assert isinstance(drift["drift_detected"], bool)
    assert transform["output_dataset_id"]
    assert monitor["is_healthy"] is True


async def test_langgraph() -> None:
    """Verify pipeline graph topology and state transitions."""

    graph = build_pipeline_graph()
    expected = {"ingest", "schema", "quality_gate", "clean", "features", "ml", "explain", "deploy", "monitor", "human_approval", "error_handler"}
    assert expected.issubset(set(graph.nodes))
    assert ("START", "ingest") in graph.edges
    assert "human_approval" in graph.checkpoint_nodes
    state: PipelineState = {
        "pipeline_id": "pipeline-graph",
        "project_id": "project",
        "dataset_id": "dataset",
        "current_step": "",
        "completed_steps": [],
        "artifacts": {},
        "quality_score": 0.9,
        "human_decisions": {},
        "retry_count": 0,
        "risk_level": "low",
        "needs_transform": False,
    }
    result = await graph.ainvoke(state)
    assert result["completed_steps"] == ["ingest", "schema", "clean", "features", "ml", "explain", "deploy", "monitor"]


async def test_rag_agent() -> None:
    """Verify RAG ingest and query across vector store and database."""

    await reset_database()
    async with AsyncSessionLocal() as session:
        agent = RAGKnowledgeAgent("rag", MockLLM(), session, MemoryStorage())
        ingest = await agent.execute(
            {
                "action": "ingest",
                "doc_type": "schema",
                "title": "orders schema",
                "content": "orders has columns id, amount, category",
                "metadata": {"dataset": "orders"},
            }
        )
        query = await agent.execute({"action": "query", "question": "What schemas do we have?"})
        documents = (await session.execute(select(Document))).scalars().all()
    assert ingest["embedding_dimension"] == VECTOR_SIZE
    assert documents
    assert query["answer"]
    assert isinstance(query["sources"], list)


async def test_approval_api() -> None:
    """Verify pending, approve, and reject flows update real pipelines."""

    await reset_database()
    _, project, dataset = await seed_project_dataset("approval_orders")
    async with AsyncSessionLocal() as session:
        approve_pipeline = await PipelineRepository(session).create(
            Pipeline(
                project_id=project.id,
                dataset_id=dataset.id,
                name="approve-me",
                status=PipelineStatus.APPROVAL_REQUIRED,
                current_state="human_approval",
                checkpoint_data={"pipeline_id": "", "current_step": "human_approval", "completed_steps": []},
            )
        )
        approve_pipeline.checkpoint_data["pipeline_id"] = approve_pipeline.id
        await PipelineRepository(session).update(approve_pipeline.id, {"checkpoint_data": approve_pipeline.checkpoint_data})
        reject_pipeline = await PipelineRepository(session).create(
            Pipeline(
                project_id=project.id,
                dataset_id=dataset.id,
                name="reject-me",
                status=PipelineStatus.APPROVAL_REQUIRED,
                current_state="human_approval",
                checkpoint_data={"pipeline_id": "", "current_step": "human_approval", "completed_steps": []},
            )
        )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        pending = await client.get("/approvals/pending")
        approved = await client.post(
            f"/approvals/{approve_pipeline.id}/approve",
            json={"decision": "approve", "rationale": "Looks safe"},
        )
        rejected = await client.post(
            f"/approvals/{reject_pipeline.id}/reject",
            json={"decision": "reject", "rationale": "Risk too high"},
        )
    async with AsyncSessionLocal() as session:
        refreshed = await PipelineRepository(session).get_by_id(approve_pipeline.id)
        failed = await PipelineRepository(session).get_by_id(reject_pipeline.id)
        audits = (await session.execute(select(AuditLog).where(AuditLog.action == "HUMAN_DECISION"))).scalars().all()
    assert pending.status_code == 200
    assert any(item["pipeline_id"] == approve_pipeline.id for item in pending.json()["pipelines"])
    assert approved.status_code == 200
    assert rejected.status_code == 200
    assert refreshed.status == PipelineStatus.RUNNING
    assert failed.status == PipelineStatus.FAILED
    assert audits


async def test_chat_api() -> None:
    """Verify chat answers direct database questions."""

    await reset_database()
    await seed_project_dataset("dataset_x", quality_score=0.73)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/chat/ask", json={"question": "What is the quality score of dataset dataset_x?"})
    payload = response.json()
    assert response.status_code == 200
    assert "answer" in payload
    assert "sources" in payload
    assert payload["confidence"] > 0


async def test_qdrant_service() -> None:
    """Verify async vector collection setup and search behavior."""

    store = AsyncVectorStore(get_settings().AEGIS_QDRANT_COLLECTION)
    await store.ensure_collection()
    assert await store.collection_exists()
    vector = [0.1] * VECTOR_SIZE
    await store.upsert("qdrant-test", vector, {"document_id": "qdrant-test", "doc_type": "manual", "title": "test"})
    results = await store.search(vector, limit=1)
    assert results
    assert results[0]["payload"]["document_id"] == "qdrant-test"


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
    """Run all M3 verification checks."""

    db_path = VERIFY_ROOT / "verify_m3.db"
    storage_path = VERIFY_ROOT / "verify_data"
    if db_path.exists():
        db_path.unlink()
    if storage_path.exists():
        shutil.rmtree(storage_path)
    VERIFY_ROOT.mkdir(parents=True, exist_ok=True)
    print("=== AEGIS AI M3 VERIFICATION ===")
    checks: list[tuple[str, Check]] = [
        ("Config", test_config_loading),
        ("Database", test_create_all_tables),
        ("Repository", test_repository_crud),
        ("Storage", test_storage_adapter),
        ("LLM", test_llm_client_initialization),
        ("API", test_api),
        ("M1 Agents", test_m1_agents),
        ("M2 Agents", test_m2_agents),
        ("LangGraph", test_langgraph),
        ("RAG Agent", test_rag_agent),
        ("Approval API", test_approval_api),
        ("Chat API", test_chat_api),
        ("Qdrant", test_qdrant_service),
    ]
    results = [await run_check(name, check) for name, check in checks]
    failed = len(results) - sum(1 for result in results if result)
    if failed == 0:
        print("ALL M3 CHECKS PASSED")
    await async_engine.dispose()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
