"""Deployment artifact generation agent."""

import ast
from typing import Any

from src.agents.base import BaseAgent
from src.config import get_settings
from src.core.logging import configure_logging

logger = configure_logging(get_settings().AEGIS_DEBUG)


class DeployAgent(BaseAgent):
    """Generate a FastAPI inference service package for a trained model."""

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Create deployment source, Dockerfile, and requirements artifacts."""

        try:
            await self.storage.read(context["model_artifact_path"])
            for path in context.get("encoder_artifacts", {}).values():
                await self.storage.read(path)
            service_code = self._generate_service_code(context)
            ast.parse(service_code)
            base = f"deployments/{context['model_id']}"
            dockerfile = self._generate_dockerfile()
            requirements = "\n".join(["fastapi", "uvicorn", "pydantic", "scikit-learn", "pandas", "numpy", "joblib"]) + "\n"
            service_path = await self.store_artifact(f"{base}/main.py", service_code.encode(), "text/x-python")
            dockerfile_path = await self.store_artifact(f"{base}/Dockerfile", dockerfile.encode(), "text/plain")
            requirements_path = await self.store_artifact(f"{base}/requirements.txt", requirements.encode(), "text/plain")
            rationale = f"Generated FastAPI service for model {context['model_id']}"
            await self.log_decision("DEPLOYMENT_GENERATED", rationale, 0.95)
            return {
                "service_code_path": service_path,
                "dockerfile_path": dockerfile_path,
                "requirements_path": requirements_path,
                "endpoint_schema": {"features": context["feature_columns"], "target": context["target_column"]},
                "feature_count": len(context["feature_columns"]),
            }
        except Exception as exc:
            logger.error("deploy_agent_failed", error=str(exc))
            return {"deploy_failed": True, "error": "Unable to generate deployment artifacts."}

    def _generate_service_code(self, context: dict[str, Any]) -> str:
        """Render syntactically valid FastAPI inference code."""

        feature_lines = "\n".join(f"    {name}: Any" for name in context["feature_columns"])
        feature_columns = repr(list(context["feature_columns"]))
        model_id = repr(str(context["model_id"]))
        encoder_columns = repr(list(context.get("encoder_artifacts", {}).keys()))
        return f'''"""Generated Aegis AI inference service."""

from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

MODEL_VERSION = {model_id}
FEATURE_COLUMNS = {feature_columns}
ENCODER_COLUMNS = {encoder_columns}

app = FastAPI(title="Aegis Model Service")
model = joblib.load("model.pkl")
encoders = {{}}
for column in ENCODER_COLUMNS:
    encoders[column] = joblib.load("encoders/" + column + ".pkl")


class InputModel(BaseModel):
{feature_lines}


@app.get("/health")
async def health() -> dict[str, str]:
    return {{"status": "healthy", "model_version": MODEL_VERSION}}


@app.post("/predict")
async def predict(payload: InputModel) -> dict[str, Any]:
    row = payload.model_dump()
    frame = pd.DataFrame([row], columns=FEATURE_COLUMNS)
    for column, encoder in encoders.items():
        if column in frame:
            frame[column] = encoder.transform(frame[column])
    prediction = model.predict(frame)[0]
    confidence = 1.0
    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(frame)[0]
        confidence = float(np.max(probabilities))
    if hasattr(prediction, "item"):
        prediction = prediction.item()
    return {{"prediction": prediction, "confidence": confidence, "model_version": MODEL_VERSION}}
'''

    def _generate_dockerfile(self) -> str:
        """Return a deployable Dockerfile for the generated service."""

        return """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
COPY model.pkl .
COPY encoders/ ./encoders/
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
"""
