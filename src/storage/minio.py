"""MinIO object storage adapter."""

import asyncio
from datetime import timedelta
from io import BytesIO

from minio import Minio
from minio.error import S3Error

from src.config import get_settings
from src.core.exceptions import StorageError
from src.storage.base import StorageAdapter


class MinioStorageAdapter(StorageAdapter):
    """Store objects in a MinIO bucket."""

    def __init__(self) -> None:
        """Initialize the MinIO client and ensure the configured bucket exists."""

        settings = get_settings()
        self.bucket = settings.AEGIS_MINIO_BUCKET
        self.client = Minio(
            settings.AEGIS_MINIO_ENDPOINT,
            access_key=settings.AEGIS_MINIO_ACCESS_KEY,
            secret_key=settings.AEGIS_MINIO_SECRET_KEY,
            secure=settings.AEGIS_MINIO_SECURE,
        )
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except S3Error as exc:
            raise StorageError("Failed to initialize MinIO bucket", {"bucket": self.bucket, "error": str(exc)}) from exc

    async def write(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Write bytes to MinIO."""

        try:
            await asyncio.to_thread(
                self.client.put_object,
                self.bucket,
                key,
                BytesIO(data),
                len(data),
                content_type=content_type,
            )
            return key
        except Exception as exc:
            raise StorageError("Failed to write MinIO object", {"key": key, "error": str(exc)}) from exc

    async def read(self, key: str) -> bytes:
        """Read bytes from MinIO."""

        response = None
        try:
            response = await asyncio.to_thread(self.client.get_object, self.bucket, key)
            return await asyncio.to_thread(response.read)
        except Exception as exc:
            raise StorageError("Failed to read MinIO object", {"key": key, "error": str(exc)}) from exc
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    async def delete(self, key: str) -> bool:
        """Delete an object from MinIO."""

        try:
            await asyncio.to_thread(self.client.remove_object, self.bucket, key)
            return True
        except Exception as exc:
            raise StorageError("Failed to delete MinIO object", {"key": key, "error": str(exc)}) from exc

    async def exists(self, key: str) -> bool:
        """Return True if an object exists in MinIO."""

        try:
            await asyncio.to_thread(self.client.stat_object, self.bucket, key)
            return True
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NoSuchBucket"}:
                return False
            raise StorageError("Failed to stat MinIO object", {"key": key, "error": str(exc)}) from exc

    async def list_keys(self, prefix: str = "") -> list[str]:
        """List MinIO object keys with an optional prefix."""

        try:
            objects = await asyncio.to_thread(
                lambda: list(self.client.list_objects(self.bucket, prefix=prefix, recursive=True))
            )
            return sorted(obj.object_name for obj in objects if obj.object_name is not None)
        except Exception as exc:
            raise StorageError("Failed to list MinIO objects", {"prefix": prefix, "error": str(exc)}) from exc

    async def get_url(self, key: str) -> str:
        """Return a seven-day presigned URL for an object."""

        try:
            return await asyncio.to_thread(
                self.client.presigned_get_object,
                self.bucket,
                key,
                expires=timedelta(days=7),
            )
        except Exception as exc:
            raise StorageError("Failed to create MinIO URL", {"key": key, "error": str(exc)}) from exc
