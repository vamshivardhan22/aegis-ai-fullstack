"""Provider-backed asynchronous LLM client using LangChain integrations."""
from __future__ import annotations

import json
import re
from typing import Any

from src.config import get_settings
from src.core.exceptions import LLMError


class LLMClient:
    """Create chat and embedding calls through the configured LangChain provider."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def _chat_model(self, temperature: float, max_tokens: int) -> Any:
        provider = self.settings.AEGIS_LLM_PROVIDER
        model_name = self.settings.AEGIS_LLM_MODEL
        try:
            if provider == "openai":
                if not self.settings.AEGIS_OPENAI_API_KEY:
                    raise LLMError("AEGIS_OPENAI_API_KEY is required for the OpenAI provider")
                from langchain_openai import ChatOpenAI

                return ChatOpenAI(
                    model=model_name,
                    api_key=self.settings.AEGIS_OPENAI_API_KEY,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self.settings.AEGIS_LLM_TIMEOUT,
                )
            if provider == "anthropic":
                if not self.settings.AEGIS_ANTHROPIC_API_KEY:
                    raise LLMError("AEGIS_ANTHROPIC_API_KEY is required for the Anthropic provider")
                from langchain_anthropic import ChatAnthropic

                return ChatAnthropic(
                    model=model_name,
                    anthropic_api_key=self.settings.AEGIS_ANTHROPIC_API_KEY,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=self.settings.AEGIS_LLM_TIMEOUT,
                )
            if provider == "google":
                if not self.settings.AEGIS_GOOGLE_API_KEY:
                    raise LLMError("AEGIS_GOOGLE_API_KEY is required for the Google provider")
                from langchain_google_genai import ChatGoogleGenerativeAI

                return ChatGoogleGenerativeAI(
                    model=model_name,
                    google_api_key=self.settings.AEGIS_GOOGLE_API_KEY,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    timeout=self.settings.AEGIS_LLM_TIMEOUT,
                )
            raise LLMError("Unsupported LLM provider", {"provider": provider})
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("Unable to initialize configured LangChain provider", {"provider": provider}) from exc

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        expect_json: bool = False,
    ) -> str:
        """Generate text asynchronously and optionally validate/extract JSON."""
        messages: list[tuple[str, str]] = []
        if system:
            messages.append(("system", system))
        messages.append(("human", prompt))
        try:
            response = await self._chat_model(temperature, max_tokens).ainvoke(messages)
            content = response.content
            if isinstance(content, list):
                content = "".join(
                    str(part.get("text", "")) if isinstance(part, dict) else str(part)
                    for part in content
                )
            if not isinstance(content, str):
                raise LLMError("Provider response did not contain text")
            return self._extract_json(content) if expect_json else content
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("LLM generation failed", {"provider": self.settings.AEGIS_LLM_PROVIDER}) from exc

    async def embed(self, text: str, model: str | None = None) -> list[float]:
        """Generate a fixed 768-dimensional OpenAI embedding for the Qdrant collection."""
        if not self.settings.AEGIS_OPENAI_API_KEY:
            raise LLMError("AEGIS_OPENAI_API_KEY is required for the configured embedding provider")
        try:
            from langchain_openai import OpenAIEmbeddings

            embeddings = OpenAIEmbeddings(
                model=model or self.settings.AEGIS_EMBEDDING_MODEL,
                dimensions=768,
                api_key=self.settings.AEGIS_OPENAI_API_KEY,
                request_timeout=self.settings.AEGIS_LLM_TIMEOUT,
            )
            vector = await embeddings.aembed_query(text)
            if len(vector) != 768:
                raise LLMError("Embedding provider returned an unexpected vector dimension", {"dimension": len(vector)})
            return [float(value) for value in vector]
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError("Embedding generation failed", {"provider": self.settings.AEGIS_EMBEDDING_PROVIDER}) from exc

    @staticmethod
    def _extract_json(content: str) -> str:
        """Extract valid JSON from raw or fenced model output."""
        candidates = re.findall(r"\x60\x60\x60(?:json)?\s*(.*?)\x60\x60\x60", content, flags=re.DOTALL | re.IGNORECASE)
        candidates.append(content)
        for candidate in candidates:
            candidate = candidate.strip()
            try:
                json.loads(candidate)
                return candidate
            except json.JSONDecodeError:
                continue
        raise LLMError("LLM response did not contain valid JSON", {"content": content[:500]})

    async def close(self) -> None:
        """LangChain creates request-scoped clients; no persistent client is held here."""
        return None
