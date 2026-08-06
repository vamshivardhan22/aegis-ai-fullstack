"""Data transformation agent."""

import io
import json
import re
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import BaseAgent
from src.config import get_settings
from src.core.exceptions import ValidationError
from src.core.logging import configure_logging
from src.database.models import Dataset, Lineage
from src.database.repository import DatasetRepository, LineageRepository

logger = configure_logging(get_settings().AEGIS_DEBUG)


class TransformAgent(BaseAgent):
    """Generate, validate, execute, and lineage-track pandas transformations."""

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Transform a source CSV into a silver dataset."""

        try:
            df = pd.read_csv(io.BytesIO(await self.storage.read(context["source_data_path"])))
            schema = self._schema_for_prompt(df)
            generated = await self._generate_transformation(context, schema)
            code = generated["code"]
            self._validate_code(code)
            namespace: dict[str, Any] = {"pd": pd, "np": np, "df": df, "result": None}
            exec(code, {"__builtins__": {"len": len, "range": range, "min": min, "max": max, "sum": sum}}, namespace)
            result = namespace.get("result")
            if not isinstance(result, pd.DataFrame):
                raise ValidationError("Transformation code must assign a pandas DataFrame to result")
            key = f"silver/{context['output_name']}.csv"
            await self.store_artifact(key, result.to_csv(index=False).encode(), "text/csv")
            dataset_id = ""
            lineage_id = ""
            if isinstance(self.db_repo, AsyncSession):
                datasets = DatasetRepository(self.db_repo)
                lineage = LineageRepository(self.db_repo)
                source = await datasets.get_by_id(context["source_dataset_id"])
                project_id = getattr(source, "project_id", context.get("project_id"))
                if not project_id:
                    raise ValidationError("Source dataset or project_id is required to create transformed dataset")
                target = await datasets.create(
                    Dataset(
                        project_id=project_id,
                        name=context["output_name"],
                        source_type="transformed",
                        silver_path=key,
                        schema_json=self._schema_json(result),
                        row_count=len(result),
                        column_count=len(result.columns),
                    )
                )
                edge = await lineage.create(
                    Lineage(
                        source_dataset_id=context["source_dataset_id"],
                        target_dataset_id=target.id,
                        transformation_type="pandas",
                        agent_id=self.name,
                        sql_code=generated.get("explanation"),
                        config_json={
                            "request": context["transformation_request"],
                            "output_columns": generated.get("output_columns", list(result.columns)),
                        },
                    )
                )
                dataset_id = target.id
                lineage_id = edge.id
            await self.log_decision("DATA_TRANSFORMED", str(generated.get("explanation", "Data transformed")), 0.75)
            return {
                "output_dataset_id": dataset_id,
                "output_path": key,
                "row_count": len(result),
                "column_count": len(result.columns),
                "transformation_code": code,
                "lineage_id": lineage_id,
            }
        except Exception as exc:
            logger.error("transform_agent_failed", error=str(exc))
            return {"transform_failed": True, "error": "Unable to execute requested transformation."}

    async def _generate_transformation(self, context: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
        """Ask the LLM for pandas code or use a deterministic fallback."""

        prompt = (
            "Given a pandas DataFrame named df with this schema and sample values, return JSON with keys "
            f"code, explanation, output_columns. Schema: {schema}. Request: {context['transformation_request']}. "
            "The code must assign a pandas DataFrame to result."
        )
        try:
            return json.loads(await self.llm.generate(prompt, expect_json=True))
        except Exception as exc:
            logger.warning("transform_llm_fallback", agent=self.name, error=str(exc))
            request = context["transformation_request"].lower()
            if "groupby" in request or "group by" in request:
                group_match = re.search(r"(?:groupby|group by)\s+([a-zA-Z_][\w]*)", request)
                sum_match = re.search(r"sum\s+([a-zA-Z_][\w]*)", request)
                group_col = group_match.group(1) if group_match else "category"
                sum_col = sum_match.group(1) if sum_match else "amount"
                return {
                    "code": f"result = df.groupby('{group_col}', as_index=False)['{sum_col}'].sum()",
                    "explanation": f"Grouped rows by {group_col} and summed {sum_col}.",
                    "output_columns": [group_col, sum_col],
                }
            return {"code": "result = df.copy()", "explanation": "Copied source data unchanged.", "output_columns": list(schema)}

    def _validate_code(self, code: str) -> None:
        """Reject unsafe generated Python before execution."""

        forbidden = ["import os", "import sys", "exec", "eval", "__import__", "open(", "subprocess"]
        lowered = code.lower()
        if any(token in lowered for token in forbidden):
            raise ValidationError("Unsafe transformation code rejected", {"forbidden": forbidden})

    def _schema_for_prompt(self, df: pd.DataFrame) -> dict[str, Any]:
        """Return compact schema and samples for prompting."""

        return {
            column: {"dtype": str(df[column].dtype), "samples": df[column].head(3).astype(str).tolist()}
            for column in df.columns
        }

    def _schema_json(self, df: pd.DataFrame) -> dict[str, str]:
        """Return JSON-serializable pandas dtypes."""

        return {column: str(dtype) for column, dtype in df.dtypes.items()}
