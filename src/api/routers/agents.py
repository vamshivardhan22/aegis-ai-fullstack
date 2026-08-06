"""API routes for Aegis AI agents."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.compat import CompatibilityAgent
from src.agents.deploy import DeployAgent
from src.agents.drift import DriftAgent
from src.agents.explain import ExplainAgent
from src.agents.monitor import MonitorAgent
from src.agents.pii import PIIDetectionAgent
from src.agents.transform import TransformAgent
from src.core.exceptions import AgentError, HumanApprovalRequired
from src.core.security import get_current_user, require_role
from src.database.models import User, UserRole
from src.database.session import get_async_session
from src.llm.client import LLMClient
from src.storage import get_storage

router = APIRouter()

AGENT_TYPES = {
    "ingestion": CompatibilityAgent,
    "schema": CompatibilityAgent,
    "quality": CompatibilityAgent,
    "cleaning": CompatibilityAgent,
    "features": CompatibilityAgent,
    "ml": CompatibilityAgent,
    "explain": ExplainAgent,
    "deploy": DeployAgent,
    "monitor": MonitorAgent,
    "drift": DriftAgent,
    "transform": TransformAgent,
    "pii": PIIDetectionAgent,
}


def get_llm_client() -> LLMClient:
    """Return an LLM client for request-scoped agent execution."""

    return LLMClient()


@router.get("/")
async def list_agents(current_user: User = Depends(get_current_user)) -> dict[str, list[str]]:
    """List available M2 agent types."""

    del current_user
    return {"agent_types": sorted(AGENT_TYPES)}


@router.get("/{agent_type}/status")
async def agent_status(agent_type: str, current_user: User = Depends(get_current_user)) -> dict[str, str]:
    """Return basic agent availability."""

    del current_user
    if agent_type not in AGENT_TYPES:
        raise HTTPException(status_code=404, detail={"error": "Unknown agent type"})
    return {"agent_type": agent_type, "status": "available"}


@router.post("/{agent_type}/execute")
async def execute_agent(
    agent_type: str,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.DATA_ENGINEER, UserRole.ADMIN)),
) -> dict[str, Any]:
    """Instantiate and execute an agent from a JSON context."""

    if agent_type not in AGENT_TYPES:
        raise HTTPException(status_code=404, detail={"error": "Unknown agent type"})
    context = await request.json()
    llm_client = get_llm_client()
    try:
        agent = AGENT_TYPES[agent_type](agent_type, llm_client, session, get_storage())
        agent.current_user_id = current_user.id
        return await agent.execute(context)
    except HumanApprovalRequired as exc:
        raise HTTPException(status_code=status.HTTP_202_ACCEPTED, detail=exc.to_dict()) from exc
    except AgentError as exc:
        raise HTTPException(status_code=500, detail=exc.to_dict()) from exc
    finally:
        await llm_client.close()
