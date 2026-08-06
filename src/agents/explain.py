"""Explainability agent for trained models."""

import io
import json
import pickle
from typing import Any

import numpy as np
import pandas as pd

from src.agents.base import BaseAgent
from src.config import get_settings
from src.core.logging import configure_logging

logger = configure_logging(get_settings().AEGIS_DEBUG)


class ExplainAgent(BaseAgent):
    """Generate SHAP-based model explanations and business summaries."""

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Explain a model artifact against sample feature data."""

        try:
            model = self._load_model(await self.storage.read(context["model_artifact_path"]))
            sample = pd.read_csv(io.BytesIO(await self.storage.read(context["sample_data_path"])))
            top_features: list[dict[str, Any]]
            shap_shape: tuple[int, ...]
            shap_failed = False
            try:
                values = self._calculate_shap_values(model, sample)
                shap_array = self._to_2d_array(values)
                shap_shape = tuple(int(part) for part in shap_array.shape)
                importances = np.abs(shap_array).mean(axis=0)
                directions = np.sign(shap_array.mean(axis=0))
                ranked = np.argsort(importances)[::-1][:5]
                top_features = [
                    {
                        "name": str(sample.columns[index]),
                        "importance": float(importances[index]),
                        "direction": "positive" if directions[index] >= 0 else "negative",
                    }
                    for index in ranked
                ]
            except Exception as exc:
                logger.warning("shap_failed", agent=self.name, error=str(exc))
                shap_failed = True
                numeric = sample.select_dtypes(include=[np.number])
                scores = numeric.std(numeric_only=True).fillna(0.0).sort_values(ascending=False).head(5)
                top_features = [
                    {"name": str(name), "importance": float(value), "direction": "positive"}
                    for name, value in scores.items()
                ]
                shap_shape = (len(sample), len(sample.columns))

            summary = self._statistical_summary(model, top_features)
            explanation = {
                "summary": summary,
                "top_features": top_features,
                "business_insight": "Review the highest-importance features before promoting this model.",
            }
            try:
                prompt = (
                    "Explain this model using JSON with keys summary, top_features, business_insight. "
                    f"Model type: {type(model).__name__}. Top features: {top_features}."
                )
                explanation = json.loads(await self.llm.generate(prompt, expect_json=True))
            except Exception as exc:
                logger.warning("explain_llm_fallback", agent=self.name, error=str(exc))

            artifact = {
                "model_id": context["model_id"],
                "dataset_id": context["dataset_id"],
                "shap_failed": shap_failed,
                **explanation,
            }
            key = f"explanations/{context['model_id']}.json"
            await self.store_artifact(key, json.dumps(artifact, indent=2).encode(), "application/json")
            await self.log_decision("MODEL_EXPLAINED", str(explanation.get("summary", summary)), 0.85)
            return {
                "explanation_path": key,
                "top_features": explanation.get("top_features", top_features),
                "shap_values_shape": shap_shape,
                "summary": explanation.get("summary", summary),
                "shap_failed": shap_failed,
            }
        except Exception as exc:
            logger.error("explain_agent_failed", error=str(exc))
            return {"explain_failed": True, "error": "Unable to generate model explanation."}

    def _calculate_shap_values(self, model: Any, sample: pd.DataFrame) -> Any:
        """Calculate SHAP values with a model-appropriate explainer."""

        import shap

        tree_markers = ("forest", "tree", "xgb", "lgbm", "catboost", "gradientboosting")
        model_name = type(model).__name__.lower()
        explainer = shap.TreeExplainer(model) if any(marker in model_name for marker in tree_markers) else shap.Explainer(model, sample)
        values = explainer(sample)
        return getattr(values, "values", values)

    def _load_model(self, data: bytes) -> Any:
        """Load model bytes with joblib when installed, otherwise pickle."""

        try:
            import joblib

            return joblib.load(io.BytesIO(data))
        except ImportError:
            return pickle.loads(data)

    def _to_2d_array(self, values: Any) -> np.ndarray:
        """Normalize SHAP output to rows by features."""

        array = np.asarray(values)
        if array.ndim == 3:
            array = np.mean(array, axis=2)
        return array.reshape((array.shape[0], -1))

    def _statistical_summary(self, model: Any, top_features: list[dict[str, Any]]) -> str:
        """Build a deterministic fallback explanation."""

        names = ", ".join(feature["name"] for feature in top_features) or "available features"
        return f"{type(model).__name__} is most influenced by {names}."
