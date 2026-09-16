"""Runtime wiring for the governed AGIES v2 graph."""

from __future__ import annotations

from typing import Any

from src.agents.pii import PIIDetectionAgent
from src.agents.transform import TransformAgent
from src.database.session import AsyncSessionLocal
from src.llm.langchain import LangChainProvider
from src.storage import get_storage
from src.v2.graph.builder import build_aegis_graph
from src.v2.llm.agent_adapter import LangChainAgentAdapter


def build_runtime_graph() -> Any:
    """Build a graph wired to the real storage, DB session, and LangChain-backed agents."""
    storage = get_storage()
    llm = LangChainAgentAdapter(LangChainProvider())

    def factory(name: str) -> Any:
        session = AsyncSessionLocal()
        if name == "transform":
            return TransformAgent(name, llm, session, storage)
        if name == "pii":
            return PIIDetectionAgent(name, llm, session, storage)
        raise ValueError(f"Unsupported AGIES v2 agent: {name}")

    return build_aegis_graph(agent_factory=factory, pii_agent_factory=factory, storage=storage)
