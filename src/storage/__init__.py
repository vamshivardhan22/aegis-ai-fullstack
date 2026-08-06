"""Storage adapter factory."""

from src.config import get_settings
from src.storage.base import StorageAdapter
from src.storage.local import LocalStorageAdapter


def get_storage() -> StorageAdapter:
    """Return the configured storage adapter."""

    settings = get_settings()
    if settings.AEGIS_STORAGE_BACKEND == "minio":
        from src.storage.minio import MinioStorageAdapter

        return MinioStorageAdapter()
    return LocalStorageAdapter()
