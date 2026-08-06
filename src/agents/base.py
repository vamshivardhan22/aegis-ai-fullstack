"""Base agent primitives for Aegis AI."""

from abc import ABC, abstractmethod
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.core.exceptions import AgentError
from src.core.logging import configure_logging
from src.database.repository import AuditLogRepository
from src.storage.base import StorageAdapter

logger = configure_logging(get_settings().AEGIS_DEBUG)


class BaseAgent(ABC):
    """Common lifecycle and audit behavior for specialized agents."""

    def __init__(self, name: str, llm_client: Any, db_repo: Any, storage_adapter: StorageAdapter) -> None:
        """Initialize shared agent dependencies."""

        self.name = name
        self.llm = llm_client
        self.db_repo = db_repo
        self.storage = storage_adapter
        self.current_user_id: str | None = None
        self.audit_repo = (
            AuditLogRepository(db_repo)
            if isinstance(db_repo, AsyncSession)
            else db_repo
            if hasattr(db_repo, "log_action")
            else None
        )

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run the agent with a JSON-serializable context."""

    async def store_artifact(self, key: str, data: bytes, content_type: str) -> str:
        """Store an artifact and return its storage key."""

        return await self.storage.write(key, data, content_type)

    async def log_decision(self, action: str, rationale: str, confidence: float) -> None:
        """Write a decision audit log entry when an audit repository is available."""

        logger.info("agent_decision", agent=self.name, action=action, confidence=confidence)
        if self.audit_repo is None:
            return
        await self.audit_repo.log_action(
            action=action,
            resource_type="agent",
            resource_id=self.name,
            user_id=self.current_user_id,
            before_json={},
            rationale=rationale,
            confidence=confidence,
            after_json={"agent": self.name},
        )

    def handle_error(self, error: Exception, context: dict[str, Any]) -> dict[str, Any]:
        """Log an agent error and raise an API-safe AgentError."""

        logger.error("agent_error", agent=self.name, error=str(error), context_keys=list(context.keys()))
        raise AgentError(f"{self.name} failed", {"error": str(error)}) from error
