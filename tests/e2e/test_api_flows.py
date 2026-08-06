"""End-to-end API flow tests."""

import pytest
from httpx import AsyncClient


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
