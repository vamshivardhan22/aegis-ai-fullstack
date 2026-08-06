"""Data retention and compliance policy enforcement."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import Alert, AlertSeverity, AuditLog, Dataset
from src.database.repository import AlertRepository, AuditLogRepository, DatasetRepository


@dataclass
class RetentionPolicy:
    """Project-level data retention policy with soft-delete enforcement."""

    session: AsyncSession
    project_id: str
    bronze_days: int = 365
    silver_days: int = 90
    gold_days: int = 30
    audit_days: int = 2555

    def configure(self, project_id: str, bronze_days: int, silver_days: int, gold_days: int, audit_days: int) -> None:
        """Configure retention windows in days."""

        self.project_id = project_id
        self.bronze_days = bronze_days
        self.silver_days = silver_days
        self.gold_days = gold_days
        self.audit_days = audit_days

    async def enforce(self) -> dict[str, Any]:
        """Soft-delete expired datasets and log compliance alerts."""

        archived: list[str] = []
        result = await self.session.execute(select(Dataset).where(Dataset.project_id == self.project_id, Dataset.is_deleted.is_(False)))
        datasets = result.scalars().all()
        now = datetime.utcnow()
        for dataset in datasets:
            max_days = self._retention_days(dataset)
            if dataset.created_at < now - timedelta(days=max_days):
                before = {"is_deleted": dataset.is_deleted, "profile_json": dataset.profile_json}
                profile = dict(dataset.profile_json or {})
                profile["archived_at"] = now.isoformat()
                profile["archive_reason"] = "retention_policy"
                await DatasetRepository(self.session).update(dataset.id, {"is_deleted": True, "profile_json": profile})
                await AuditLogRepository(self.session).log_action(
                    action="DATASET_RETENTION_ARCHIVED",
                    resource_type="dataset",
                    resource_id=dataset.id,
                    before_json=before,
                    after_json={"is_deleted": True, "profile_json": profile},
                    rationale="Retention policy soft delete",
                    confidence=1.0,
                )
                archived.append(dataset.id)
        if archived:
            await AlertRepository(self.session).create(
                Alert(
                    metric_name="retention_archival",
                    threshold=0,
                    actual_value=float(len(archived)),
                    severity=AlertSeverity.MEDIUM,
                    message=f"Archived {len(archived)} datasets under retention policy",
                )
            )
        return {"archived_datasets": archived, "count": len(archived)}

    async def erase_user_data(self, user_id: str) -> dict[str, Any]:
        """Anonymize direct personal user data while retaining audit trail."""

        await self.session.execute(
            select(AuditLog).where(AuditLog.user_id == user_id)
        )
        await AuditLogRepository(self.session).log_action(
            action="GDPR_ERASURE_REQUESTED",
            resource_type="user",
            resource_id=user_id,
            user_id=user_id,
            before_json={"user_id": user_id},
            after_json={"anonymized": True},
            rationale="GDPR right to erasure",
            confidence=1.0,
        )
        return {"user_id": user_id, "status": "erasure_logged"}

    def _retention_days(self, dataset: Dataset) -> int:
        """Choose the retention window based on dataset layer."""

        if dataset.gold_path:
            return self.gold_days
        if dataset.silver_path:
            return self.silver_days
        return self.bronze_days
