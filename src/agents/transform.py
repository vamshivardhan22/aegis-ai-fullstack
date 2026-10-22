"""Data transformation agent using validated declarative plans, never executable model code."""
import hashlib
import io
import json
import re
from uuid import uuid4
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import BaseAgent
from src.agents.safe_transform import apply_transformation_plan
from src.workflows.csv_pipeline import _detect_pii, _profile
from src.config import get_settings
from src.core.exceptions import ValidationError
from src.core.logging import configure_logging
from src.database.models import Dataset, Lineage
from src.database.repository import DatasetRepository, LineageRepository

logger = configure_logging(get_settings().AEGIS_DEBUG)


class TransformAgent(BaseAgent):
    """Generate a constrained JSON plan, execute allow-listed operations, and record lineage."""

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Transform a source CSV into a silver dataset."""
        try:
            source_bytes = await self.storage.read(context["source_data_path"])
            df = pd.read_csv(io.BytesIO(source_bytes))
            source = None
            if isinstance(self.db_repo, AsyncSession):
                source = await DatasetRepository(self.db_repo).get_by_id(context["source_dataset_id"])
                if source is None:
                    raise ValidationError("Source dataset was not found")
                pii_columns = _detect_pii(df)
                if pii_columns and not (source.profile_json or {}).get("masking_applied"):
                    raise ValidationError(
                        "Sensitive columns must pass through the governed masking and approval workflow before standalone transformation",
                        {"columns": list(pii_columns)},
                    )
            schema = self._schema_for_prompt(df)
            generated = await self._generate_transformation(context, schema)
            plan = generated["plan"]
            result = apply_transformation_plan(df, plan)
            if result.empty:
                raise ValidationError("Transformation produced zero rows")
            output_name = context.get("output_name")
            if not isinstance(output_name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", output_name) or ".." in output_name:
                raise ValidationError("output_name must be a safe 1-100 character identifier")
            output_bytes = result.to_csv(index=False).encode("utf-8")
            output_profile = _profile(result, output_bytes)
            if output_profile["non_finite_cells"]:
                raise ValidationError("Transformation produced non-finite numeric values")
            output_sha256 = hashlib.sha256(output_bytes).hexdigest()
            output_profile["source_sha256"] = hashlib.sha256(source_bytes).hexdigest()
            output_profile["output_sha256"] = output_sha256
            key = "silver/" + (source.project_id if source is not None else str(context.get("project_id", "unscoped"))) + "/" + uuid4().hex + ".csv"
            await self.store_artifact(key, output_bytes, "text/csv")
            dataset_id = ""
            lineage_id = ""
            if isinstance(self.db_repo, AsyncSession):
                datasets = DatasetRepository(self.db_repo)
                lineage = LineageRepository(self.db_repo)
                if source is None:
                    raise ValidationError("Source dataset was not found")
                project_id = getattr(source, "project_id", context.get("project_id"))
                if not project_id:
                    raise ValidationError("Source dataset or project_id is required to create transformed dataset")
                target = await datasets.create(Dataset(
                    project_id=project_id,
                    name=context["output_name"],
                    source_type="transformed",
                    silver_path=key,
                    schema_json=self._schema_json(result),
                    profile_json={
                        **output_profile,
                        "masking_applied": bool((source.profile_json or {}).get("masking_applied")),
                        "pii_columns": (source.profile_json or {}).get("pii_columns", {}),
                    },
                    row_count=len(result),
                    column_count=len(result.columns),
                    size_bytes=len(output_bytes),
                    quality_score=output_profile["quality_score"],
                    version=source.version + 1,
                ))
                edge = await lineage.create(Lineage(
                    source_dataset_id=context["source_dataset_id"],
                    target_dataset_id=target.id,
                    transformation_type="declarative_plan",
                    agent_id=self.name,
                    sql_code=generated.get("explanation"),
                    config_json={"plan": plan, "output_columns": list(result.columns)},
                ))
                dataset_id = target.id
                lineage_id = edge.id
            await self.log_decision("DATA_TRANSFORMED", str(generated.get("explanation", "Data transformed")), 0.75)
            return {
                "output_dataset_id": dataset_id,
                "output_path": key,
                "row_count": len(result),
                "column_count": len(result.columns),
                "transformation_plan": json.dumps(plan, sort_keys=True),
                "lineage_id": lineage_id,
            }
        except ValidationError as exc:
            logger.warning("transform_validation_failed", error=exc.message)
            raise
        except Exception as exc:
            logger.error("transform_agent_failed", error=str(exc))
            return {"transform_failed": True, "error": "Unable to execute requested transformation."}

    async def _generate_transformation(self, context: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        """Use an explicit plan when supplied; otherwise request a constrained plan from the LLM."""
        provided_plan = context.get("transformation_plan")
        if provided_plan is not None:
            if not isinstance(provided_plan, dict):
                raise ValidationError("transformation_plan must be a declarative plan object")
            return {
                "plan": provided_plan,
                "explanation": "Applied caller-supplied declarative transformation plan.",
                "output_columns": list(schema),
            }
        prompt = (
            "Return JSON only with keys plan, explanation, output_columns. "
            "plan must contain an operations list with at most 25 allow-listed steps. "
            "Allowed operations: select_columns(columns), drop_columns(columns), drop_duplicates(subset,keep), "
            "rename_columns(mapping), fillna(columns,value), filter(column,operator,value), "
            "groupby_agg(group_by,aggregations), cast(columns), derive_numeric(name,left,operator,right_column|value), "
            "derive_string(name,column,operation), derive_datetime(name,column,part). "
            "Allowed filters: eq, ne, gt, gte, lt, lte, contains, is_null, not_null. "
            "Allowed aggregations: sum, mean, min, max, count, nunique. "
            "Allowed cast types: string, integer, float, boolean, datetime. "
            "Never return Python, SQL, imports, or executable expressions. "
            f"Schema: {schema}. Request: {context['transformation_request']}."
        )
        try:
            response = json.loads(await self.llm.generate(prompt, expect_json=True))
            if not isinstance(response, dict) or not isinstance(response.get("plan"), dict):
                raise ValidationError("LLM response must contain a declarative plan")
            return response
        except ValidationError:
            raise
        except Exception as exc:
            logger.warning("transform_llm_fallback", agent=self.name, error=str(exc))
            request = context["transformation_request"].lower()
            if "groupby" in request or "group by" in request:
                group_match = re.search(r"(?:groupby|group by)\s+([a-zA-Z_][\w]*)", request)
                sum_match = re.search(r"sum\s+([a-zA-Z_][\w]*)", request)
                group_col = group_match.group(1) if group_match else "category"
                sum_col = sum_match.group(1) if sum_match else "amount"
                if group_col not in schema or sum_col not in schema:
                    raise ValidationError("Fallback transformation refers to missing columns") from exc
                return {
                    "plan": {"operations": [{"op": "groupby_agg", "group_by": [group_col], "aggregations": {sum_col: "sum"}}]},
                    "explanation": f"Grouped rows by {group_col} and summed {sum_col}.",
                    "output_columns": [group_col, sum_col],
                }
            if "drop duplicate" in request or "remove duplicate" in request or "deduplicate" in request:
                return {
                    "plan": {"operations": [{"op": "drop_duplicates"}]},
                    "explanation": "Removed exact duplicate rows using the deterministic fallback.",
                    "output_columns": list(schema),
                }
            if "copy unchanged" in request or "no transformation" in request or "leave unchanged" in request:
                return {
                    "plan": {"operations": []},
                    "explanation": "Copied source data unchanged as explicitly requested.",
                    "output_columns": list(schema),
                }
            raise ValidationError(
                "The LLM planner is unavailable and this request cannot be safely interpreted. "
                "Provide a declarative transformation_plan or configure an LLM provider."
            ) from exc

    def _schema_for_prompt(self, df: pd.DataFrame) -> dict[str, Any]:
        """Return compact schema and samples for prompting."""
        return {column: {"dtype": str(df[column].dtype)} for column in df.columns}

    def _schema_json(self, df: pd.DataFrame) -> dict[str, str]:
        """Return JSON-serializable pandas dtypes."""
        return {column: str(dtype) for column, dtype in df.dtypes.items()}
