"""Project-scoped chat API with per-user ephemeral history."""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.rag import RAGKnowledgeAgent
from src.core.security import get_current_user
from src.core.tenancy import require_project_access
from src.database.models import Dataset, Pipeline, Project, User, UserRole
from src.database.session import get_async_session
from src.llm.client import LLMClient
from src.storage import get_storage

router = APIRouter()
CHAT_HISTORY: dict[str, list[dict[str, Any]]] = {}


class ChatQuestion(BaseModel):
    """Chat question payload."""

    question: str = Field(min_length=1, max_length=4000)
    project_id: str | None = None


@router.post("/ask")
async def ask_chat(
    payload: ChatQuestion,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Answer a question from facts the caller is authorized to access."""
    if payload.project_id:
        await require_project_access(session, current_user, payload.project_id)
    direct = await _answer_from_database(payload, session, current_user)
    if direct is not None:
        response = direct
    else:
        llm = LLMClient()
        try:
            agent = RAGKnowledgeAgent("rag", llm, session, get_storage())
            response = await agent.execute({
                "action": "query",
                "question": payload.question,
                "project_id": payload.project_id,
                "user_id": current_user.id,
            })
        finally:
            await llm.close()
    history = CHAT_HISTORY.setdefault(current_user.id, [])
    history.append({
        "question": payload.question,
        "response": response,
        "project_id": payload.project_id,
        "created_at": datetime.utcnow().isoformat(),
    })
    del history[:-50]
    return response


@router.get("/history")
async def chat_history(current_user: User = Depends(get_current_user)) -> dict[str, list[dict[str, Any]]]:
    """Return only this user's recent in-process chat interactions."""
    return {"history": CHAT_HISTORY.get(current_user.id, [])[-50:]}


async def _answer_from_database(
    payload: ChatQuestion, session: AsyncSession, current_user: User
) -> dict[str, Any] | None:
    """Answer direct factual questions from project-scoped database records."""
    question = payload.question.lower()
    dataset_query = (
        select(Dataset)
        .join(Project, Project.id == Dataset.project_id)
        .where(Dataset.is_deleted.is_(False))
    )
    if current_user.role != UserRole.ADMIN:
        dataset_query = dataset_query.where(Project.owner_id == current_user.id)
    if payload.project_id:
        dataset_query = dataset_query.where(Dataset.project_id == payload.project_id)

    if "quality score" in question and "dataset" in question:
        result = await session.execute(dataset_query.limit(200))
        candidates = list(result.scalars().all())
        selected = next((item for item in candidates if item.name.lower() in question), None)
        if selected is None and len(candidates) == 1:
            selected = candidates[0]
        if selected is None:
            return {
                "answer": "Please specify the dataset name so I can report the correct quality score.",
                "sources": [],
                "confidence": 0.25,
            }
        score = selected.quality_score
        return {
            "answer": f"Dataset {selected.name} has quality score {score if score is not None else 'unknown'}.",
            "sources": [{"type": "dataset", "id": selected.id, "name": selected.name}],
            "confidence": 0.9,
        }

    if "pipeline" in question and ("fail" in question or "status" in question):
        query = select(Pipeline).join(Project, Project.id == Pipeline.project_id)
        if current_user.role != UserRole.ADMIN:
            query = query.where(Project.owner_id == current_user.id)
        if payload.project_id:
            query = query.where(Pipeline.project_id == payload.project_id)
        result = await session.execute(query.limit(200))
        candidates = list(result.scalars().all())
        selected = next((item for item in candidates if item.name.lower() in question or item.id.lower() in question), None)
        if selected is None and len(candidates) == 1:
            selected = candidates[0]
        if selected is None:
            return {
                "answer": "Please specify the pipeline name or ID so I can report its status.",
                "sources": [],
                "confidence": 0.25,
            }
        answer = selected.error_message or f"Pipeline {selected.name} is {selected.status.value}."
        return {
            "answer": answer,
            "sources": [{"type": "pipeline", "id": selected.id, "name": selected.name}],
            "confidence": 0.9,
        }
    return None
