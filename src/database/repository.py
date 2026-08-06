"""Repository abstractions for Aegis AI models."""

from abc import ABC
from typing import Any, Generic, Optional, Sequence, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import (
    Alert,
    AuditLog,
    Dataset,
    Deployment,
    Document,
    Job,
    Lineage,
    Metric,
    Model,
    Pipeline,
    PipelineStatus,
    Project,
    Task,
    User,
)

ModelType = TypeVar("ModelType")


class BaseRepository(ABC, Generic[ModelType]):
    """Generic async CRUD repository."""

    def __init__(self, session: AsyncSession, model: type[ModelType]) -> None:
        """Initialize the repository for a model class."""

        self.session = session
        self.model = model

    async def get_by_id(self, id: str) -> Optional[ModelType]:
        """Return one model by primary key."""

        return await self.session.get(self.model, id)

    async def list_all(self, limit: int = 100, offset: int = 0) -> Sequence[ModelType]:
        """Return all models with pagination."""

        result = await self.session.execute(select(self.model).limit(limit).offset(offset))
        return result.scalars().all()

    async def create(self, obj: ModelType) -> ModelType:
        """Persist a new model object."""

        self.session.add(obj)
        await self.session.commit()
        await self.session.refresh(obj)
        return obj

    async def update(self, id: str, data: dict[str, Any]) -> Optional[ModelType]:
        """Update a model by primary key."""

        obj = await self.get_by_id(id)
        if obj is None:
            return None
        for key, value in data.items():
            if hasattr(obj, key):
                setattr(obj, key, value)
        await self.session.commit()
        await self.session.refresh(obj)
        return obj

    async def delete(self, id: str) -> bool:
        """Delete a model by primary key."""

        obj = await self.get_by_id(id)
        if obj is None:
            return False
        await self.session.delete(obj)
        await self.session.commit()
        return True


class UserRepository(BaseRepository[User]):
    """Repository for users."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the user repository."""

        super().__init__(session, User)

    async def get_by_email(self, email: str) -> Optional[User]:
        """Return a user by email."""

        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()


class ProjectRepository(BaseRepository[Project]):
    """Repository for projects."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the project repository."""

        super().__init__(session, Project)

    async def list_by_owner(self, owner_id: str) -> Sequence[Project]:
        """Return projects owned by a user."""

        result = await self.session.execute(select(Project).where(Project.owner_id == owner_id))
        return result.scalars().all()


class DatasetRepository(BaseRepository[Dataset]):
    """Repository for datasets."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the dataset repository."""

        super().__init__(session, Dataset)

    async def list_by_project(self, project_id: str) -> Sequence[Dataset]:
        """Return datasets belonging to a project."""

        result = await self.session.execute(select(Dataset).where(Dataset.project_id == project_id))
        return result.scalars().all()

    async def get_latest_version(self, project_id: str, name: str) -> Optional[Dataset]:
        """Return the latest non-deleted dataset version by project and name."""

        result = await self.session.execute(
            select(Dataset)
            .where(Dataset.project_id == project_id, Dataset.name == name, Dataset.is_deleted.is_(False))
            .order_by(Dataset.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class PipelineRepository(BaseRepository[Pipeline]):
    """Repository for pipelines."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the pipeline repository."""

        super().__init__(session, Pipeline)

    async def list_by_project(self, project_id: str) -> Sequence[Pipeline]:
        """Return pipelines belonging to a project."""

        result = await self.session.execute(select(Pipeline).where(Pipeline.project_id == project_id))
        return result.scalars().all()

    async def list_active(self) -> Sequence[Pipeline]:
        """Return pipelines in active execution states."""

        result = await self.session.execute(
            select(Pipeline).where(
                Pipeline.status.in_(
                    [PipelineStatus.PENDING, PipelineStatus.PLANNING, PipelineStatus.RUNNING, PipelineStatus.PAUSED]
                )
            )
        )
        return result.scalars().all()


class JobRepository(BaseRepository[Job]):
    """Repository for jobs."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the job repository."""

        super().__init__(session, Job)

    async def list_by_pipeline(self, pipeline_id: str) -> Sequence[Job]:
        """Return jobs for a pipeline."""

        result = await self.session.execute(select(Job).where(Job.pipeline_id == pipeline_id))
        return result.scalars().all()


class TaskRepository(BaseRepository[Task]):
    """Repository for tasks."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the task repository."""

        super().__init__(session, Task)


class ModelRepository(BaseRepository[Model]):
    """Repository for model registry records."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the model repository."""

        super().__init__(session, Model)

    async def list_active_by_dataset(self, dataset_id: str) -> Sequence[Model]:
        """Return active models trained on a dataset."""

        result = await self.session.execute(select(Model).where(Model.dataset_id == dataset_id, Model.is_active.is_(True)))
        return result.scalars().all()


class DeploymentRepository(BaseRepository[Deployment]):
    """Repository for runtime deployments."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the deployment repository."""

        super().__init__(session, Deployment)


class MetricRepository(BaseRepository[Metric]):
    """Repository for observed metrics."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the metric repository."""

        super().__init__(session, Metric)


class AlertRepository(BaseRepository[Alert]):
    """Repository for monitoring alerts."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the alert repository."""

        super().__init__(session, Alert)


class DocumentRepository(BaseRepository[Document]):
    """Repository for RAG knowledge-base documents."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the document repository."""

        super().__init__(session, Document)

    async def search_content(self, query: str, limit: int = 10) -> Sequence[Document]:
        """Return documents whose title or content contains a query fragment."""

        pattern = f"%{query}%"
        result = await self.session.execute(
            select(Document).where((Document.content.ilike(pattern)) | (Document.title.ilike(pattern))).limit(limit)
        )
        return result.scalars().all()


class AuditLogRepository(BaseRepository[AuditLog]):
    """Repository for audit logs."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the audit log repository."""

        super().__init__(session, AuditLog)

    async def log_action(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        user_id: Optional[str] = None,
        before_json: Optional[dict[str, Any]] = None,
        after_json: Optional[dict[str, Any]] = None,
        rationale: Optional[str] = None,
        confidence: Optional[float] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        """Create an audit log entry for an action."""

        return await self.create(
            AuditLog(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                before_json=before_json,
                after_json=after_json,
                rationale=rationale,
                confidence=confidence,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

    async def list_by_resource(self, resource_type: str, resource_id: str, limit: int = 100) -> Sequence[AuditLog]:
        """Return audit logs for a resource."""

        result = await self.session.execute(
            select(AuditLog)
            .where(AuditLog.resource_type == resource_type, AuditLog.resource_id == resource_id)
            .order_by(AuditLog.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()


class LineageRepository(BaseRepository[Lineage]):
    """Repository for dataset lineage edges."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the lineage repository."""

        super().__init__(session, Lineage)

    async def get_upstream(self, dataset_id: str) -> Sequence[Lineage]:
        """Return lineage edges feeding a target dataset."""

        result = await self.session.execute(select(Lineage).where(Lineage.target_dataset_id == dataset_id))
        return result.scalars().all()

    async def get_downstream(self, dataset_id: str) -> Sequence[Lineage]:
        """Return lineage edges emitted by a source dataset."""

        result = await self.session.execute(select(Lineage).where(Lineage.source_dataset_id == dataset_id))
        return result.scalars().all()
