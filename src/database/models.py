"""Database models for the Aegis AI infrastructure milestone."""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database.base import Base, TimestampMixin, UUIDMixin


class UserRole(str, enum.Enum):
    """Supported user roles."""

    ADMIN = "admin"
    DATA_ENGINEER = "data_engineer"
    ANALYST = "analyst"
    VIEWER = "viewer"


class PipelineStatus(str, enum.Enum):
    """Pipeline lifecycle states."""

    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    APPROVAL_REQUIRED = "approval_required"


class AgentType(str, enum.Enum):
    """Autonomous agent categories."""

    INGESTION = "ingestion"
    SCHEMA = "schema"
    QUALITY = "quality"
    CLEANING = "cleaning"
    TRANSFORM = "transform"
    FEATURES = "features"
    ML = "ml"
    EXPLAIN = "explain"
    DEPLOY = "deploy"
    MONITOR = "monitor"
    DRIFT = "drift"
    RAG = "rag"


class TaskStatus(str, enum.Enum):
    """Job and task execution states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class ModelStatus(str, enum.Enum):
    """Model registry states."""

    STAGING = "staging"
    PRODUCTION = "production"
    ARCHIVED = "archived"
    FAILED = "failed"


class AlertSeverity(str, enum.Enum):
    """Alert severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class User(Base, UUIDMixin, TimestampMixin):
    """Platform user account."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    org_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    projects: Mapped[list["Project"]] = relationship(back_populates="owner")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="user")


class Project(Base, UUIDMixin, TimestampMixin):
    """A project groups datasets, pipelines, and experiments."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    owner: Mapped["User"] = relationship(back_populates="projects")
    datasets: Mapped[list["Dataset"]] = relationship(back_populates="project")
    pipelines: Mapped[list["Pipeline"]] = relationship(back_populates="project")
    experiments: Mapped[list["Experiment"]] = relationship(back_populates="project")


class Dataset(Base, UUIDMixin, TimestampMixin):
    """Dataset metadata across bronze, silver, and gold layers."""

    __tablename__ = "datasets"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(100), nullable=False)
    bronze_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    silver_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    gold_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    schema_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    profile_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    row_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    column_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(default=False, nullable=False)

    project: Mapped["Project"] = relationship(back_populates="datasets")
    pipelines: Mapped[list["Pipeline"]] = relationship(back_populates="dataset")
    models: Mapped[list["Model"]] = relationship(back_populates="dataset")
    upstream_lineage: Mapped[list["Lineage"]] = relationship(
        back_populates="target_dataset",
        foreign_keys="Lineage.target_dataset_id",
    )
    downstream_lineage: Mapped[list["Lineage"]] = relationship(
        back_populates="source_dataset",
        foreign_keys="Lineage.source_dataset_id",
    )


class Pipeline(Base, UUIDMixin, TimestampMixin):
    """Pipeline execution plan and state."""

    __tablename__ = "pipelines"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[PipelineStatus] = mapped_column(SAEnum(PipelineStatus), nullable=False)
    current_state: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    checkpoint_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="pipelines")
    dataset: Mapped["Dataset"] = relationship(back_populates="pipelines")
    jobs: Mapped[list["Job"]] = relationship(back_populates="pipeline")
    models: Mapped[list["Model"]] = relationship(back_populates="pipeline")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="pipeline")
    metrics: Mapped[list["Metric"]] = relationship(back_populates="pipeline")
    schedules: Mapped[list["Schedule"]] = relationship(back_populates="pipeline")


class Job(Base, UUIDMixin, TimestampMixin):
    """Agent job belonging to a pipeline."""

    __tablename__ = "jobs"

    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id"), nullable=False)
    agent_type: Mapped[AgentType] = mapped_column(SAEnum(AgentType), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(SAEnum(TaskStatus), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    logs_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    pipeline: Mapped["Pipeline"] = relationship(back_populates="jobs")
    tasks: Mapped[list["Task"]] = relationship(back_populates="job")


class Task(Base, UUIDMixin, TimestampMixin):
    """Atomic unit of agent work."""

    __tablename__ = "tasks"

    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    agent_type: Mapped[AgentType] = mapped_column(SAEnum(AgentType), nullable=False)
    input_artifact: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    output_artifact: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    status: Mapped[TaskStatus] = mapped_column(SAEnum(TaskStatus), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    execution_time_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    job: Mapped["Job"] = relationship(back_populates="tasks")


class Model(Base, UUIDMixin, TimestampMixin):
    """Trained model metadata and registry state."""

    __tablename__ = "models"

    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    pipeline_id: Mapped[Optional[str]] = mapped_column(ForeignKey("pipelines.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(255), nullable=False)
    problem_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metrics_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    parameters_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    mlflow_run_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    status: Mapped[ModelStatus] = mapped_column(SAEnum(ModelStatus), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    dataset: Mapped["Dataset"] = relationship(back_populates="models")
    pipeline: Mapped[Optional["Pipeline"]] = relationship(back_populates="models")
    deployments: Mapped[list["Deployment"]] = relationship(back_populates="model")


class Deployment(Base, UUIDMixin, TimestampMixin):
    """Runtime deployment for a model."""

    __tablename__ = "deployments"

    model_id: Mapped[str] = mapped_column(ForeignKey("models.id"), nullable=False)
    endpoint_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    docker_image: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    container_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(100), default="running", nullable=False)
    health_check_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    model: Mapped["Model"] = relationship(back_populates="deployments")
    metrics: Mapped[list["Metric"]] = relationship(back_populates="deployment")


class Experiment(Base, UUIDMixin, TimestampMixin):
    """Experiment tracking metadata."""

    __tablename__ = "experiments"

    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mlflow_experiment_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    parameters_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    metrics_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="experiments")


class Lineage(Base, UUIDMixin, TimestampMixin):
    """Dataset-to-dataset transformation lineage."""

    __tablename__ = "lineage"
    __table_args__ = (Index("ix_lineage_source_target", "source_dataset_id", "target_dataset_id"),)

    source_dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    target_dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    transformation_type: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    sql_code: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    source_dataset: Mapped["Dataset"] = relationship(
        back_populates="downstream_lineage",
        foreign_keys=[source_dataset_id],
    )
    target_dataset: Mapped["Dataset"] = relationship(
        back_populates="upstream_lineage",
        foreign_keys=[target_dataset_id],
    )


class AuditLog(Base, UUIDMixin, TimestampMixin):
    """Immutable audit event for user or system action."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[Optional[str]] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False)
    before_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    after_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    user: Mapped[Optional["User"]] = relationship(back_populates="audit_logs")


class Alert(Base, UUIDMixin, TimestampMixin):
    """Monitoring alert raised by a pipeline or deployment."""

    __tablename__ = "alerts"

    pipeline_id: Mapped[Optional[str]] = mapped_column(ForeignKey("pipelines.id"), nullable=True)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    actual_value: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(SAEnum(AlertSeverity), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    acknowledged: Mapped[bool] = mapped_column(default=False, nullable=False)
    acknowledged_by: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    pipeline: Mapped[Optional["Pipeline"]] = relationship(back_populates="alerts")


class Document(Base, UUIDMixin, TimestampMixin):
    """Knowledge-base document for RAG workflows."""

    __tablename__ = "documents"

    doc_type: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_vector: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)


class Metric(Base, UUIDMixin, TimestampMixin):
    """Observed metric value with optional labels."""

    __tablename__ = "metrics"

    pipeline_id: Mapped[Optional[str]] = mapped_column(ForeignKey("pipelines.id"), nullable=True)
    deployment_id: Mapped[Optional[str]] = mapped_column(ForeignKey("deployments.id"), nullable=True)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    labels_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    pipeline: Mapped[Optional["Pipeline"]] = relationship(back_populates="metrics")
    deployment: Mapped[Optional["Deployment"]] = relationship(back_populates="metrics")


class Schedule(Base, UUIDMixin, TimestampMixin):
    """Cron schedule for a pipeline."""

    __tablename__ = "schedules"

    pipeline_id: Mapped[str] = mapped_column(ForeignKey("pipelines.id"), nullable=False)
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    pipeline: Mapped["Pipeline"] = relationship(back_populates="schedules")
