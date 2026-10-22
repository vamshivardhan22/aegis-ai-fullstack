"""Project-scoped chat API with persisted per-user history."""
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.rag import RAGKnowledgeAgent
from src.core.security import get_current_user
from src.core.tenancy import require_project_access
from src.database.models import ChatMessage, Dataset, Pipeline, Project, User, UserRole
from src.database.session import get_async_session
from src.llm.client import LLMClient
from src.storage import get_storage

router = APIRouter()


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
    """Answer from authorized facts and persist the resulting conversation turn."""
    effective_project_id = payload.project_id
    if effective_project_id:
        await require_project_access(session, current_user, effective_project_id)
    elif current_user.role != UserRole.ADMIN:
        owned = await session.execute(
            select(Project.id).where(Project.owner_id == current_user.id).order_by(Project.created_at.asc()).limit(2)
        )
        owned_ids = list(owned.scalars().all())
        if len(owned_ids) == 1:
            effective_project_id = owned_ids[0]
    scoped_payload = payload.model_copy(update={"project_id": effective_project_id})
    direct = await _answer_from_database(scoped_payload, session, current_user)
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
    message = ChatMessage(
        user_id=current_user.id,
        project_id=effective_project_id,
        question=payload.question,
        response_json=response,
    )
    session.add(message)
    await session.commit()
    return response


@router.get("/history")
async def chat_history(
    project_id: str | None = None,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, list[dict[str, Any]]]:
    """Return this user's recent persisted chat turns, optionally for one authorized project."""
    if project_id:
        await require_project_access(session, current_user, project_id)
    query = select(ChatMessage).where(ChatMessage.user_id == current_user.id)
    if project_id:
        query = query.where(ChatMessage.project_id == project_id)
    result = await session.execute(query.order_by(ChatMessage.created_at.desc()).limit(50))
    messages = list(reversed(result.scalars().all()))
    return {"history": [
        {
            "question": message.question,
            "response": message.response_json,
            "project_id": message.project_id,
            "created_at": message.created_at.isoformat() if message.created_at else None,
        }
        for message in messages
    ]}


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
