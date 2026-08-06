"""Storage adapter contract."""

from abc import ABC, abstractmethod


class StorageAdapter(ABC):
    """Abstract async object storage adapter."""

    @abstractmethod
    async def write(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Write bytes to storage and return the normalized key."""

    @abstractmethod
    async def read(self, key: str) -> bytes:
        """Read bytes from storage."""

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Delete a stored object if it exists."""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Return True if a key exists."""

    @abstractmethod
    async def list_keys(self, prefix: str = "") -> list[str]:
        """List keys with an optional prefix."""

    @abstractmethod
    async def get_url(self, key: str) -> str:
        """Return a readable URL or path for a key."""
