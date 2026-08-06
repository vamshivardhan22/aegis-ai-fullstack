"""Domain exceptions used across Aegis AI."""

from typing import Any


class AegisError(Exception):
    """Base exception carrying an API-safe error code, status, and details."""

    code = "AEGIS_ERROR"
    status_code = 500

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        """Initialize the exception with a message and optional details."""

        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Serialize the exception into a JSON-compatible payload."""

        return {"code": self.code, "message": self.message, "details": self.details}


class AgentError(AegisError):
    """Raised when an autonomous agent fails."""

    code = "AGENT_ERROR"
    status_code = 500


class ValidationError(AegisError):
    """Raised for domain validation failures."""

    code = "VALIDATION_ERROR"
    status_code = 422


class StorageError(AegisError):
    """Raised for storage backend failures."""

    code = "STORAGE_ERROR"
    status_code = 500


class DatabaseError(AegisError):
    """Raised for database failures."""

    code = "DATABASE_ERROR"
    status_code = 500


class LLMError(AegisError):
    """Raised when the LLM backend fails or returns invalid data."""

    code = "LLM_ERROR"
    status_code = 502


class PipelineError(AegisError):
    """Raised for pipeline orchestration failures."""

    code = "PIPELINE_ERROR"
    status_code = 500


class HumanApprovalRequired(AegisError):
    """Raised when a task must pause for human approval."""

    code = "HUMAN_APPROVAL_REQUIRED"
    status_code = 202
