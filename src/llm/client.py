"""Ollama-backed LLM client."""

import json
import re
from typing import Any, Optional

import httpx

from src.config import get_settings
from src.core.exceptions import LLMError


class LLMClient:
    """Async client for generating text with Ollama chat models."""

    def __init__(self) -> None:
        """Initialize the HTTP client from settings."""

        self.settings = get_settings()
        self.client = httpx.AsyncClient(base_url=self.settings.AEGIS_OLLAMA_URL, timeout=self.settings.AEGIS_LLM_TIMEOUT)

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        expect_json: bool = False,
    ) -> str:
        """Generate a response from Ollama, optionally extracting JSON."""

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload: dict[str, Any] = {
            "model": self.settings.AEGIS_LLM_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        try:
            response = await self.client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()
            content = data.get("message", {}).get("content")
            if not isinstance(content, str):
                raise LLMError("Ollama response did not include message content", {"response": data})
            return self._extract_json(content) if expect_json else content
        except LLMError:
            raise
        except httpx.HTTPError as exc:
            raise LLMError("LLM HTTP request failed", {"error": str(exc)}) from exc
        except json.JSONDecodeError as exc:
            raise LLMError("LLM response was not valid JSON", {"error": str(exc)}) from exc
        except Exception as exc:
            raise LLMError("LLM generation failed", {"error": str(exc)}) from exc

    async def embed(self, text: str, model: Optional[str] = None) -> list[float]:
        """Generate an embedding vector with Ollama."""

        payload = {"model": model or self.settings.AEGIS_EMBEDDING_MODEL, "prompt": text}
        try:
            response = await self.client.post("/api/embeddings", json=payload)
            response.raise_for_status()
            data = response.json()
            embedding = data.get("embedding")
            if not isinstance(embedding, list):
                raise LLMError("Ollama response did not include embedding", {"response": data})
            return [float(value) for value in embedding]
        except LLMError:
            raise
        except httpx.HTTPError as exc:
            raise LLMError("Embedding HTTP request failed", {"error": str(exc)}) from exc
        except Exception as exc:
            raise LLMError("Embedding generation failed", {"error": str(exc)}) from exc

    def _extract_json(self, content: str) -> str:
        """Extract JSON from markdown code blocks or raw model output."""

        candidates = re.findall(r"```(?:json)?\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE)
        candidates.append(content)
        for candidate in candidates:
            text = candidate.strip()
            try:
                json.loads(text)
                return text
            except json.JSONDecodeError:
                continue
        raise LLMError("LLM response did not contain valid JSON", {"content": content[:500]})

    async def close(self) -> None:
        """Close the underlying HTTP client."""

        await self.client.aclose()
