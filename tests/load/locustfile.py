"""Locust load profile for Aegis AI production SLO validation."""

from __future__ import annotations

import csv
import io
import random
import time
from pathlib import Path
from typing import Any

from locust import HttpUser, between, events, task

DATA_DIR = Path(__file__).parent / "data"


def _unique_email(prefix: str) -> str:
    """Return a unique load-test email."""

    return f"{prefix}-{int(time.time() * 1000)}-{random.randint(1000, 9999)}@load.local"


class AuthenticatedUser(HttpUser):
    """Base user with JWT registration, login, and relogin support."""

    abstract = True
    wait_time = between(1, 5)
    role = "viewer"
    password = "LoadTestPass123"

    def on_start(self) -> None:
        """Register and log in before protected requests."""

        self.email = _unique_email(self.__class__.__name__.lower())
        self.token = ""
        self.register_and_login()

    @property
    def headers(self) -> dict[str, str]:
        """Return auth headers."""

        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def register_and_login(self) -> None:
        """Create a user and obtain a bearer token."""

        self.client.post(
            "/auth/register",
            json={"email": self.email, "password": self.password, "role": self.role},
            name="/auth/register",
            catch_response=True,
        )
        with self.client.post(
            "/auth/login",
            data={"username": self.email, "password": self.password},
            name="/auth/login",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                self.token = response.json()["access_token"]
                response.success()
            else:
                response.failure(f"login failed: {response.status_code}")

    def request_with_reauth(self, method: str, path: str, **kwargs: Any) -> Any:
        """Issue a request and retry once on token failure."""

        headers = kwargs.pop("headers", {})
        headers.update(self.headers)
        response = getattr(self.client, method)(path, headers=headers, catch_response=True, **kwargs)
        if response.status_code in {401, 403}:
            self.register_and_login()
        return response


class HealthCheckUser(HttpUser):
    """Low-frequency public health checker."""

    weight = 1
    wait_time = between(5, 30)

    @task
    def health(self) -> None:
        """Validate health endpoint SLO."""

        self.client.get("/health", name="/health")


class AuthUser(AuthenticatedUser):
    """Authenticated user browsing profile and agent catalog."""

    weight = 2
    role = "viewer"

    @task(2)
    def profile(self) -> None:
        """Fetch current profile."""

        self.request_with_reauth("get", "/auth/me", name="/auth/me")

    @task(1)
    def agent_catalog_denied_or_allowed(self) -> None:
        """Hit a protected endpoint and track auth behavior."""

        self.request_with_reauth("get", "/agents/", name="/agents/")


class DataEngineerUser(AuthenticatedUser):
    """Data engineer uploading CSVs and triggering agents."""

    weight = 3
    role = "data_engineer"

    @task
    def upload_and_scan(self) -> None:
        """Upload CSV content, then run a PII scan agent."""

        content = load_sample_csv()
        dataset_name = f"load_orders_{random.randint(1, 999999)}"
        response = self.request_with_reauth(
            "post",
            "/datasets/",
            json={"name": dataset_name, "content": content, "source_type": "csv"},
            name="/datasets/",
        )
        if response.status_code != 200:
            return
        dataset = response.json()
        self.request_with_reauth(
            "post",
            "/agents/ingestion/execute",
            json={"dataset_id": dataset["id"], "artifact": dataset.get("bronze_path")},
            name="/agents/ingestion/execute",
        )


def load_sample_csv() -> str:
    """Load the sample CSV or synthesize 1000 rows if the fixture is compact."""

    path = DATA_DIR / "sample_1000.csv"
    text = path.read_text() if path.exists() else ""
    if text.count("\n") >= 1000:
        return text
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "customer_id", "region", "category", "amount", "discount", "email", "phone", "created_at", "status"])
    for index in range(1, 1001):
        writer.writerow(
            [
                index,
                f"C{index:04d}",
                ["north", "south", "east", "west"][index % 4],
                ["a", "b", "c"][index % 3],
                f"{10 + index * 1.5:.2f}",
                f"{(index % 20) / 100:.2f}",
                f"user{index}@example.com",
                f"555-010-{index % 10000:04d}",
                f"2026-01-{(index % 28) + 1:02d}",
                "active",
            ]
        )
    return buffer.getvalue()


class AnalystUser(AuthenticatedUser):
    """Analyst asking chat questions and browsing lineage."""

    weight = 2
    role = "analyst"

    @task(2)
    def ask_chat(self) -> None:
        """Query the chat API."""

        self.request_with_reauth(
            "post",
            "/chat/ask",
            json={"question": "What datasets are available?"},
            name="/chat/ask",
        )

    @task(1)
    def chat_history(self) -> None:
        """Fetch chat history."""

        self.request_with_reauth("get", "/chat/history", name="/chat/history")


class AdminUser(AuthenticatedUser):
    """Admin user checking audit logs and user management endpoints."""

    weight = 1
    role = "admin"

    @task(2)
    def audit_logs(self) -> None:
        """Fetch audit logs."""

        self.request_with_reauth("get", "/admin/audit-logs", name="/admin/audit-logs")

    @task(1)
    def users(self) -> None:
        """List users."""

        self.request_with_reauth("get", "/admin/users", name="/admin/users")


@events.request.add_listener
def record_custom_metrics(request_type: str, name: str, response_time: float, response_length: int, exception: Exception | None, **kwargs: Any) -> None:
    """Hook for endpoint-level latency, success, and error reporting."""

    del request_type, response_length, kwargs
    if exception:
        print(f"load_metric endpoint={name} status=error latency_ms={response_time:.2f} error={exception}")
    else:
        print(f"load_metric endpoint={name} status=success latency_ms={response_time:.2f}")
