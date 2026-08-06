"""Natural-language chat API for Aegis AI."""

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.rag import RAGKnowledgeAgent
from src.core.security import get_current_user
from src.database.models import Dataset, Pipeline
from src.database.models import User
from src.database.session import get_async_session
from src.llm.client import LLMClient
from src.storage import get_storage

router = APIRouter()
CHAT_HISTORY: list[dict[str, Any]] = []


class ChatQuestion(BaseModel):
    """Chat question payload."""

    question: str
    project_id: Optional[str] = None


@router.post("/ask")
async def ask_chat(
    payload: ChatQuestion,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Answer a natural-language question using database facts or RAG."""

    del current_user
    direct = await _answer_from_database(payload, session)
    if direct is not None:
        response = direct
    else:
        llm = LLMClient()
        try:
            agent = RAGKnowledgeAgent("rag", llm, session, get_storage())
            response = await agent.execute({"action": "query", "question": payload.question})
        finally:
            await llm.close()
    CHAT_HISTORY.append({"question": payload.question, "response": response, "created_at": datetime.utcnow().isoformat()})
    return response


@router.get("/history")
async def chat_history(current_user: User = Depends(get_current_user)) -> dict[str, list[dict[str, Any]]]:
    """Return recent chat interactions."""

    del current_user
    return {"history": CHAT_HISTORY[-50:]}


async def _answer_from_database(payload: ChatQuestion, session: AsyncSession) -> dict[str, Any] | None:
    """Answer direct factual questions from PostgreSQL/SQLite records."""

    question = payload.question.lower()
    if "quality score" in question and "dataset" in question:
        result = await session.execute(select(Dataset))
        datasets = result.scalars().all()
        candidates = [dataset for dataset in datasets if payload.project_id is None or dataset.project_id == payload.project_id]
        selected = None
        for dataset in candidates:
            if dataset.name.lower() in question:
                selected = dataset
                break
        if selected is None and candidates:
            selected = candidates[0]
        if selected is None:
            return {"answer": "No datasets are available for that question.", "sources": [], "confidence": 0.4}
        score = selected.quality_score
        answer = f"Dataset {selected.name} has quality score {score if score is not None else 'unknown'}."
        return {
            "answer": answer,
            "sources": [{"type": "dataset", "id": selected.id, "name": selected.name}],
            "confidence": 0.9,
        }
    if "pipeline" in question and "fail" in question:
        result = await session.execute(select(Pipeline))
        pipelines = result.scalars().all()
        if pipelines:
            pipeline = pipelines[0]
            answer = pipeline.error_message or f"Pipeline {pipeline.name} has status {pipeline.status.value}."
            return {"answer": answer, "sources": [{"type": "pipeline", "id": pipeline.id}], "confidence": 0.8}
    return None
