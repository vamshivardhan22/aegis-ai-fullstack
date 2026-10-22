"""Data transformation agent using validated declarative plans, never executable model code."""
import io
import json
import re
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import BaseAgent
from src.agents.safe_transform import apply_transformation_plan
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
            if not source_bytes or len(source_bytes) > 50 * 1024 * 1024:
                raise ValidationError("Source CSV is empty or exceeds the 50 MiB transformation limit")
            df = pd.read_csv(io.BytesIO(source_bytes))
            if df.empty or len(df.columns) == 0 or len(df.columns) > 500 or df.columns.duplicated().any():
                raise ValidationError("Source CSV must contain rows and unique columns, with at most 500 columns")
            output_name = str(context.get("output_name", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}", output_name) or ".." in output_name:
                raise ValidationError("output_name must be a safe identifier of at most 100 characters")
            schema = self._schema_for_prompt(df)
            generated = await self._generate_transformation(context, schema)
            plan = generated["plan"]
            result = apply_transformation_plan(df, plan)
            key = f"silver/{context.get('project_id', context['source_dataset_id'])}/{output_name}.csv"
            await self.store_artifact(key, result.to_csv(index=False).encode(), "text/csv")
            dataset_id = ""
            lineage_id = ""
            if isinstance(self.db_repo, AsyncSession):
                datasets = DatasetRepository(self.db_repo)
                lineage = LineageRepository(self.db_repo)
                source = await datasets.get_by_id(context["source_dataset_id"])
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
                    row_count=len(result),
                    column_count=len(result.columns),
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
            return {"transform_failed": True, "error": exc.message}
        except Exception as exc:
            logger.error("transform_agent_failed", error=str(exc))
            return {"transform_failed": True, "error": "Unable to execute requested transformation."}

    async def _generate_transformation(self, context: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        """Ask the LLM for a JSON plan; use a safe no-op fallback if unavailable."""
        prompt = (
            "Return JSON only with keys plan, explanation, output_columns. "
            "plan must contain an operations list with at most 25 allow-listed steps. "
            "Allowed operations: select_columns(columns), drop_columns(columns), rename_columns(mapping), "
            "fillna(columns,value), filter(column,operator,value), groupby_agg(group_by,aggregations), cast(columns). "
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
                    raise ValidationError("Fallback transformation refers to missing columns")
                return {
                    "plan": {"operations": [{"op": "groupby_agg", "group_by": [group_col], "aggregations": {sum_col: "sum"}}]},
                    "explanation": f"Grouped rows by {group_col} and summed {sum_col}.",
                    "output_columns": [group_col, sum_col],
                }
            return {
                "plan": {"operations": []},
                "explanation": "Copied source data unchanged.",
                "output_columns": list(schema),
            }

    def _schema_for_prompt(self, df: pd.DataFrame) -> dict[str, Any]:
        """Return compact schema and samples for prompting."""
        return {
            column: {"dtype": str(df[column].dtype), "samples": df[column].head(3).astype(str).tolist()}
            for column in df.columns
        }

    def _schema_json(self, df: pd.DataFrame) -> dict[str, str]:
        """Return JSON-serializable pandas dtypes."""
        return {column: str(dtype) for column, dtype in df.dtypes.items()}
