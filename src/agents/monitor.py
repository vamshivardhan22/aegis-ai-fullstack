"""Monitoring agent for deployed model endpoints."""

import time
from datetime import datetime
from typing import Any

import httpx
from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import BaseAgent
from src.config import get_settings
from src.core.logging import configure_logging
from src.database.models import Alert, AlertSeverity, Metric
from src.database.repository import AlertRepository, MetricRepository

logger = configure_logging(get_settings().AEGIS_DEBUG)

LATENCY_HISTOGRAM = Histogram("aegis_prediction_latency_seconds", "Prediction latency in seconds")
ERROR_COUNTER = Counter("aegis_prediction_errors_total", "Prediction endpoint errors")
HEALTH_GAUGE = Gauge("aegis_model_health", "Model health, 1 healthy and 0 unhealthy")


class MonitorAgent(BaseAgent):
    """Probe model services and persist operational telemetry."""

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run one monitoring check against a deployed endpoint."""

        alerts_triggered: list[str] = []
        latency_ms = 0.0
        is_healthy = False
        try:
            base_url = str(context["endpoint_url"]).rstrip("/")
            transport = context.get("_transport")
            async with httpx.AsyncClient(timeout=10.0, transport=transport) as client:
                start = time.perf_counter()
                health = await client.get(base_url + "/health")
                health_latency_ms = (time.perf_counter() - start) * 1000
                is_healthy = health.status_code == 200
                if not is_healthy:
                    alerts_triggered.append("health_check_failed")
                    await self._create_alert("health_check_failed", 1.0, 0.0, "critical", "Health check failed")
                dummy_payload = context.get("dummy_payload", {})
                start = time.perf_counter()
                prediction = await client.post(base_url + "/predict", json=dummy_payload)
                latency_ms = (time.perf_counter() - start) * 1000
                status_code = prediction.status_code
                if status_code != 200:
                    ERROR_COUNTER.inc()
                    alerts_triggered.append("prediction_error")
                    is_healthy = False
                    await self._create_alert("prediction_error", 0.0, float(status_code), "critical", "Prediction failed")
                latency_ms = max(latency_ms, health_latency_ms)

            await self._store_metric(context, "latency_ms", latency_ms)
            await self._store_metric(context, "status_code", float(status_code))
            threshold = context.get("alert_thresholds", {}).get("latency_p95_ms")
            if threshold is not None and latency_ms > float(threshold):
                alerts_triggered.append("latency_p95_ms")
                await self._create_alert("latency_p95_ms", float(threshold), latency_ms, "high", "Latency threshold exceeded")
            LATENCY_HISTOGRAM.observe(latency_ms / 1000)
            HEALTH_GAUGE.set(1 if is_healthy else 0)
            await self.log_decision("MONITORING_CHECK", f"Checked {context['endpoint_url']}, latency={latency_ms:.2f}ms", 0.9)
            return {
                "latency_ms": latency_ms,
                "is_healthy": is_healthy,
                "alerts_triggered": alerts_triggered,
                "check_timestamp": datetime.utcnow().isoformat(),
            }
        except httpx.ConnectError as exc:
            logger.warning("monitor_endpoint_unreachable", error=str(exc))
            ERROR_COUNTER.inc()
            HEALTH_GAUGE.set(0)
            await self._create_alert("endpoint_unreachable", 1.0, 0.0, "critical", "Endpoint unreachable")
            await self.log_decision("MONITORING_CHECK", f"Endpoint unreachable: {context.get('endpoint_url')}", 0.9)
            return {
                "latency_ms": latency_ms,
                "is_healthy": False,
                "alerts_triggered": ["endpoint_unreachable"],
                "check_timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as exc:
            logger.error("monitor_agent_failed", error=str(exc))
            return {"monitor_failed": True, "error": "Unable to complete monitoring check.", "is_healthy": False}

    async def _store_metric(self, context: dict[str, Any], name: str, value: float) -> None:
        """Persist a metric when a session is available."""

        if isinstance(self.db_repo, AsyncSession):
            await MetricRepository(self.db_repo).create(
                Metric(
                    deployment_id=context.get("deployment_id"),
                    metric_name=name,
                    metric_value=value,
                    labels_json={"deployment_id": context.get("deployment_id"), "endpoint": context.get("endpoint_url")},
                )
            )

    async def _create_alert(self, name: str, threshold: float, actual: float, severity: str, message: str) -> None:
        """Persist an alert when a session is available."""

        if isinstance(self.db_repo, AsyncSession):
            await AlertRepository(self.db_repo).create(
                Alert(
                    metric_name=name,
                    threshold=threshold,
                    actual_value=actual,
                    severity=AlertSeverity(severity),
                    message=message,
                )
            )
