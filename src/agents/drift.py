"""Drift detection agent."""

import io
import json
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from src.agents.base import BaseAgent
from src.config import get_settings
from src.core.logging import configure_logging

logger = configure_logging(get_settings().AEGIS_DEBUG)


class DriftAgent(BaseAgent):
    """Detect numerical and categorical data drift between dataset snapshots."""

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Compare baseline and current CSV distributions."""

        try:
            baseline = pd.read_csv(io.BytesIO(await self.storage.read(context["baseline_data_path"])))
            current = pd.read_csv(io.BytesIO(await self.storage.read(context["current_data_path"])))
            psi_scores = {
                column: self._calculate_psi(baseline[column], current[column])
                for column in context.get("numerical_columns", [])
                if column in baseline and column in current
            }
            categorical_scores = {
                column: self._categorical_divergence(baseline[column], current[column])
                for column in context.get("categorical_columns", [])
                if column in baseline and column in current
            }
            affected = [name for name, score in psi_scores.items() if score >= 0.1] + [
                name for name, score in categorical_scores.items() if score >= 0.1
            ]
            max_score = max([0.0, *psi_scores.values(), *categorical_scores.values()])
            severity = "significant" if max_score > 0.25 else "moderate" if max_score >= 0.1 else "none"
            report = {
                "drift_detected": bool(affected),
                "affected_features": affected,
                "severity": severity,
                "recommendation": "Retrain or investigate data source changes." if affected else "No immediate action required.",
            }
            try:
                prompt = (
                    "Return JSON keys drift_detected, affected_features, severity, recommendation for these drift scores: "
                    f"PSI={psi_scores}, categorical={categorical_scores}."
                )
                report.update(json.loads(await self.llm.generate(prompt, expect_json=True)))
            except Exception as exc:
                logger.warning("drift_llm_fallback", agent=self.name, error=str(exc))
            artifact = {
                "model_id": context["model_id"],
                "dataset_id": context["dataset_id"],
                "psi_scores": psi_scores,
                "categorical_scores": categorical_scores,
                **report,
            }
            key = f"drift/{context['model_id']}/{datetime.utcnow().isoformat()}.json"
            await self.store_artifact(key, json.dumps(artifact, indent=2).encode(), "application/json")
            await self.log_decision("DRIFT_CHECK", f"Drift severity: {report['severity']}", 0.8)
            return {**report, "psi_scores": psi_scores, "report_path": key}
        except Exception as exc:
            logger.error("drift_agent_failed", error=str(exc))
            return {"drift_failed": True, "error": "Unable to complete drift check.", "drift_detected": False}

    def _calculate_psi(self, baseline: pd.Series, current: pd.Series, bins: int = 10) -> float:
        """Calculate Population Stability Index from scratch."""

        baseline_values = pd.to_numeric(baseline, errors="coerce").dropna()
        current_values = pd.to_numeric(current, errors="coerce").dropna()
        if baseline_values.empty or current_values.empty:
            return 0.0
        quantiles = np.linspace(0, 1, bins + 1)
        edges = np.unique(np.quantile(baseline_values, quantiles))
        if len(edges) < 2:
            return 0.0
        edges[0] = -np.inf
        edges[-1] = np.inf
        baseline_counts, _ = np.histogram(baseline_values, bins=edges)
        current_counts, _ = np.histogram(current_values, bins=edges)
        epsilon = 1e-6
        baseline_pct = np.maximum(baseline_counts / max(len(baseline_values), 1), epsilon)
        current_pct = np.maximum(current_counts / max(len(current_values), 1), epsilon)
        return float(np.sum((current_pct - baseline_pct) * np.log(current_pct / baseline_pct)))

    def _categorical_divergence(self, baseline: pd.Series, current: pd.Series) -> float:
        """Calculate KL-style categorical distribution divergence."""

        baseline_dist = baseline.astype(str).value_counts(normalize=True)
        current_dist = current.astype(str).value_counts(normalize=True)
        categories = sorted(set(baseline_dist.index) | set(current_dist.index))
        epsilon = 1e-6
        total = 0.0
        for category in categories:
            expected = max(float(baseline_dist.get(category, 0.0)), epsilon)
            observed = max(float(current_dist.get(category, 0.0)), epsilon)
            total += (observed - expected) * np.log(observed / expected)
        return float(total)
