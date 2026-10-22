"""Generate a reproducible inference-service package for a registered model."""
from __future__ import annotations

import ast
import importlib.metadata
import keyword
import re
from typing import Any

from src.agents.base import BaseAgent
from src.config import get_settings
from src.core.exceptions import AgentError, ValidationError
from src.core.logging import configure_logging

logger = configure_logging(get_settings().AEGIS_DEBUG)
_FEATURE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class DeployAgent(BaseAgent):
    """Package the registered sklearn pipeline and a safe FastAPI inference wrapper."""

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Create service source, model binary, Dockerfile, and pinned requirements."""
        try:
            model_id = context.get("model_id")
            artifact_path = context.get("model_artifact_path")
            features = context.get("feature_columns")
            target = context.get("target_column")
            if not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id):
                raise ValidationError("A valid registered model_id is required")
            if not isinstance(artifact_path, str) or not artifact_path.startswith("models/"):
                raise ValidationError("A registered model artifact path is required")
            if not isinstance(features, list) or not features or not all(
                isinstance(name, str) and _FEATURE_NAME.fullmatch(name) and not keyword.iskeyword(name)
                for name in features
            ):
                raise ValidationError("Model feature columns must be safe Python identifiers")
            if len(features) != len(set(features)):
                raise ValidationError("Model feature columns must be unique")
            if not isinstance(target, str) or not target:
                raise ValidationError("Model target column metadata is required")

            model_bytes = await self.storage.read(artifact_path)
            service_code = self._generate_service_code(model_id, features)
            ast.parse(service_code)
            base = f"deployments/{model_id}"
            dockerfile = self._generate_dockerfile()
            requirements = self._generate_requirements()
            model_path = await self.store_artifact(f"{base}/model.pkl", model_bytes, "application/octet-stream")
            service_path = await self.store_artifact(f"{base}/main.py", service_code.encode("utf-8"), "text/x-python")
            dockerfile_path = await self.store_artifact(f"{base}/Dockerfile", dockerfile.encode("utf-8"), "text/plain")
            requirements_path = await self.store_artifact(
                f"{base}/requirements.txt", requirements.encode("utf-8"), "text/plain"
            )
            await self.log_decision("DEPLOYMENT_PACKAGE_GENERATED", f"Packaged model {model_id} for review", 1.0)
            return {
                "model_id": model_id,
                "model_path": model_path,
                "service_code_path": service_path,
                "dockerfile_path": dockerfile_path,
                "requirements_path": requirements_path,
                "endpoint_schema": {"features": features, "target": target},
                "feature_count": len(features),
                "deployment_status": "package_ready_review_required",
            }
        except ValidationError:
            raise
        except Exception as exc:
            logger.error("deploy_agent_failed", error=str(exc))
            raise AgentError("Unable to generate deployment package.") from exc

    def _generate_service_code(self, model_id: str, feature_columns: list[str]) -> str:
        """Render an inference service that invokes the saved preprocessing/model pipeline."""
        feature_lines = "\n".join(f"    {name}: Any" for name in feature_columns)
        feature_literal = repr(list(feature_columns))
        version_literal = repr(model_id)
        return f'''"""Generated Aegis DataOps inference service."""
from typing import Any

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI
from pydantic import BaseModel

MODEL_VERSION = {version_literal}
FEATURE_COLUMNS = {feature_literal}

app = FastAPI(title="Aegis DataOps Model Service")
model = joblib.load("model.pkl")


class InputModel(BaseModel):
{feature_lines}


@app.get("/health")
async def health() -> dict[str, str]:
    return {{"status": "healthy", "model_version": MODEL_VERSION}}


@app.post("/predict")
async def predict(payload: InputModel) -> dict[str, Any]:
    frame = pd.DataFrame([payload.model_dump()], columns=FEATURE_COLUMNS)
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
        """Return a Dockerfile for the generated service package."""
        return '''FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py model.pkl ./
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
'''

    def _generate_requirements(self) -> str:
        """Pin runtime libraries to the versions used by the training service."""
        packages = ["fastapi", "uvicorn", "pydantic", "scikit-learn", "pandas", "numpy", "joblib"]
        lines = []
        for package in packages:
            try:
                version = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError as exc:
                raise ValidationError("Cannot pin deployment runtime because a required package is missing", {"package": package}) from exc
            lines.append(f"{package}=={version}")
        return "\n".join(lines) + "\n"
