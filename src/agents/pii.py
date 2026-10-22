"""PII detection and masking recommendation agent."""

import hashlib
import hmac
import io
import json
import re
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import BaseAgent
from src.core.exceptions import AgentError, ValidationError
from src.config import get_settings
from src.core.logging import configure_logging
from src.database.models import Alert, AlertSeverity, Dataset, Lineage
from src.database.repository import AlertRepository, DatasetRepository, LineageRepository

settings = get_settings()
logger = configure_logging(settings.AEGIS_DEBUG)


class PIIDetectionAgent(BaseAgent):
    """Scan sample data for likely PII and recommend masking strategies."""

    PATTERNS = {
        "email": re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"),
        "phone": re.compile(r"^(?:\+?\d[\d\s().-]{7,}\d)$"),
        "ssn": re.compile(r"^\d{3}-\d{2}-\d{4}$"),
        "credit_card": re.compile(r"^(?:\d[ -]*?){13,19}$"),
        "ip_address": re.compile(r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)$"),
        "date_of_birth": re.compile(r"^\d{4}-\d{2}-\d{2}$|^\d{1,2}/\d{1,2}/\d{2,4}$"),
    }
    NAME_HINTS = {
        "email": "email",
        "phone": "phone",
        "mobile": "phone",
        "ssn": "ssn",
        "dob": "date_of_birth",
        "birth": "date_of_birth",
        "address": "address",
        "name": "name",
        "credit": "credit_card",
        "card": "credit_card",
    }

    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Scan a CSV sample for PII."""

        try:
            dataset_id = context.get("dataset_id")
            artifact_path = context.get("data_sample_path")
            if not isinstance(dataset_id, str) or not isinstance(artifact_path, str):
                raise ValidationError("dataset_id and data_sample_path are required")
            source_dataset = None
            if isinstance(self.db_repo, AsyncSession):
                source_dataset = await DatasetRepository(self.db_repo).get_by_id(dataset_id)
                if source_dataset is None or artifact_path not in {
                    source_dataset.bronze_path, source_dataset.silver_path, source_dataset.gold_path
                }:
                    raise ValidationError("Dataset artifact is not accessible")
            raw_data = await self.storage.read(artifact_path)
            if len(raw_data) > 50 * 1024 * 1024:
                raise ValidationError("PII scan input exceeds the 50 MiB scan limit.")
            df = pd.read_csv(io.BytesIO(raw_data))
            report_columns = []
            for column in df.columns:
                pii_type, confidence = await self._score_column(column, df[column])
                if confidence > 0.7:
                    strategy = await self._recommend_strategy(pii_type)
                    report_columns.append(
                        {
                            "name": column,
                            "pii_type": pii_type,
                            "confidence": confidence,
                            "masking_strategy": strategy,
                            "sample_masked": self._mask_value(str(df[column].dropna().astype(str).head(1).iloc[0]), strategy)
                            if not df[column].dropna().empty
                            else "",
                        }
                    )
            report = {
                "dataset_id": context["dataset_id"],
                "rows_scanned": int(len(df)),
                "columns_scanned": int(len(df.columns)),
                "scan_coverage": "full_dataset",
                "columns": report_columns,
            }
            key = f"pii-reports/{context['dataset_id']}.json"
            await self.store_artifact(key, json.dumps(report, indent=2).encode(), "application/json")
            masked_output_path = None
            masked_dataset = None
            if context.get("apply_masking") is True:
                masked = df.copy(deep=True)
                for item in report_columns:
                    column = item["name"]
                    strategy = item["masking_strategy"]
                    masked[column] = masked[column].map(
                        lambda value: value if pd.isna(value) else self._mask_value(str(value), strategy)
                    )
                if source_dataset is None or not isinstance(self.db_repo, AsyncSession):
                    raise ValidationError("Database-backed dataset metadata is required to publish a masked dataset")
                masked_bytes = masked.to_csv(index=False).encode("utf-8")
                masked_output_path = f"masked/{source_dataset.project_id}/{uuid4().hex}.csv"
                await self.store_artifact(masked_output_path, masked_bytes, "text/csv")
                output_schema = {str(column): str(dtype) for column, dtype in masked.dtypes.items()}
                pii_columns = {item["name"]: item["pii_type"] for item in report_columns}
                masked_profile = {
                    "masking_applied": bool(report_columns),
                    "pii_columns": pii_columns,
                    "source_sha256": hashlib.sha256(raw_data).hexdigest(),
                    "output_sha256": hashlib.sha256(masked_bytes).hexdigest(),
                    "row_count": int(len(masked)),
                    "column_count": int(len(masked.columns)),
                }
                masked_dataset = await DatasetRepository(self.db_repo).create(Dataset(
                    project_id=source_dataset.project_id,
                    name=f"{source_dataset.name}-masked-{uuid4().hex[:8]}",
                    source_type="transformed",
                    silver_path=masked_output_path,
                    schema_json=output_schema,
                    profile_json=masked_profile,
                    row_count=len(masked),
                    column_count=len(masked.columns),
                    size_bytes=len(masked_bytes),
                    quality_score=source_dataset.quality_score,
                    version=source_dataset.version + 1,
                ))
                await LineageRepository(self.db_repo).create(Lineage(
                    source_dataset_id=source_dataset.id,
                    target_dataset_id=masked_dataset.id,
                    transformation_type="pii_masking",
                    agent_id=self.name,
                    config_json={"pii_columns": pii_columns, "source_sha256": masked_profile["source_sha256"]},
                ))
            if report_columns and isinstance(self.db_repo, AsyncSession):
                await AlertRepository(self.db_repo).create(
                    Alert(
                        metric_name="pii_detected_without_policy",
                        threshold=0.7,
                        actual_value=max(column["confidence"] for column in report_columns),
                        severity=AlertSeverity.HIGH,
                        message=f"PII detected in columns: {', '.join(column['name'] for column in report_columns)}",
                    )
                )
            avg_confidence = (
                sum(float(column["confidence"]) for column in report_columns) / len(report_columns) if report_columns else 1.0
            )
            await self.log_decision("PII_SCAN_COMPLETE", f"Detected {len(report_columns)} PII columns", avg_confidence)
            return {
                "pii_detected": bool(report_columns),
                "columns_flagged": len(report_columns),
                "report_path": key,
                "masking_recommendations": report_columns,
                "rows_scanned": int(len(df)),
                "scan_coverage": "full_dataset",
                "masked_output_path": masked_output_path,
                "masked_dataset_id": masked_dataset.id if masked_dataset is not None else None,
                "masking_applied": bool(report_columns) and masked_output_path is not None,
            }
        except ValidationError:
            raise
        except AgentError:
            raise
        except Exception as exc:
            logger.error("pii_agent_failed", error=str(exc))
            raise AgentError("Unable to complete PII scan.") from exc

    async def _score_column(self, column: str, series: pd.Series) -> tuple[str, float]:
        """Score a column using name heuristics, regexes, spaCy, and optional LLM fallback."""

        lowered = column.lower()
        for hint, pii_type in self.NAME_HINTS.items():
            if hint in lowered:
                return pii_type, 0.92
        values = series.dropna().astype(str).tolist()
        if not values:
            return "unknown", 0.0
        best_type = "unknown"
        best_score = 0.0
        for pii_type, pattern in self.PATTERNS.items():
            matches = sum(1 for value in values if pattern.fullmatch(value.strip()))
            score = matches / len(values)
            if score > best_score:
                best_type = pii_type
                best_score = score
        if best_score > 0.7:
            return best_type, min(0.98, best_score)
        ner_score = self._spacy_name_score(values[:50])
        if ner_score > best_score:
            return "name", ner_score
        try:
            prompt = (
                "Does this column contain PII? Return JSON with keys pii_type and confidence. "
                "Types: name, address, email, phone, SSN, credit_card, date_of_birth, medical_record, financial_account. "
                f"Column: {column}. Sample values are redacted count={len(values)}."
            )
            response = json.loads(await self.llm.generate(prompt, expect_json=True))
            return str(response.get("pii_type", "unknown")), float(response.get("confidence", 0.0))
        except Exception:
            return best_type, best_score

    def _spacy_name_score(self, values: list[str]) -> float:
        """Use spaCy for PERSON/ORG/GPE detection when installed and model is available."""

        try:
            import spacy

            nlp = spacy.load("en_core_web_sm")
        except Exception:
            return 0.0
        matches = 0
        for value in values:
            doc = nlp(value)
            if any(entity.label_ in {"PERSON", "GPE", "ORG"} for entity in doc.ents):
                matches += 1
        return matches / len(values)

    async def _recommend_strategy(self, pii_type: str) -> str:
        """Recommend a masking strategy for a PII type."""

        defaults = {
            "email": "hash",
            "phone": "mask_last_4",
            "ssn": "mask_last_4",
            "credit_card": "mask_last_4",
            "date_of_birth": "redact",
            "name": "tokenize",
            "address": "redact",
        }
        try:
            response = json.loads(
                await self.llm.generate(
                    f"Recommend one masking strategy for pii_type={pii_type}. Return JSON with key strategy.",
                    expect_json=True,
                )
            )
            strategy = str(response.get("strategy", ""))
            return strategy if strategy in {"hash", "mask_last_4", "redact", "tokenize"} else defaults.get(pii_type, "redact")
        except Exception:
            return defaults.get(pii_type, "redact")

    def _mask_value(self, value: str, strategy: str) -> str:
        """Mask one sample value without leaking original PII."""

        if strategy == "mask_last_4":
            return "*" * max(len(value) - 4, 0) + value[-4:]
        if strategy in {"hash", "tokenize"}:
            digest = hmac.new(
                settings.AEGIS_SECRET_KEY.encode("utf-8"),
                value.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()[:20]
            return ("hash:" if strategy == "hash" else "token:") + digest
        return "<redacted>"
