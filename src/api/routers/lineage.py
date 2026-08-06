"""Lineage graph and impact API routes."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import get_current_user, require_role
from src.database.models import Lineage, User, UserRole
from src.database.repository import LineageRepository, PipelineRepository
from src.database.session import get_async_session

router = APIRouter()


class LineageRecord(BaseModel):
    """Lineage creation payload."""

    source_dataset_id: str
    target_dataset_id: str
    transformation_type: str
    agent_id: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


@router.get("/datasets/{dataset_id}")
async def dataset_lineage(
    dataset_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return upstream and downstream lineage for a dataset using recursive CTEs."""

    del current_user
    upstream_sql = text(
        """
        WITH RECURSIVE upstream(source_dataset_id, target_dataset_id, transformation_type, agent_id, depth) AS (
            SELECT source_dataset_id, target_dataset_id, transformation_type, agent_id, 1
            FROM lineage WHERE target_dataset_id = :dataset_id
            UNION ALL
            SELECT l.source_dataset_id, l.target_dataset_id, l.transformation_type, l.agent_id, u.depth + 1
            FROM lineage l JOIN upstream u ON l.target_dataset_id = u.source_dataset_id
            WHERE u.depth < 10
        )
        SELECT * FROM upstream
        """
    )
    downstream_sql = text(
        """
        WITH RECURSIVE downstream(source_dataset_id, target_dataset_id, transformation_type, agent_id, depth) AS (
            SELECT source_dataset_id, target_dataset_id, transformation_type, agent_id, 1
            FROM lineage WHERE source_dataset_id = :dataset_id
            UNION ALL
            SELECT l.source_dataset_id, l.target_dataset_id, l.transformation_type, l.agent_id, d.depth + 1
            FROM lineage l JOIN downstream d ON l.source_dataset_id = d.target_dataset_id
            WHERE d.depth < 10
        )
        SELECT * FROM downstream
        """
    )
    upstream_rows = (await session.execute(upstream_sql, {"dataset_id": dataset_id})).mappings().all()
    downstream_rows = (await session.execute(downstream_sql, {"dataset_id": dataset_id})).mappings().all()
    dataset_ids = {dataset_id}
    edges = []
    for row in [*upstream_rows, *downstream_rows]:
        dataset_ids.add(row["source_dataset_id"])
        dataset_ids.add(row["target_dataset_id"])
        edges.append({"source": row["source_dataset_id"], "target": row["target_dataset_id"], "label": row["transformation_type"]})
    nodes = await _dataset_nodes(session, dataset_ids)
    return {
        "dataset_id": dataset_id,
        "upstream": [
            {
                "dataset_id": row["source_dataset_id"],
                "transformation_type": row["transformation_type"],
                "agent": row["agent_id"],
                "depth": row["depth"],
            }
            for row in upstream_rows
        ],
        "downstream": [
            {
                "dataset_id": row["target_dataset_id"],
                "transformation_type": row["transformation_type"],
                "agent": row["agent_id"],
                "depth": row["depth"],
            }
            for row in downstream_rows
        ],
        "nodes": nodes,
        "edges": edges,
    }


@router.get("/pipelines/{pipeline_id}")
async def pipeline_lineage(
    pipeline_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return lineage for the dataset associated with a pipeline."""

    del current_user
    pipeline = await PipelineRepository(session).get_by_id(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail={"detail": "Pipeline not found", "code": "NOT_FOUND"})
    return await dataset_lineage(pipeline.dataset_id, session, current_user=None)  # type: ignore[arg-type]


@router.get("/impact/{dataset_id}")
async def lineage_impact(
    dataset_id: str,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Return downstream datasets, models, and deployments affected by a dataset change."""

    del current_user
    sql = text(
        """
        WITH RECURSIVE downstream(source_dataset_id, target_dataset_id, depth) AS (
            SELECT source_dataset_id, target_dataset_id, 1 FROM lineage WHERE source_dataset_id = :dataset_id
            UNION ALL
            SELECT l.source_dataset_id, l.target_dataset_id, d.depth + 1
            FROM lineage l JOIN downstream d ON l.source_dataset_id = d.target_dataset_id
            WHERE d.depth < 10
        )
        SELECT target_dataset_id, depth FROM downstream
        """
    )
    rows = (await session.execute(sql, {"dataset_id": dataset_id})).mappings().all()
    affected_dataset_ids = [row["target_dataset_id"] for row in rows]
    if not affected_dataset_ids:
        return {"affected_datasets": [], "affected_models": [], "affected_deployments": []}
    models_sql = text("SELECT id, name, dataset_id FROM models WHERE dataset_id IN :ids").bindparams(
        bindparam("ids", expanding=True)
    )
    try:
        model_rows = (await session.execute(models_sql, {"ids": affected_dataset_ids})).mappings().all()
    except Exception:
        model_rows = []
    model_ids = [row["id"] for row in model_rows]
    deployment_rows = []
    if model_ids:
        deployments_sql = text("SELECT id, model_id, endpoint_url, status FROM deployments WHERE model_id IN :ids").bindparams(
            bindparam("ids", expanding=True)
        )
        try:
            deployment_rows = (await session.execute(deployments_sql, {"ids": model_ids})).mappings().all()
        except Exception:
            deployment_rows = []
    return {
        "affected_datasets": [{"id": row["target_dataset_id"], "depth": row["depth"]} for row in rows],
        "affected_models": [dict(row) for row in model_rows],
        "affected_deployments": [dict(row) for row in deployment_rows],
    }


@router.post("/record")
async def record_lineage(
    payload: LineageRecord,
    session: AsyncSession = Depends(get_async_session),
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.DATA_ENGINEER)),
) -> dict[str, Any]:
    """Create a lineage edge."""

    lineage = await LineageRepository(session).create(
        Lineage(
            source_dataset_id=payload.source_dataset_id,
            target_dataset_id=payload.target_dataset_id,
            transformation_type=payload.transformation_type,
            agent_id=payload.agent_id,
            config_json=payload.config,
        )
    )
    return {
        "id": lineage.id,
        "source_dataset_id": lineage.source_dataset_id,
        "target_dataset_id": lineage.target_dataset_id,
        "transformation_type": lineage.transformation_type,
        "agent_id": lineage.agent_id,
        "created_by": current_user.id,
    }


async def _dataset_nodes(session: AsyncSession, dataset_ids: set[str]) -> list[dict[str, str | None]]:
    """Load dataset node labels and layers."""

    if not dataset_ids:
        return []
    placeholders = ", ".join(f":id{index}" for index, _ in enumerate(dataset_ids))
    params = {f"id{index}": value for index, value in enumerate(dataset_ids)}
    rows = (await session.execute(text(f"SELECT id, name, bronze_path, silver_path, gold_path FROM datasets WHERE id IN ({placeholders})"), params)).mappings().all()
    nodes = []
    for row in rows:
        layer = "gold" if row["gold_path"] else "silver" if row["silver_path"] else "bronze"
        nodes.append({"id": row["id"], "name": row["name"], "layer": layer})
    return nodes
