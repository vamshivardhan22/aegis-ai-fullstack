"""Deterministic data-stage agents; do not return synthetic success."""
from __future__ import annotations

import hashlib
import io
import json
from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import BaseAgent
from src.agents.safe_transform import apply_transformation_plan
from src.core.exceptions import ValidationError
from src.database.models import Dataset, Lineage
from src.database.repository import DatasetRepository, LineageRepository


class CompatibilityAgent(BaseAgent):
    """Perform real bounded work for ingestion, schema, quality, cleaning and features."""

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(self.db_repo, AsyncSession) or not context.get("dataset_id"):
            raise ValidationError("dataset_id and database session are required")
        repo = DatasetRepository(self.db_repo)
        dataset = await repo.get_by_id(str(context["dataset_id"]))
        if dataset is None or dataset.is_deleted:
            raise ValidationError("Dataset not found")
        path = context.get("artifact") or dataset.bronze_path or dataset.silver_path
        if not isinstance(path, str) or path not in {dataset.bronze_path, dataset.silver_path, dataset.gold_path}:
            raise ValidationError("Artifact is not attached to the requested dataset")
        raw = await self.storage.read(path)
        if not raw or len(raw) > 50 * 1024 * 1024:
            raise ValidationError("CSV is empty or exceeds the 50 MiB limit")
        try:
            frame = pd.read_csv(io.BytesIO(raw))
        except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
            raise ValidationError("Source is not a valid CSV") from exc
        if frame.empty or frame.columns.duplicated().any() or not 1 <= len(frame.columns) <= 500:
            raise ValidationError("CSV needs data rows and unique column names; maximum 500 columns")
        result: dict[str, Any]
        if self.name == "ingestion":
            report = {"rows": len(frame), "columns": list(frame.columns), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            await repo.update(dataset.id, {"row_count": len(frame), "column_count": len(frame.columns), "size_bytes": len(raw)})
            result = {"status": "completed", "report": report}
        elif self.name == "schema":
            schema = {str(c): {"dtype": str(frame[c].dtype), "nulls": int(frame[c].isna().sum()), "distinct": int(frame[c].nunique(dropna=True))} for c in frame.columns}
            await repo.update(dataset.id, {"schema_json": {c: v["dtype"] for c, v in schema.items()}})
            result = {"status": "completed", "schema": schema}
        elif self.name == "quality":
            cells = max(1, int(frame.shape[0] * frame.shape[1]))
            nulls, duplicates = int(frame.isna().sum().sum()), int(frame.duplicated().sum())
            score = round(max(0.0, min(1.0, 1 - .7 * nulls / cells - .3 * duplicates / max(1, len(frame)))), 4)
            report = {"rows": len(frame), "columns": len(frame.columns), "null_cells": nulls, "duplicate_rows": duplicates, "quality_score": score}
            await repo.update(dataset.id, {"quality_score": score, "profile_json": {**(dataset.profile_json or {}), "quality": report}})
            result = {"status": "completed", "quality": report}
        elif self.name == "cleaning":
            options = context.get("cleaning_options", {})
            if not isinstance(options, dict) or set(options) - {"trim_strings", "drop_duplicates", "drop_all_null_rows"}:
                raise ValidationError("Unsupported cleaning options")
            output = frame.copy()
            if options.get("trim_strings"):
                for col in output.select_dtypes(include=["object", "string"]).columns:
                    output[col] = output[col].map(lambda v: v.strip() if isinstance(v, str) else v)
            before = len(output)
            if options.get("drop_duplicates"):
                output = output.drop_duplicates()
            if options.get("drop_all_null_rows"):
                output = output.dropna(how="all")
            result = {"status": "completed", "rows_before": before, "rows_after": len(output), "rows_removed": before-len(output)}
            frame = output
        elif self.name == "features":
            plan = context.get("transformation_plan")
            if not isinstance(plan, dict):
                raise ValidationError("A declarative transformation_plan is required")
            frame = apply_transformation_plan(frame, plan)
            result = {"status": "completed", "plan": plan}
        elif self.name == "ml":
            target = context.get("target_column")
            if not isinstance(target, str) or target not in frame.columns:
                return {"agent": self.name, "status": "needs_configuration", "required_input": "target_column", "available_columns": list(frame.columns)}
            return await self._baseline(frame, target)
        else:
            raise ValidationError("Unsupported deterministic stage", {"agent": self.name})
        if self.name in {"cleaning", "features"}:
            key = f"silver/{dataset.project_id}/{dataset.id}-{self.name}.csv"
            data = frame.to_csv(index=False).encode()
            digest = hashlib.sha256(data).hexdigest()
            await self.store_artifact(key, data, "text/csv")
            output_name = f"{dataset.name}-{self.name}"
            existing = await self.db_repo.execute(
                select(Dataset).where(Dataset.project_id == dataset.project_id, Dataset.name == output_name)
            )
            target = existing.scalar_one_or_none()
            values = {
                "silver_path": key,
                "source_type": "transformed",
                "schema_json": {str(col): str(dtype) for col, dtype in frame.dtypes.items()},
                "profile_json": {"source_dataset_id": dataset.id, "stage": self.name, "sha256": digest},
                "row_count": len(frame),
                "column_count": len(frame.columns),
                "size_bytes": len(data),
                "version": dataset.version + 1,
            }
            if target is None:
                target = await DatasetRepository(self.db_repo).create(
                    Dataset(project_id=dataset.project_id, name=output_name, **values)
                )
            else:
                target = await DatasetRepository(self.db_repo).update(target.id, values)
            if target is None:
                raise ValidationError("Transformed dataset metadata could not be persisted")
            lineage_repo = LineageRepository(self.db_repo)
            edge_result = await self.db_repo.execute(select(Lineage).where(
                Lineage.source_dataset_id == dataset.id, Lineage.target_dataset_id == target.id
            ))
            if edge_result.scalar_one_or_none() is None:
                await lineage_repo.create(Lineage(
                    source_dataset_id=dataset.id,
                    target_dataset_id=target.id,
                    transformation_type=self.name,
                    agent_id=self.name,
                    sql_code="Validated deterministic transformation",
                    config_json={"sha256": digest},
                ))
            result.update({"output_path": key, "output_dataset_id": target.id, "rows": len(frame), "sha256": digest})
        else:
            key = f"reports/{dataset.project_id}/{dataset.id}/{self.name}.json"
            await self.store_artifact(key, json.dumps(result, indent=2).encode(), "application/json")
            result["report_path"] = key
        await self.log_decision(f"{self.name.upper()}_EXECUTED", f"Executed deterministic {self.name} operation", 1.0)
        return {"agent": self.name, "dataset_id": dataset.id, **result}

    async def _baseline(self, frame: pd.DataFrame, target: str) -> dict[str, Any]:
        if len(frame) < 10 or frame[target].isna().any():
            raise ValidationError("Model evaluation needs at least 10 rows and a non-null target")
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, mean_squared_error
        from sklearn.model_selection import train_test_split
        x = pd.get_dummies(frame.drop(columns=[target]), dummy_na=True)
        if x.empty or x.isna().any().any():
            raise ValidationError("Features are empty or contain missing values")
        y = frame[target]
        classification = (
            pd.api.types.is_object_dtype(y)
            or pd.api.types.is_bool_dtype(y)
            or (pd.api.types.is_integer_dtype(y) and y.nunique() <= max(20, int(len(y) * 0.1)))
        )
        if classification and y.nunique() < 2:
            raise ValidationError("Classification requires at least two classes")
        x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=.2, random_state=42)
        model = RandomForestClassifier(n_estimators=100, random_state=42) if classification else RandomForestRegressor(n_estimators=100, random_state=42)
        model.fit(x_train, y_train)
        pred = model.predict(x_test)
        metrics = {"accuracy": float(accuracy_score(y_test, pred)), "f1_weighted": float(f1_score(y_test, pred, average="weighted", zero_division=0))} if classification else {"mae": float(mean_absolute_error(y_test, pred)), "rmse": float(mean_squared_error(y_test, pred) ** .5)}
        return {"agent": self.name, "status": "completed", "task": "classification" if classification else "regression", "target_column": target, "train_rows": len(x_train), "test_rows": len(x_test), "metrics": metrics, "note": "Evaluation only; this endpoint does not persist a model artifact."}
