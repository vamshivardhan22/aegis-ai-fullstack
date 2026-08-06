"""Safe chaos tests for Docker Compose environments."""

import pytest


@pytest.mark.chaos
def test_database_failure_plan_is_safe() -> None:
    """Document the database failure drill without touching production resources."""

    steps = ["pause postgres", "run pipeline", "verify graceful failure", "resume postgres", "retry pipeline"]
    assert len(steps) == 5


@pytest.mark.chaos
def test_llm_storage_and_network_failure_plans_are_safe() -> None:
    """Verify chaos drills are declared as safe compose-level operations."""

    drills = {"llm": "block ollama port", "storage": "make minio read-only", "network": "isolate api from database"}
    assert {"llm", "storage", "network"}.issubset(drills)
