#!/usr/bin/env python
"""Verify Aegis AI Milestone 4 security and governance."""

import asyncio
import json
import os
import pickle
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

ROOT = Path(__file__).resolve().parents[1]
VERIFY_ROOT = Path(tempfile.gettempdir()) / "aegis_ai_m4_verify"
VERIFY_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
os.environ["AEGIS_DB_URL"] = f"sqlite+aiosqlite:///{(VERIFY_ROOT / 'verify_m4.db').as_posix()}"
os.environ["AEGIS_STORAGE_BACKEND"] = "local"
os.environ["AEGIS_LOCAL_STORAGE_PATH"] = str(VERIFY_ROOT / "verify_data")
os.environ["AEGIS_DEBUG"] = "false"

import httpx  # noqa: E402
import pandas as pd  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from src.agents.pii import PIIDetectionAgent  # noqa: E402
from src.agents.rag import AsyncVectorStore, RAGKnowledgeAgent, VECTOR_SIZE  # noqa: E402
from src.api.main import app  # noqa: E402
from src.config import get_settings  # noqa: E402
from src.core.policies import RetentionPolicy  # noqa: E402
from src.core.security import verify_password  # noqa: E402
from src.database.base import Base  # noqa: E402
from src.database.models import (  # noqa: E402
    Alert,
    AuditLog,
    Dataset,
    Lineage,
    Pipeline,
    PipelineStatus,
    Project,
    User,
    UserRole,
)
from src.database.repository import AuditLogRepository, DatasetRepository, LineageRepository, PipelineRepository, ProjectRepository, UserRepository  # noqa: E402
from src.database.session import AsyncSessionLocal, async_engine  # noqa: E402
from src.llm.client import LLMClient  # noqa: E402
from src.orchestrator.langgraph import PipelineState, build_pipeline_graph  # noqa: E402
from src.storage import get_storage  # noqa: E402
from src.storage.base import StorageAdapter  # noqa: E402

Check = Callable[[], Awaitable[None]]


class MemoryStorage(StorageAdapter):
    """Small async storage adapter for verifier fixtures."""

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
        return [((seed + index) % 101) / 101.0 for index in range(VECTOR_SIZE)]

    async def generate(self, prompt: str, expect_json: bool = False, **kwargs: Any) -> str:
        if "masking strategy" in prompt:
            return json.dumps({"strategy": "redact"})
        if expect_json:
            return json.dumps({"pii_type": "unknown", "confidence": 0.0})
        return "Aegis knowledge answer."


class SimpleModel:
    """Pickle-friendly model fixture."""

    def predict(self, frame: pd.DataFrame) -> list[int]:
        return [1 for _ in range(len(frame))]


async def reset_database() -> None:
    """Recreate all verifier tables."""

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def seed_user(email: str, role: UserRole) -> tuple[User, str]:
    """Register and log in a user through the API."""

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        password = "SecurePass123"
        register = await client.post(
            "/auth/register",
            json={"email": email, "password": password, "full_name": email.split("@")[0], "role": role.value},
        )
        assert register.status_code in {201, 409}, register.text
        login = await client.post("/auth/login", data={"username": email, "password": password})
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]
    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).get_by_email(email)
        assert user is not None
        assert verify_password(password, user.hashed_password)
        return user, token


async def seed_project_dataset(name: str = "orders", quality_score: float | None = 0.82) -> tuple[User, Project, Dataset]:
    """Create project and dataset records."""

    async with AsyncSessionLocal() as session:
        user = await UserRepository(session).create(
            User(email=f"{name}@example.com", hashed_password="x", role=UserRole.ADMIN, full_name="Owner")
        )
        project = await ProjectRepository(session).create(Project(name=f"{name}-project", owner_id=user.id, config={}))
        dataset = await DatasetRepository(session).create(
            Dataset(project_id=project.id, name=name, source_type="csv", bronze_path=f"{name}.csv", quality_score=quality_score)
        )
        return user, project, dataset


async def test_config_loading() -> None:
    """Verify security settings are present."""

    settings = get_settings()
    assert settings.AEGIS_SECRET_KEY
    assert settings.AEGIS_ACCESS_TOKEN_EXPIRE_MINUTES == 60


async def test_create_all_tables() -> None:
    """Verify database metadata."""

    await reset_database()
    assert {"users", "audit_logs", "lineage", "alerts"}.issubset(Base.metadata.tables)


async def test_repository_crud() -> None:
    """Verify repositories still work."""

    await reset_database()
    _, project, dataset = await seed_project_dataset("repo_m4")
    async with AsyncSessionLocal() as session:
        pipeline = await PipelineRepository(session).create(
            Pipeline(project_id=project.id, dataset_id=dataset.id, name="p", status=PipelineStatus.RUNNING)
        )
        assert pipeline.id
        assert len(await PipelineRepository(session).list_by_project(project.id)) == 1


async def test_storage_adapter() -> None:
    """Verify storage still works."""

    storage = get_storage()
    await storage.write("m4/sample.txt", b"aegis", "text/plain")
    assert await storage.read("m4/sample.txt") == b"aegis"


async def test_llm_client_initialization() -> None:
    """Verify LLM client settings."""

    client = LLMClient()
    assert client.settings.AEGIS_EMBEDDING_MODEL
    await client.close()


async def test_api() -> None:
    """Verify public health and protected auth behavior."""

    await reset_database()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/health")
        protected = await client.get("/agents/")
    assert health.status_code == 200
    assert protected.status_code == 401


async def test_m1_agents() -> None:
    """Verify agent package import surface."""

    import src.agents  # noqa: F401


async def test_m2_agents() -> None:
    """Verify M2 and PII agents are importable."""

    from src.agents.deploy import DeployAgent  # noqa: F401
    from src.agents.drift import DriftAgent  # noqa: F401
    from src.agents.explain import ExplainAgent  # noqa: F401
    from src.agents.monitor import MonitorAgent  # noqa: F401
    from src.agents.transform import TransformAgent  # noqa: F401


async def test_langgraph() -> None:
    """Verify graph execution."""

    graph = build_pipeline_graph()
    state: PipelineState = {
        "pipeline_id": "m4-graph",
        "project_id": "p",
        "dataset_id": "d",
        "current_step": "",
        "completed_steps": [],
        "artifacts": {},
        "quality_score": 0.95,
        "human_decisions": {},
        "retry_count": 0,
        "risk_level": "low",
        "needs_transform": False,
    }
    result = await graph.ainvoke(state)
    assert "monitor" in result["completed_steps"]


async def test_rag_agent() -> None:
    """Verify RAG ingest/query."""

    await reset_database()
    async with AsyncSessionLocal() as session:
        agent = RAGKnowledgeAgent("rag", MockLLM(), session, MemoryStorage())
        ingest = await agent.execute({"action": "ingest", "doc_type": "schema", "content": "orders schema", "metadata": {}})
        query = await agent.execute({"action": "query", "question": "What schemas do we have?"})
    assert ingest["embedding_dimension"] == VECTOR_SIZE
    assert query["answer"]


async def test_approval_api() -> None:
    """Verify approval endpoint with auth."""

    await reset_database()
    admin, token = await seed_user("approval-admin@example.com", UserRole.ADMIN)
    _, project, dataset = await seed_project_dataset("approval_m4")
    async with AsyncSessionLocal() as session:
        pipeline = await PipelineRepository(session).create(
            Pipeline(
                project_id=project.id,
                dataset_id=dataset.id,
                name="approval",
                status=PipelineStatus.APPROVAL_REQUIRED,
                current_state="human_approval",
                checkpoint_data={"pipeline_id": "", "current_step": "human_approval", "completed_steps": []},
            )
        )
        await PipelineRepository(session).update(pipeline.id, {"checkpoint_data": {"pipeline_id": pipeline.id, "current_step": "human_approval"}})
    headers = {"Authorization": f"Bearer {token}"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        pending = await client.get("/approvals/pending", headers=headers)
        approved = await client.post(f"/approvals/{pipeline.id}/approve", headers=headers, json={"decision": "approve", "rationale": "ok"})
    assert pending.status_code == 200
    assert approved.status_code == 200


async def test_chat_api() -> None:
    """Verify authenticated chat."""

    await reset_database()
    _, token = await seed_user("chat-viewer@example.com", UserRole.VIEWER)
    await seed_project_dataset("dataset_x", quality_score=0.77)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/ask",
            headers={"Authorization": f"Bearer {token}"},
            json={"question": "What is the quality score of dataset dataset_x?"},
        )
    assert response.status_code == 200
    assert "quality score" in response.json()["answer"].lower()


async def test_qdrant_service() -> None:
    """Verify vector collection behavior."""

    store = AsyncVectorStore(get_settings().AEGIS_QDRANT_COLLECTION)
    await store.ensure_collection()
    assert await store.collection_exists()
    vector = [0.2] * VECTOR_SIZE
    await store.upsert("m4-qdrant", vector, {"document_id": "m4-qdrant"})
    assert await store.search(vector, limit=1)


async def test_auth() -> None:
    """Verify registration, login, token profile, and auth failures."""

    await reset_database()
    viewer, viewer_token = await seed_user("viewer@example.com", UserRole.VIEWER)
    assert viewer.role == UserRole.VIEWER
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        me = await client.get("/auth/me", headers={"Authorization": f"Bearer {viewer_token}"})
        no_token = await client.get("/agents/")
        admin_denied = await client.get("/admin/users", headers={"Authorization": f"Bearer {viewer_token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "viewer@example.com"
    assert no_token.status_code == 401
    assert no_token.json()["code"] == "UNAUTHORIZED"
    assert admin_denied.status_code == 403
    assert admin_denied.json()["code"] == "FORBIDDEN"


async def test_rbac() -> None:
    """Verify role-based access across key endpoints."""

    await reset_database()
    admin, admin_token = await seed_user("admin@example.com", UserRole.ADMIN)
    _, engineer_token = await seed_user("engineer@example.com", UserRole.DATA_ENGINEER)
    _, analyst_token = await seed_user("analyst@example.com", UserRole.ANALYST)
    _, viewer_token = await seed_user("viewer2@example.com", UserRole.VIEWER)
    storage = get_storage()
    await storage.write(
        "m4/pii.csv",
        pd.DataFrame({"email": ["a@example.com"], "phone": ["555-123-4567"], "name": ["Ada Lovelace"]}).to_csv(index=False).encode(),
        "text/csv",
    )
    _, project, dataset = await seed_project_dataset("rbac_orders")
    async with AsyncSessionLocal() as session:
        pipeline = await PipelineRepository(session).create(
            Pipeline(project_id=project.id, dataset_id=dataset.id, name="rbac", status=PipelineStatus.APPROVAL_REQUIRED)
        )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        viewer_execute = await client.post(
            "/agents/pii/execute",
            headers={"Authorization": f"Bearer {viewer_token}"},
            json={"dataset_id": dataset.id, "data_sample_path": "m4/pii.csv"},
        )
        analyst_chat = await client.post(
            "/chat/ask",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={"question": "What is the quality score of dataset rbac_orders?"},
        )
        analyst_approve = await client.post(
            f"/approvals/{pipeline.id}/approve",
            headers={"Authorization": f"Bearer {analyst_token}"},
            json={"decision": "approve", "rationale": "ok"},
        )
        engineer_execute = await client.post(
            "/agents/pii/execute",
            headers={"Authorization": f"Bearer {engineer_token}"},
            json={"dataset_id": dataset.id, "data_sample_path": "m4/pii.csv"},
        )
        admin_users = await client.get("/admin/users", headers={"Authorization": f"Bearer {admin_token}"})
    assert viewer_execute.status_code == 403
    assert analyst_chat.status_code == 200
    assert analyst_approve.status_code == 403
    assert engineer_execute.status_code == 200
    assert admin_users.status_code == 200
    assert admin.id


async def test_pii_detection() -> None:
    """Verify PII detection report and alert creation."""

    await reset_database()
    storage = MemoryStorage()
    csv = pd.DataFrame(
        {
            "id": [1, 2],
            "email": ["ada@example.com", "grace@example.com"],
            "phone": ["555-111-2222", "555-333-4444"],
            "name": ["Ada Lovelace", "Grace Hopper"],
            "purchase_amount": [10.5, 20.0],
        }
    )
    await storage.write("sample.csv", csv.to_csv(index=False).encode())
    async with AsyncSessionLocal() as session:
        result = await PIIDetectionAgent("pii", MockLLM(), session, storage).execute(
            {"dataset_id": "dataset-pii", "data_sample_path": "sample.csv"}
        )
        alerts = (await session.execute(select(Alert))).scalars().all()
    report = json.loads((await storage.read(result["report_path"])).decode())
    flagged = {column["name"] for column in report["columns"]}
    assert {"email", "phone", "name"}.issubset(flagged)
    assert result["pii_detected"] is True
    assert alerts


async def test_lineage_graph() -> None:
    """Verify recursive lineage graph and impact APIs."""

    await reset_database()
    _, token = await seed_user("lineage-admin@example.com", UserRole.ADMIN)
    _, project, dataset_a = await seed_project_dataset("dataset_a")
    async with AsyncSessionLocal() as session:
        dataset_b = await DatasetRepository(session).create(Dataset(project_id=project.id, name="dataset_b", source_type="transformed", silver_path="b.csv"))
        dataset_c = await DatasetRepository(session).create(Dataset(project_id=project.id, name="dataset_c", source_type="transformed", gold_path="c.csv"))
        await LineageRepository(session).create(Lineage(source_dataset_id=dataset_a.id, target_dataset_id=dataset_b.id, transformation_type="clean", agent_id="clean"))
        await LineageRepository(session).create(Lineage(source_dataset_id=dataset_b.id, target_dataset_id=dataset_c.id, transformation_type="aggregate", agent_id="transform"))
    headers = {"Authorization": f"Bearer {token}"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        graph = await client.get(f"/lineage/datasets/{dataset_c.id}", headers=headers)
        impact = await client.get(f"/lineage/impact/{dataset_a.id}", headers=headers)
    upstream = graph.json()["upstream"]
    affected = impact.json()["affected_datasets"]
    assert graph.status_code == 200
    assert {row["dataset_id"] for row in upstream} == {dataset_a.id, dataset_b.id}
    assert {row["id"] for row in affected} == {dataset_b.id, dataset_c.id}


async def test_audit_logging() -> None:
    """Verify key user actions create complete audit logs."""

    await reset_database()
    user, token = await seed_user("audit-admin@example.com", UserRole.ADMIN)
    storage = get_storage()
    await storage.write("m4/audit-pii.csv", pd.DataFrame({"email": ["audit@example.com"]}).to_csv(index=False).encode(), "text/csv")
    _, project, dataset = await seed_project_dataset("audit_dataset")
    async with AsyncSessionLocal() as session:
        await AuditLogRepository(session).log_action(
            action="DATASET_CREATED",
            resource_type="dataset",
            resource_id=dataset.id,
            user_id=user.id,
            before_json={},
            after_json={"name": dataset.name},
            rationale="Verifier dataset creation",
            confidence=1.0,
        )
        pipeline = await PipelineRepository(session).create(
            Pipeline(project_id=project.id, dataset_id=dataset.id, name="audit", status=PipelineStatus.APPROVAL_REQUIRED)
        )
    headers = {"Authorization": f"Bearer {token}"}
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/auth/login", data={"username": user.email, "password": "SecurePass123"})
        await client.post("/agents/pii/execute", headers=headers, json={"dataset_id": dataset.id, "data_sample_path": "m4/audit-pii.csv"})
        await client.post(f"/approvals/{pipeline.id}/approve", headers=headers, json={"decision": "approve", "rationale": "audit ok"})
    async with AsyncSessionLocal() as session:
        logs = (
            await session.execute(
                select(AuditLog).where(
                    AuditLog.action.in_(["USER_LOGIN", "PII_SCAN_COMPLETE", "HUMAN_DECISION", "DATASET_CREATED"])
                )
            )
        ).scalars().all()
    actions = {log.action for log in logs}
    assert {"USER_LOGIN", "PII_SCAN_COMPLETE", "HUMAN_DECISION", "DATASET_CREATED"}.issubset(actions)
    assert all(log.user_id and log.action and log.resource_type and log.resource_id and log.created_at for log in logs)
    assert all(log.before_json is not None and log.after_json is not None for log in logs)


async def test_data_retention() -> None:
    """Verify retention policy soft-deletes old datasets and logs the action."""

    await reset_database()
    _, project, dataset = await seed_project_dataset("retention_dataset")
    async with AsyncSessionLocal() as session:
        loaded = await DatasetRepository(session).get_by_id(dataset.id)
        loaded.silver_path = "silver/old.csv"
        loaded.created_at = datetime.utcnow() - timedelta(days=100)
        await session.commit()
        result = await RetentionPolicy(session=session, project_id=project.id, silver_days=30).enforce()
        refreshed = await DatasetRepository(session).get_by_id(dataset.id)
        logs = (await session.execute(select(AuditLog).where(AuditLog.action == "DATASET_RETENTION_ARCHIVED"))).scalars().all()
    assert dataset.id in result["archived_datasets"]
    assert refreshed.is_deleted is True
    assert logs


async def run_check(name: str, check: Check) -> bool:
    """Run one check and print a PASS/FAIL line."""

    try:
        await check()
        print(f"{name}: PASS")
        return True
    except Exception as exc:
        print(f"{name}: FAIL ({exc})")
        return False


async def main() -> int:
    """Run all M4 verification checks."""

    db_path = VERIFY_ROOT / "verify_m4.db"
    storage_path = VERIFY_ROOT / "verify_data"
    if db_path.exists():
        db_path.unlink()
    if storage_path.exists():
        shutil.rmtree(storage_path)
    VERIFY_ROOT.mkdir(parents=True, exist_ok=True)
    print("=== AEGIS AI M4 VERIFICATION ===")
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
        ("Auth", test_auth),
        ("RBAC", test_rbac),
        ("PII Detection", test_pii_detection),
        ("Lineage Graph", test_lineage_graph),
        ("Audit Logging", test_audit_logging),
        ("Data Retention", test_data_retention),
    ]
    results = [await run_check(name, check) for name, check in checks]
    failed = len(results) - sum(1 for result in results if result)
    if failed == 0:
        print("ALL M4 CHECKS PASSED")
    await async_engine.dispose()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
