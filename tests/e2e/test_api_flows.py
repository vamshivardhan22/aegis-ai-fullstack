"""End-to-end API flow tests."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from src.database.models import AuditLog, Dataset, Pipeline, PipelineStatus, Project
from src.database.session import AsyncSessionLocal
from src.storage import get_storage


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
    quality = await client.post("/agents/quality/execute", headers=headers, json={"dataset_id": dataset_id})
    assert quality.status_code == 200
    assert quality.json()["quality_score"] >= 0.9
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
    history = await client.get("/chat/history", headers=headers)
    assert history.status_code == 200
    assert any(item["question"] == "What datasets are available?" for item in history.json()["history"])
    profile = await client.get("/auth/me", headers=headers)
    assert profile.status_code == 200


@pytest.mark.asyncio
async def test_approval_resumes_pipeline_to_completion(client: AsyncClient) -> None:
    """A sensitive CSV run pauses, then publishes only after a scoped approval."""
    token = await _token(client)
    headers = {"Authorization": f"Bearer {token}"}
    profile = await client.get("/auth/me", headers=headers)
    user_id = profile.json()["id"]

    async with AsyncSessionLocal() as session:
        project = Project(name="approval_project", description="Approval flow", owner_id=user_id, config={})
        session.add(project)
        await session.flush()
        project_id = project.id
        dataset = Dataset(
            project_id=project.id,
            name="approval_dataset",
            source_type="csv",
            bronze_path=f"bronze/{project.id}/approval_dataset.csv",
            row_count=2,
            column_count=3,
        )
        session.add(dataset)
        await session.flush()
        dataset_id = dataset.id
        await session.commit()

    await get_storage().write(
        f"bronze/{project_id}/approval_dataset.csv",
        b"order_id,customer_email,amount\n1,one@example.com,10\n2,two@example.com,20\n",
        "text/csv",
    )
    started = await client.post("/pipelines/", headers=headers, json={"dataset_id": dataset_id})
    assert started.status_code == 200, started.text
    pipeline_id = started.json()["pipeline"]["id"]
    assert started.json()["pipeline"]["status"] == PipelineStatus.APPROVAL_REQUIRED.value

    response = await client.post(
        f"/approvals/{pipeline_id}/approve",
        headers=headers,
        json={"decision": "approve", "rationale": "Approved after PII masking."},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == PipelineStatus.COMPLETED.value

    async with AsyncSessionLocal() as session:
        pipeline = await session.get(Pipeline, pipeline_id)
        assert pipeline is not None
        assert pipeline.status == PipelineStatus.COMPLETED
        assert pipeline.current_state == "published"
        assert pipeline.checkpoint_data["pii_columns"]["customer_email"] == "email"
        assert pipeline.checkpoint_data["human_decisions"]["latest"]["decision"] == "approved"
        output = await session.get(Dataset, pipeline.checkpoint_data["output_dataset_id"])
        assert output is not None
        assert output.silver_path == pipeline.checkpoint_data["candidate_artifact"]
        assert output.row_count == 2
        actions_result = await session.execute(select(AuditLog.action).where(AuditLog.resource_id == pipeline_id))
        actions = set(actions_result.scalars().all())
        assert {"HUMAN_APPROVAL_GRANTED", "PIPELINE_PUBLISHED"}.issubset(actions)


@pytest.mark.asyncio
async def test_dataset_and_lineage_are_project_scoped(client: AsyncClient) -> None:
    """A user cannot fetch another user's dataset or lineage by guessing an ID."""
    engineer_token = await _token(client, role="data_engineer")
    analyst_token = await _token(client, role="analyst")
    engineer_headers = {"Authorization": f"Bearer {engineer_token}"}
    analyst_headers = {"Authorization": f"Bearer {analyst_token}"}
    created = await client.post(
        "/datasets/",
        headers=engineer_headers,
        json={"name": "private_orders", "content": "order_id,amount\n1,10\n", "source_type": "csv"},
    )
    assert created.status_code == 200, created.text
    dataset_id = created.json()["id"]
    chat = await client.post(
        "/chat/ask",
        headers=engineer_headers,
        json={"question": "What is the quality score for private_orders?"},
    )
    assert chat.status_code == 200
    analyst_history = await client.get("/chat/history", headers=analyst_headers)
    assert analyst_history.status_code == 200
    assert analyst_history.json()["history"] == []

    hidden_dataset = await client.get(f"/datasets/{dataset_id}", headers=analyst_headers)
    hidden_lineage = await client.get(f"/lineage/datasets/{dataset_id}", headers=analyst_headers)
    hidden_download = await client.get(f"/datasets/{dataset_id}/download?layer=bronze", headers=analyst_headers)
    analyst_datasets = await client.get("/datasets/", headers=analyst_headers)
    assert hidden_dataset.status_code == 404
    assert hidden_lineage.status_code == 404
    assert hidden_download.status_code == 404
    assert analyst_datasets.status_code == 200
    assert analyst_datasets.json()["datasets"] == []


@pytest.mark.asyncio
async def test_non_sensitive_csv_pipeline_publishes_output(client: AsyncClient) -> None:
    """A valid non-sensitive CSV runs through quality checks and creates a lineage-linked output."""
    token = await _token(client, role="data_engineer")
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        "/datasets/",
        headers=headers,
        json={"name": "clean_orders", "content": "order_id,amount\n1,10\n2,20\n", "source_type": "csv"},
    )
    assert created.status_code == 200, created.text
    dataset_id = created.json()["id"]

    started = await client.post("/pipelines/", headers=headers, json={"dataset_id": dataset_id})
    assert started.status_code == 200, started.text
    pipeline = started.json()["pipeline"]
    assert pipeline["status"] == PipelineStatus.COMPLETED.value
    output_id = started.json()["execution"]["output_dataset_id"]
    output = await client.get(f"/datasets/{output_id}", headers=headers)
    assert output.status_code == 200
    assert output.json()["silver_path"]
    download = await client.get(f"/datasets/{output_id}/download?layer=silver", headers=headers)
    assert download.status_code == 200
    assert "text/csv" in download.headers["content-type"]
    assert "order_id,amount" in download.text
    lineage = await client.get(f"/lineage/datasets/{dataset_id}", headers=headers)
    assert lineage.status_code == 200
    assert any(edge["target"] == output_id for edge in lineage.json()["edges"])


@pytest.mark.asyncio
async def test_ml_agent_trains_and_registers_a_model(client: AsyncClient) -> None:
    """The standalone ML agent must train and register a real evaluated model."""
    token = await _token(client, role="data_engineer")
    headers = {"Authorization": f"Bearer {token}"}
    rows = ["id,age,spend,segment"]
    for index in range(30):
        segment = "high" if index % 2 else "low"
        rows.append(f"{index},{20 + index},{100 + index * 7},{segment}")
    csv_content = "\n".join(rows) + "\n"
    created = await client.post(
        "/datasets/",
        headers=headers,
        json={"name": "ml_training_data", "content": csv_content, "source_type": "csv"},
    )
    assert created.status_code == 200, created.text

    trained = await client.post(
        "/agents/ml/execute",
        headers=headers,
        json={"dataset_id": created.json()["id"], "target_column": "segment", "task": "classification"},
    )
    assert trained.status_code == 200, trained.text
    result = trained.json()
    assert result["model_id"]
    assert result["algorithm"] == "RandomForestClassifier"
    assert 0 <= result["metrics"]["accuracy"] <= 1
    assert result["artifact_path"].endswith(".joblib")
    registry = await client.get("/models/", headers=headers)
    assert registry.status_code == 200
    assert any(model["id"] == result["model_id"] for model in registry.json()["models"])
    artifact = await client.get(f"/models/{result['model_id']}/download", headers=headers)
    assert artifact.status_code == 200
    assert len(artifact.content) > 100
    analyst_token = await _token(client, role="analyst")
    analyst_headers = {"Authorization": f"Bearer {analyst_token}"}
    hidden_model = await client.get(f"/models/{result['model_id']}", headers=analyst_headers)
    hidden_artifact = await client.get(f"/models/{result['model_id']}/download", headers=analyst_headers)
    assert hidden_model.status_code == 404
    assert hidden_artifact.status_code == 404


@pytest.mark.asyncio
async def test_rejected_pii_pipeline_never_publishes_output(client: AsyncClient) -> None:
    """Rejecting a sensitive-data checkpoint must leave the output unpublished."""
    token = await _token(client, role="data_engineer")
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        "/datasets/",
        headers=headers,
        json={"name": "rejected_orders", "content": "order_id,customer_email\n1,secret@example.com\n", "source_type": "csv"},
    )
    assert created.status_code == 200, created.text
    started = await client.post("/pipelines/", headers=headers, json={"dataset_id": created.json()["id"]})
    assert started.status_code == 200, started.text
    pipeline_id = started.json()["pipeline"]["id"]
    assert started.json()["pipeline"]["status"] == PipelineStatus.APPROVAL_REQUIRED.value

    rejected = await client.post(
        f"/approvals/{pipeline_id}/reject",
        headers=headers,
        json={"decision": "reject", "rationale": "Rejected for policy review."},
    )
    assert rejected.status_code == 200, rejected.text
    async with AsyncSessionLocal() as session:
        pipeline = await session.get(Pipeline, pipeline_id)
        assert pipeline is not None
        assert pipeline.status == PipelineStatus.FAILED
        assert pipeline.checkpoint_data["stage"] == "rejected"
        assert "output_dataset_id" not in pipeline.checkpoint_data


@pytest.mark.asyncio
async def test_cleaning_and_feature_agents_create_lineage_linked_datasets(client: AsyncClient) -> None:
    """Cleaning and feature agents must produce real derived artifacts, not smoke success."""
    token = await _token(client, role="data_engineer")
    headers = {"Authorization": f"Bearer {token}"}
    created = await client.post(
        "/datasets/",
        headers=headers,
        json={
            "name": "feature_source",
            "content": "category,unit_price,quantity\n A ,10,2\n A ,10,2\nB,5,3\n",
            "source_type": "csv",
        },
    )
    assert created.status_code == 200, created.text
    dataset_id = created.json()["id"]

    cleaned = await client.post("/agents/cleaning/execute", headers=headers, json={"dataset_id": dataset_id})
    assert cleaned.status_code == 200, cleaned.text
    assert cleaned.json()["row_count"] == 2
    assert cleaned.json()["lineage_recorded"] is True

    features = await client.post(
        "/agents/features/execute",
        headers=headers,
        json={
            "dataset_id": dataset_id,
            "transformation_plan": {"operations": [
                {"op": "derive_numeric", "name": "revenue", "left": "unit_price", "operator": "multiply", "right_column": "quantity"},
                {"op": "derive_string", "name": "category_clean", "column": "category", "operation": "strip"},
            ]},
        },
    )
    assert features.status_code == 200, features.text
    assert features.json()["output_path"].startswith("gold/")
    assert features.json()["lineage_recorded"] is True
