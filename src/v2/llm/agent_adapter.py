"""Adapter that lets legacy AGIES agents use the LangChain provider."""

from __future__ import annotations

import json
from typing import Any

from src.llm.langchain import LangChainProvider


class LangChainAgentAdapter:
    """Expose the small ``generate`` contract expected by existing agents."""

    def __init__(self, provider: LangChainProvider | None = None) -> None:
        self.provider = provider or LangChainProvider()

    async def generate(self, prompt: str, expect_json: bool = False) -> str:
        response = await self.provider.ainvoke([("system", "You are an AGIES DataOps agent. Return only the requested result."), ("user", prompt)])
        content: Any = getattr(response, "content", response)
        if isinstance(content, list):
            content = "".join(str(part.get("text", part)) if isinstance(part, dict) else str(part) for part in content)
        text = str(content).strip()
        if expect_json:
            # Validate JSON at the integration boundary; agents can safely fall back on malformed output.
            json.loads(text)
        return text
