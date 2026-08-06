"""Fault tolerance E2E tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_llm_and_agent_fallbacks(client: AsyncClient) -> None:
    """Verify agents return controlled responses when optional services are unavailable."""

    await client.post(
        "/auth/register",
        json={"email": "engineer-fault@example.com", "password": "SecurePass123", "role": "data_engineer"},
    )
    login = await client.post("/auth/login", data={"username": "engineer-fault@example.com", "password": "SecurePass123"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    dataset = await client.post(
        "/datasets/",
        headers=headers,
        json={"name": "fault_orders", "content": "id,email\n1,test@example.com\n", "source_type": "csv"},
    )
    response = await client.post(
        "/agents/pii/execute",
        headers=headers,
        json={"dataset_id": dataset.json()["id"], "data_sample_path": dataset.json()["bronze_path"]},
    )
    assert response.status_code == 200
    assert "pii_detected" in response.json()


@pytest.mark.asyncio
async def test_health_degrades_meaningfully(client: AsyncClient) -> None:
    """Verify health response has structured dependency checks."""

    response = await client.get("/health")
    payload = response.json()
    assert response.status_code == 200
    assert "checks" in payload
    assert "database" in payload["checks"]
