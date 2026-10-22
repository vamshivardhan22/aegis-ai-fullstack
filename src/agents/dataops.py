"""Real dataset operations for the standalone agent API."""
from __future__ import annotations

import hashlib
import io
import re
from typing import Any
from uuid import uuid4

import joblib
import pandas as pd
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import BaseAgent
from src.agents.safe_transform import apply_transformation_plan
from src.core.exceptions import ValidationError
from src.database.models import Dataset, Lineage, Model, ModelStatus, Pipeline
from src.database.repository import DatasetRepository, LineageRepository, ModelRepository
from src.workflows.csv_pipeline import _detect_pii, _profile

MAX_AGENT_BYTES = 50 * 1024 * 1024


class DatasetOperationAgent(BaseAgent):
    """Perform a concrete ingestion, schema, quality, cleaning, feature, or ML operation."""

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.db_repo, AsyncSession):
            raise ValidationError("Dataset operations require a database session")
        dataset_id = context.get("dataset_id")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ValidationError("dataset_id is required")
        repository = DatasetRepository(self.db_repo)
        dataset = await repository.get_by_id(dataset_id)
        if dataset is None or dataset.is_deleted:
            raise HTTPException(status_code=404, detail="Dataset not found")
        path = context.get("source_data_path") or context.get("artifact") or context.get("data_sample_path")
        if not path:
            path = dataset.gold_path or dataset.silver_path or dataset.bronze_path
        if not path or path not in {dataset.bronze_path, dataset.silver_path, dataset.gold_path}:
            raise HTTPException(status_code=404, detail="Dataset artifact not found")
        raw = await self.storage.read(path)
        if len(raw) > MAX_AGENT_BYTES:
            raise ValidationError("Agent input exceeds the 50 MiB processing limit")
        try:
            frame = pd.read_csv(io.BytesIO(raw))
        except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
            raise ValidationError("Dataset artifact is not a valid CSV") from exc
        if frame.empty or len(frame.columns) == 0:
            raise ValidationError("Dataset must contain a header and at least one data row")
        if len(frame.columns) > 500 or frame.columns.duplicated().any():
            raise ValidationError("Dataset has too many columns or duplicate column names")

        if self.name == "ingestion":
            profile = _profile(frame, raw)
            await self.log_decision("INGESTION_VERIFIED", f"Verified {len(frame)} rows from the selected artifact", 1.0)
            return {
                "dataset_id": dataset.id, "artifact_path": path, "row_count": len(frame),
                "column_count": len(frame.columns), "sha256": hashlib.sha256(raw).hexdigest(),
                "schema": {str(column): str(dtype) for column, dtype in frame.dtypes.items()}, "profile": profile,
            }
        if self.name == "schema":
            required = context.get("required_columns", [])
            expected = context.get("expected_schema", {})
            if not isinstance(required, list) or not all(isinstance(column, str) for column in required):
                raise ValidationError("required_columns must be a list of strings")
            if not isinstance(expected, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in expected.items()):
                raise ValidationError("expected_schema must map column names to dtype strings")
            missing = [column for column in required if column not in frame.columns]
            schema = {str(column): str(dtype) for column, dtype in frame.dtypes.items()}
            mismatches = {
                column: {"expected": dtype, "actual": schema.get(column)}
                for column, dtype in expected.items() if schema.get(column) != dtype
            }
            if missing or mismatches:
                raise ValidationError("Dataset schema contract failed", {"missing_columns": missing, "dtype_mismatches": mismatches})
            return {"dataset_id": dataset.id, "valid": True, "schema": schema, "row_count": len(frame)}
        if self.name == "quality":
            profile = _profile(frame, raw)
            await self.log_decision("DATA_QUALITY_PROFILED", f"Calculated quality score {profile['quality_score']}", 1.0)
            return {"dataset_id": dataset.id, "quality_score": profile["quality_score"], "profile": profile}
        if self.name in {"cleaning", "features"}:
            pii_columns = _detect_pii(frame)
            source_profile = dataset.profile_json or {}
            if pii_columns and not source_profile.get("masking_applied"):
                raise ValidationError(
                    "Sensitive columns were detected. Run the governed pipeline to mask and approve this dataset before cleaning or feature publication.",
                    {"columns": list(pii_columns)},
                )
            plan = context.get("transformation_plan")
            if plan is None and self.name == "cleaning":
                plan = {"operations": [{"op": "drop_duplicates"}]}
            if not isinstance(plan, dict) or not isinstance(plan.get("operations"), list):
                raise ValidationError("transformation_plan must contain an operations list")
            if self.name == "features" and not plan["operations"]:
                raise ValidationError("Feature engineering requires at least one explicit allow-listed operation")
            transformed = apply_transformation_plan(frame, plan)
            return await self._publish_derived(dataset, raw, transformed, plan, "cleaning" if self.name == "cleaning" else "feature_engineering")
        if self.name == "ml":
            return await self._train_model(dataset, frame, context)
        raise ValidationError("Unknown dataset operation", {"agent": self.name})

    async def _publish_derived(
        self, source: Dataset, source_bytes: bytes, frame: pd.DataFrame, plan: dict[str, Any], operation: str
    ) -> dict[str, Any]:
        """Write an immutable derived artifact and create its dataset/lineage records."""
        if frame.empty:
            raise ValidationError("Transformation produced zero rows; derived dataset was not published")
        output_bytes = frame.to_csv(index=False).encode("utf-8")
        profile = _profile(frame, source_bytes)
        if profile["non_finite_cells"]:
            raise ValidationError("Derived dataset contains non-finite numeric values")
        profile["output_sha256"] = hashlib.sha256(output_bytes).hexdigest()
        source_profile = source.profile_json or {}
        profile["masking_applied"] = bool(source_profile.get("masking_applied"))
        profile["pii_columns"] = source_profile.get("pii_columns", {})
        artifact_id = uuid4().hex
        layer = "silver" if operation == "cleaning" else "gold"
        path = f"{layer}/{source.project_id}/{artifact_id}.csv"
        await self.storage.write(path, output_bytes, "text/csv")
        suffix = "cleaned" if operation == "cleaning" else "features"
        target = await DatasetRepository(self.db_repo).create(Dataset(
            project_id=source.project_id,
            name=f"{source.name}-{suffix}-{artifact_id[:8]}",
            source_type="transformed",
            silver_path=path if layer == "silver" else None,
            gold_path=path if layer == "gold" else None,
            schema_json={str(column): str(dtype) for column, dtype in frame.dtypes.items()},
            profile_json=profile,
            row_count=len(frame),
            column_count=len(frame.columns),
            size_bytes=len(output_bytes),
            quality_score=profile["quality_score"],
            version=source.version + 1,
        ))
        await LineageRepository(self.db_repo).create(Lineage(
            source_dataset_id=source.id,
            target_dataset_id=target.id,
            transformation_type=operation,
            agent_id=self.name,
            config_json={"plan": plan, "source_sha256": hashlib.sha256(source_bytes).hexdigest()},
        ))
        await self.log_decision("DERIVED_DATASET_CREATED", f"Created derived dataset {target.id}", 1.0)
        return {
            "source_dataset_id": source.id,
            "output_dataset_id": target.id,
            "output_path": path,
            "row_count": target.row_count,
            "column_count": target.column_count,
            "quality_score": target.quality_score,
            "lineage_recorded": True,
        }

    async def _train_model(
        self, dataset: Dataset, frame: pd.DataFrame, context: dict[str, Any]
    ) -> dict[str, Any]:
        """Train and register a bounded sklearn baseline model on a project-scoped dataset."""
        target = context.get("target_column")
        task = context.get("task")
        if not isinstance(target, str) or target not in frame.columns:
            raise ValidationError("ML execution requires a valid target_column")
        if not isinstance(task, str) or task not in {"classification", "regression"}:
            raise ValidationError("task must be classification or regression")
        pii_columns = _detect_pii(frame)
        if target in pii_columns:
            raise ValidationError("Sensitive columns cannot be used as the ML target")
        requested_features = context.get("feature_columns")
        if requested_features is None:
            features = [column for column in frame.columns if column != target and column not in pii_columns]
        elif isinstance(requested_features, list) and all(isinstance(column, str) for column in requested_features):
            features = requested_features
        else:
            raise ValidationError("feature_columns must be a list of column names")
        if not features or len(features) != len(set(features)):
            raise ValidationError("ML training requires a non-empty unique feature_columns list")
        missing = [column for column in features if column not in frame.columns]
        if missing:
            raise ValidationError("ML feature columns are missing", {"missing_columns": missing})
        sensitive_features = [column for column in features if column in pii_columns]
        if sensitive_features:
            raise ValidationError("Sensitive columns cannot be used as ML features", {"columns": sensitive_features})
        if target in features:
            raise ValidationError("Target column cannot also be a feature")
        training = frame.loc[:, [*features, target]].dropna(subset=[target]).copy()
        if len(training) < 10:
            raise ValidationError("At least 10 non-null target rows are required for a train/test evaluation")
        if task == "regression":
            training[target] = pd.to_numeric(training[target], errors="coerce")
            training = training.dropna(subset=[target])
            if len(training) < 10:
                raise ValidationError("Regression target must contain at least 10 numeric values")
        y = training[target]
        if task == "classification" and y.nunique() < 2:
            raise ValidationError("Classification requires at least two target classes")
        X = training[features].dropna(axis=1, how="all")
        features = list(X.columns)
        if not features:
            raise ValidationError("No usable features remain after removing all-null columns")

        try:
            from sklearn.compose import ColumnTransformer
            from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
            from sklearn.impute import SimpleImputer
            from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, r2_score
            from sklearn.model_selection import train_test_split
            from sklearn.pipeline import Pipeline as SklearnPipeline
            from sklearn.preprocessing import OneHotEncoder
        except ImportError as exc:
            raise ValidationError("scikit-learn is required for ML execution") from exc

        numeric = list(X.select_dtypes(include=["number", "bool"]).columns)
        categorical = [column for column in features if column not in numeric]
        transformers = []
        if numeric:
            transformers.append(("numeric", SklearnPipeline([("imputer", SimpleImputer(strategy="median"))]), numeric))
        if categorical:
            transformers.append((
                "categorical",
                SklearnPipeline([
                    ("imputer", SimpleImputer(strategy="most_frequent")),
                    ("onehot", OneHotEncoder(handle_unknown="ignore")),
                ]),
                categorical,
            ))
        preprocessor = ColumnTransformer(transformers=transformers, remainder="drop")
        estimator = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1, class_weight="balanced_subsample") if task == "classification" else RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
        model_pipeline = SklearnPipeline([("preprocessor", preprocessor), ("model", estimator)])
        test_size = context.get("test_size", 0.2)
        if isinstance(test_size, bool) or not isinstance(test_size, (int, float)) or not 0.1 <= float(test_size) <= 0.4:
            raise ValidationError("test_size must be between 0.1 and 0.4")
        stratify = None
        if task == "classification" and y.value_counts().min() >= 2:
            stratify = y
        try:
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=float(test_size), random_state=42, stratify=stratify
            )
            model_pipeline.fit(X_train, y_train)
            predictions = model_pipeline.predict(X_test)
            if task == "classification":
                metrics = {
                    "accuracy": float(accuracy_score(y_test, predictions)),
                    "f1_weighted": float(f1_score(y_test, predictions, average="weighted", zero_division=0)),
                }
            else:
                metrics = {
                    "mae": float(mean_absolute_error(y_test, predictions)),
                    "r2": float(r2_score(y_test, predictions)) if len(y_test) > 1 else 0.0,
                }
        except Exception as exc:
            raise ValidationError("Model training or evaluation failed", {"reason": str(exc)[:200]}) from exc

        buffer = io.BytesIO()
        joblib.dump(model_pipeline, buffer)
        artifact_bytes = buffer.getvalue()
        artifact_path = f"models/{dataset.project_id}/{uuid4().hex}.joblib"
        await self.storage.write(artifact_path, artifact_bytes, "application/octet-stream")
        pipeline_id = context.get("pipeline_id")
        if pipeline_id is not None and not isinstance(pipeline_id, str):
            raise ValidationError("pipeline_id must be a string")
        if pipeline_id:
            pipeline = await self.db_repo.get(Pipeline, pipeline_id)
            if pipeline is None or pipeline.project_id != dataset.project_id:
                raise ValidationError("pipeline_id must identify a pipeline in the same project")
        name = re.sub(r"[^A-Za-z0-9._-]", "_", str(context.get("model_name") or f"{dataset.name}-{task}"))[:200]
        model_record = await ModelRepository(self.db_repo).create(Model(
            dataset_id=dataset.id,
            pipeline_id=pipeline_id,
            name=name,
            algorithm="RandomForestClassifier" if task == "classification" else "RandomForestRegressor",
            problem_type=task,
            metrics_json=metrics,
            parameters_json={"features": features, "target": target, "test_size": float(test_size), "random_state": 42},
            artifact_path=artifact_path,
            status=ModelStatus.STAGING,
            is_active=True,
        ))
        await self.log_decision("MODEL_TRAINED", f"Trained {task} model {model_record.id}", 1.0)
        return {
            "model_id": model_record.id,
            "dataset_id": dataset.id,
            "model_name": model_record.name,
            "algorithm": model_record.algorithm,
            "problem_type": task,
            "metrics": metrics,
            "artifact_path": artifact_path,
            "training_rows": len(X_train),
            "test_rows": len(X_test),
            "features": features,
            "target_column": target,
            "pii_features_excluded": list(pii_columns),
        }
