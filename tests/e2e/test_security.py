"""Security and RBAC E2E tests."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_auth_and_rbac_security(client: AsyncClient) -> None:
    """Verify weak passwords, wrong login, missing tokens, viewer denial, and rate limiting."""

    weak = await client.post("/auth/register", json={"email": "weak@example.com", "password": "short", "role": "viewer"})
    assert weak.status_code == 422
    await client.post(
        "/auth/register",
        json={"email": "viewer-security@example.com", "password": "SecurePass123", "role": "viewer"},
    )
    wrong = await client.post("/auth/login", data={"username": "viewer-security@example.com", "password": "wrong"})
    assert wrong.status_code == 401
    no_token = await client.get("/agents/")
    assert no_token.status_code == 401
    login = await client.post("/auth/login", data={"username": "viewer-security@example.com", "password": "SecurePass123"})
    token = login.json()["access_token"]
    admin_denied = await client.get("/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert admin_denied.status_code == 403


@pytest.mark.asyncio
async def test_rate_limit_eventually_returns_429(client: AsyncClient) -> None:
    """Hammer an endpoint enough to verify rate limiting is active."""

    statuses = []
    for _ in range(260):
        response = await client.get("/agents/")
        statuses.append(response.status_code)
        if response.status_code == 429:
            break
    assert 429 in statuses
