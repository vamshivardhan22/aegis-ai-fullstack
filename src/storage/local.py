"""Local filesystem storage adapter."""

import asyncio
from pathlib import Path

from src.config import get_settings
from src.core.exceptions import StorageError
from src.storage.base import StorageAdapter


class LocalStorageAdapter(StorageAdapter):
    """Store objects under a local filesystem directory."""

    def __init__(self, base_path: str | None = None) -> None:
        """Initialize the adapter and ensure the base directory exists."""

        settings = get_settings()
        self.base_path = Path(base_path or settings.AEGIS_LOCAL_STORAGE_PATH).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        """Resolve and validate a storage key under the base path."""

        target = (self.base_path / key.lstrip("/")).resolve()
        if not str(target).startswith(str(self.base_path)):
            raise StorageError("Storage key escapes base path", {"key": key})
        return target

    async def write(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Write bytes to a local file."""

        try:
            path = self._resolve(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(path.write_bytes, data)
            return key.lstrip("/")
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError("Failed to write local object", {"key": key, "error": str(exc)}) from exc

    async def read(self, key: str) -> bytes:
        """Read bytes from a local file."""

        try:
            return await asyncio.to_thread(self._resolve(key).read_bytes)
        except Exception as exc:
            raise StorageError("Failed to read local object", {"key": key, "error": str(exc)}) from exc

    async def delete(self, key: str) -> bool:
        """Delete a local file if present."""

        try:
            path = self._resolve(key)
            if not path.exists():
                return False
            await asyncio.to_thread(path.unlink)
            return True
        except Exception as exc:
            raise StorageError("Failed to delete local object", {"key": key, "error": str(exc)}) from exc

    async def exists(self, key: str) -> bool:
        """Return True if a local file exists."""

        try:
            return await asyncio.to_thread(self._resolve(key).exists)
        except Exception as exc:
            raise StorageError("Failed to check local object", {"key": key, "error": str(exc)}) from exc

    async def list_keys(self, prefix: str = "") -> list[str]:
        """List local file keys with an optional prefix."""

        try:
            root = self._resolve(prefix) if prefix else self.base_path
            if not root.exists():
                return []
            files = await asyncio.to_thread(lambda: [p for p in root.rglob("*") if p.is_file()])
            return sorted(str(path.relative_to(self.base_path)).replace("\\", "/") for path in files)
        except Exception as exc:
            raise StorageError("Failed to list local objects", {"prefix": prefix, "error": str(exc)}) from exc

    async def get_url(self, key: str) -> str:
        """Return the absolute filesystem path for a key."""

        try:
            return str(self._resolve(key))
        except Exception as exc:
            raise StorageError("Failed to resolve local object URL", {"key": key, "error": str(exc)}) from exc
