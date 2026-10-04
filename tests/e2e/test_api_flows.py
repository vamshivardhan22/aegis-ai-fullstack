"""End-to-end API flow tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.database.models import AuditLog, Dataset, Pipeline, PipelineStatus, Project
from src.database.session import AsyncSessionLocal


async def _token(client: AsyncClient, role: str = "data_engineer") -> str:
    """Register and log in a test user."""

    email = f"{role}@e2e.local"
    password = "SecurePass123"
    await client.post("/auth/register", json={"email": email, "password": password, "role": role})
    response = await client.post("/auth/login", data={"username": email, "password": password})
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_complete_pipeline_flow(client: AsyncClient) -> None:
    """Exercise register, upload, agent execution, lineage, chat, and monitoring surfaces."""

    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}
    csv_content = "id,email,amount\n1,test@example.com,10\n2,user@example.com,20\n"
    dataset = await client.post(
        "/datasets/",
        headers=headers,
        json={"name": "e2e_orders", "content": csv_content, "source_type": "csv"},
    )
    assert dataset.status_code == 200
    dataset_id = dataset.json()["id"]
    ingestion = await client.post(
        "/agents/ingestion/execute",
        headers=headers,
        json={"dataset_id": dataset_id, "artifact": dataset.json()["bronze_path"]},
    )
    assert ingestion.status_code == 200
    ml = await client.post("/agents/ml/execute", headers=headers, json={"dataset_id": dataset_id})
    assert ml.status_code == 200
    pii = await client.post(
        "/agents/pii/execute",
        headers=headers,
        json={"dataset_id": dataset_id, "data_sample_path": dataset.json()["bronze_path"]},
    )
    assert pii.status_code == 200
    lineage = await client.get(f"/lineage/datasets/{dataset_id}", headers=headers)
    assert lineage.status_code == 200
    chat = await client.post("/chat/ask", headers=headers, json={"question": "What datasets are available?"})
    assert chat.status_code == 200
    profile = await client.get("/auth/me", headers=headers)
    assert profile.status_code == 200


@pytest.mark.asyncio
async def test_approval_resumes_pipeline_to_completion(client: AsyncClient) -> None:
    """Approving a checkpointed pipeline resumes it to a terminal completed state."""

    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}
    profile = await client.get("/auth/me", headers=headers)
    user_id = profile.json()["id"]

    async with AsyncSessionLocal() as session:
        project = Project(name="approval_project", description="Approval flow", owner_id=user_id, config={})
        session.add(project)
        await session.flush()
        dataset = Dataset(project_id=project.id, name="approval_dataset", source_type="csv", row_count=2, column_count=2)
        session.add(dataset)
        await session.flush()
        pipeline = Pipeline(
            project_id=project.id,
            dataset_id=dataset.id,
            name="approval_pipeline",
            status=PipelineStatus.APPROVAL_REQUIRED,
            current_state="human_approval",
            checkpoint_data={
                "pipeline_id": "",
                "project_id": project.id,
                "dataset_id": dataset.id,
                "current_step": "human_approval",
                "completed_steps": ["ingest", "schema"],
                "artifacts": {},
                "quality_score": 0.92,
                "human_decisions": {},
                "needs_transform": False,
                "risk_level": "high",
                "paused": True,
            },
        )
        session.add(pipeline)
        await session.flush()
        pipeline.checkpoint_data["pipeline_id"] = pipeline.id
        pipeline_id = pipeline.id
        await session.commit()

    response = await client.post(
        f"/approvals/{pipeline_id}/approve",
        headers=headers,
        json={"decision": "approve", "rationale": "Approved by regression test.", "modifications": {}, "alternative_action": None},
    )
    assert response.status_code == 200

    async with AsyncSessionLocal() as session:
        pipeline = await session.get(Pipeline, pipeline_id)
        assert pipeline is not None
        assert pipeline.status == PipelineStatus.COMPLETED
        assert pipeline.current_state == "monitor"
        audit_result = await session.execute(select(AuditLog.action).where(AuditLog.resource_id == pipeline_id))
        actions = set(audit_result.scalars().all())
        assert {"HUMAN_DECISION", "PIPELINE_RESUMED_FINISHED"}.issubset(actions)
