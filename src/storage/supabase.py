"""Supabase Storage adapter for AGIES artifacts."""

from __future__ import annotations

from src.config import get_settings
from src.core.exceptions import StorageError
from src.storage.base import StorageAdapter


class SupabaseStorageAdapter(StorageAdapter):
    """Async-compatible adapter over the Supabase Storage client."""

    def __init__(self) -> None:
        settings = get_settings()
        if not settings.AEGIS_SUPABASE_URL or not settings.AEGIS_SUPABASE_SERVICE_ROLE_KEY:
            raise StorageError("Supabase storage requires AEGIS_SUPABASE_URL and service role key")
        try:
            from supabase import create_client
        except ImportError as exc:
            raise StorageError("supabase package is not installed", {"error": str(exc)}) from exc
        self.client = create_client(settings.AEGIS_SUPABASE_URL, settings.AEGIS_SUPABASE_SERVICE_ROLE_KEY)
        self.bucket = settings.AEGIS_SUPABASE_BUCKET

    async def write(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        try:
            self.client.storage.from_(self.bucket).upload(
                path=key,
                file=data,
                file_options={"content-type": content_type, "upsert": "true"},
            )
            return key
        except Exception as exc:
            raise StorageError("Supabase upload failed", {"key": key, "error": str(exc)}) from exc

    async def read(self, key: str) -> bytes:
        try:
            result = self.client.storage.from_(self.bucket).download(key)
            return bytes(result)
        except Exception as exc:
            raise StorageError("Supabase download failed", {"key": key, "error": str(exc)}) from exc

    async def delete(self, key: str) -> bool:
        try:
            self.client.storage.from_(self.bucket).remove([key])
            return True
        except Exception as exc:
            raise StorageError("Supabase delete failed", {"key": key, "error": str(exc)}) from exc

    async def exists(self, key: str) -> bool:
        parent, _, name = key.rpartition("/")
        try:
            entries = self.client.storage.from_(self.bucket).list(parent or "")
            return any(item.get("name") == name for item in entries)
        except Exception:
            return False

    async def list_keys(self, prefix: str = "") -> list[str]:
        parent = prefix.rstrip("/")
        try:
            entries = self.client.storage.from_(self.bucket).list(parent)
            return [f"{parent}/{item['name']}".strip("/") for item in entries if item.get("name")]
        except Exception as exc:
            raise StorageError("Supabase listing failed", {"prefix": prefix, "error": str(exc)}) from exc

    async def get_url(self, key: str) -> str:
        settings = get_settings()
        try:
            if settings.AEGIS_SUPABASE_PUBLIC_URLS:
                result = self.client.storage.from_(self.bucket).get_public_url(key)
                return str(result)
            result = self.client.storage.from_(self.bucket).create_signed_url(key, 3600)
            if isinstance(result, dict):
                return str(result.get("signedURL") or result.get("signedUrl") or "")
            return str(result)
        except Exception as exc:
            raise StorageError("Supabase URL generation failed", {"key": key, "error": str(exc)}) from exc
