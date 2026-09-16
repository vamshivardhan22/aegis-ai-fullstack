"""LangChain-based LLM and embedding abstraction for AGIES."""

from __future__ import annotations

from typing import Any

from src.config import get_settings
from src.core.exceptions import LLMError


class LangChainProvider:
    """Provider-neutral LangChain facade with lazy model construction."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self._chat_model: Any | None = None
        self._embeddings: Any | None = None

    def _build_chat_model(self) -> Any:
        provider = self.settings.AEGIS_LLM_PROVIDER.lower()
        try:
            if provider == "openai":
                from langchain_openai import ChatOpenAI

                return ChatOpenAI(
                    model=self.settings.AEGIS_LLM_MODEL,
                    temperature=self.settings.AEGIS_LLM_TEMPERATURE,
                    timeout=self.settings.AEGIS_LLM_TIMEOUT,
                    api_key=self.settings.AEGIS_OPENAI_API_KEY,
                )
            if provider == "anthropic":
                from langchain_anthropic import ChatAnthropic

                return ChatAnthropic(
                    model=self.settings.AEGIS_LLM_MODEL,
                    temperature=self.settings.AEGIS_LLM_TEMPERATURE,
                    timeout=self.settings.AEGIS_LLM_TIMEOUT,
                    api_key=self.settings.AEGIS_ANTHROPIC_API_KEY,
                )
            if provider == "google":
                from langchain_google_genai import ChatGoogleGenerativeAI

                return ChatGoogleGenerativeAI(
                    model=self.settings.AEGIS_LLM_MODEL,
                    temperature=self.settings.AEGIS_LLM_TEMPERATURE,
                    timeout=self.settings.AEGIS_LLM_TIMEOUT,
                    google_api_key=self.settings.AEGIS_GOOGLE_API_KEY,
                )
            raise LLMError(
                "Unsupported LLM provider",
                {"provider": provider, "supported": ["openai", "anthropic", "google"]},
            )
        except ImportError as exc:
            raise LLMError(
                "LangChain provider package is not installed",
                {"provider": provider, "error": str(exc)},
            ) from exc

    @property
    def chat_model(self) -> Any:
        if self._chat_model is None:
            self._chat_model = self._build_chat_model()
        return self._chat_model

    def _build_embeddings(self) -> Any:
        provider = self.settings.AEGIS_EMBEDDING_PROVIDER.lower()
        try:
            if provider == "openai":
                from langchain_openai import OpenAIEmbeddings

                return OpenAIEmbeddings(
                    model=self.settings.AEGIS_EMBEDDING_MODEL,
                    api_key=self.settings.AEGIS_OPENAI_API_KEY,
                )
            raise LLMError(
                "Unsupported embedding provider",
                {"provider": provider, "supported": ["openai"]},
            )
        except ImportError as exc:
            raise LLMError(
                "LangChain embedding package is not installed",
                {"provider": provider, "error": str(exc)},
            ) from exc

    @property
    def embeddings(self) -> Any:
        if self._embeddings is None:
            self._embeddings = self._build_embeddings()
        return self._embeddings

    async def ainvoke(self, messages: list[tuple[str, str]]) -> Any:
        """Invoke the configured LangChain chat model."""

        try:
            return await self.chat_model.ainvoke(messages)
        except Exception as exc:
            raise LLMError("LangChain model invocation failed", {"error": str(exc)}) from exc

    async def aembed(self, text: str) -> list[float]:
        """Create an embedding using the configured LangChain embedding model."""

        try:
            return await self.embeddings.aembed_query(text)
        except Exception as exc:
            raise LLMError("LangChain embedding failed", {"error": str(exc)}) from exc
