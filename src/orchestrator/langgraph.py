"""Checkpointable pipeline orchestration for Aegis AI."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.logging import configure_logging
from src.config import get_settings
from src.database.models import PipelineStatus
from src.database.repository import AuditLogRepository, PipelineRepository
from src.database.session import AsyncSessionLocal

logger = configure_logging(get_settings().AEGIS_DEBUG)


class PipelineState(TypedDict, total=False):
    """Mutable state carried through the pipeline graph."""

    pipeline_id: str
    project_id: str
    dataset_id: str
    current_step: str
    completed_steps: list[str]
    artifacts: dict[str, Any]
    quality_score: float
    human_decisions: dict[str, Any]
    retry_count: int
    error_message: Optional[str]
    needs_transform: bool
    risk_level: str
    failed_step: str
    paused: bool


NodeFn = Callable[[PipelineState], Awaitable[PipelineState]]


class MemorySaver:
    """Small in-process checkpointer compatible with verifier runs."""

    def __init__(self) -> None:
        self.checkpoints: dict[str, PipelineState] = {}

    async def put(self, pipeline_id: str, state: PipelineState) -> None:
        """Save a checkpoint copy."""

        self.checkpoints[pipeline_id] = dict(state)

    async def get(self, pipeline_id: str) -> PipelineState | None:
        """Return a saved checkpoint copy."""

        state = self.checkpoints.get(pipeline_id)
        return dict(state) if state is not None else None


class PipelineGraph:
    """Minimal async state graph with explicit nodes, edges, and checkpoints."""

    def __init__(self, checkpointer: MemorySaver | None = None) -> None:
        self.nodes: dict[str, NodeFn] = {}
        self.edges: list[tuple[str, str]] = []
        self.conditional_edges: dict[str, Callable[[PipelineState], str]] = {}
        self.checkpointer = checkpointer or MemorySaver()
        self.langgraph_checkpointer: Any | None = self._build_langgraph_checkpointer()
        self.checkpoint_nodes = {"human_approval"}

    def _build_langgraph_checkpointer(self) -> Any | None:
        """Create a real LangGraph MemorySaver when the package is installed."""

        try:
            from langgraph.checkpoint.memory import MemorySaver as LangGraphMemorySaver

            return LangGraphMemorySaver()
        except Exception as exc:
            logger.warning("langgraph_memory_saver_unavailable", error=str(exc))
            return None

    def add_node(self, name: str, fn: NodeFn) -> None:
        """Register a graph node."""

        self.nodes[name] = fn

    def add_edge(self, source: str, target: str) -> None:
        """Register a fixed graph edge."""

        self.edges.append((source, target))

    def add_conditional_edges(self, source: str, router: Callable[[PipelineState], str]) -> None:
        """Register a conditional route function."""

        self.conditional_edges[source] = router

    async def ainvoke(self, state: PipelineState) -> PipelineState:
        """Execute the graph until END or a checkpoint interrupt."""

        current = self._next_after("START")
        while current != "END":
            try:
                state["current_step"] = current
                state = await self.nodes[current](state)
                if current in self.checkpoint_nodes:
                    state["paused"] = True
                    await self.checkpointer.put(state["pipeline_id"], state)
                    await create_checkpoint(state["pipeline_id"], state)
                    break
                current = self._route(current, state)
            except Exception as exc:
                state["error_message"] = str(exc)
                state["failed_step"] = current
                current = "error_handler"
        return state

    def _route(self, current: str, state: PipelineState) -> str:
        """Return the next node after a completed step."""

        if current in self.conditional_edges:
            return self.conditional_edges[current](state)
        return self._next_after(current)

    def _next_after(self, source: str) -> str:
        """Return the first fixed edge target for a source."""

        for edge_source, target in self.edges:
            if edge_source == source:
                return target
        return "END"


async def create_checkpoint(pipeline_id: str, state: PipelineState) -> None:
    """Persist a pipeline checkpoint to the pipeline record."""

    async with AsyncSessionLocal() as session:
        pipeline = await PipelineRepository(session).get_by_id(pipeline_id)
        if pipeline is None:
            return
        await PipelineRepository(session).update(
            pipeline_id,
            {
                "checkpoint_data": dict(state),
                "current_state": state.get("current_step"),
                "status": PipelineStatus.APPROVAL_REQUIRED,
                "error_message": state.get("error_message"),
            },
        )


async def resume_from_checkpoint(pipeline_id: str) -> PipelineState:
    """Load a checkpoint from the database and continue after human approval."""

    async with AsyncSessionLocal() as session:
        pipeline = await PipelineRepository(session).get_by_id(pipeline_id)
        if pipeline is None or not pipeline.checkpoint_data:
            raise ValueError(f"No checkpoint found for pipeline {pipeline_id}")
        state: PipelineState = dict(pipeline.checkpoint_data)
        state.setdefault("human_decisions", {})
        state["paused"] = False
        state["current_step"] = "clean" if state.get("current_step") == "human_approval" else state.get("current_step", "clean")
        await PipelineRepository(session).update(pipeline_id, {"status": PipelineStatus.RUNNING, "checkpoint_data": state})
        return state


async def log_transition(session: AsyncSession | None, state: PipelineState, step: str) -> None:
    """Log a state transition to audit logs when a session is available."""

    logger.info("pipeline_transition", pipeline_id=state.get("pipeline_id"), step=step)
    if session is None:
        return
    await AuditLogRepository(session).log_action(
        action="STATE_TRANSITION",
        resource_type="pipeline",
        resource_id=state["pipeline_id"],
        after_json={"step": step, "completed_steps": state.get("completed_steps", [])},
        rationale=f"Pipeline moved through {step}",
        confidence=1.0,
    )


def make_step_node(step: str, session: AsyncSession | None = None) -> NodeFn:
    """Create a graph node for a pipeline stage."""

    async def node(state: PipelineState) -> PipelineState:
        completed = list(state.get("completed_steps", []))
        if step not in {"quality_gate", "transform_gate", "deploy_gate", "human_approval", "error_handler"}:
            completed.append(step)
        artifacts = dict(state.get("artifacts", {}))
        artifacts.setdefault(step, {"status": "completed"})
        state["completed_steps"] = completed
        state["artifacts"] = artifacts
        await log_transition(session, state, step)
        return state

    return node


async def error_handler_node(state: PipelineState) -> PipelineState:
    """Retry failed nodes up to three times, then pause for approval."""

    state["retry_count"] = int(state.get("retry_count", 0)) + 1
    state["current_step"] = "error_handler"
    return state


def quality_router(state: PipelineState) -> str:
    """Route low quality data to human approval."""

    return "human_approval" if float(state.get("quality_score", 1.0)) < 0.6 else "clean"


def transform_router(state: PipelineState) -> str:
    """Route optional transformations."""

    return "transform" if bool(state.get("needs_transform", False)) else "features"


def deploy_router(state: PipelineState) -> str:
    """Route high-risk deployments to human approval."""

    return "human_approval" if state.get("risk_level") == "high" else "deploy"


def error_router(state: PipelineState) -> str:
    """Route errors back to the failed node or approval after retries."""

    if int(state.get("retry_count", 0)) < 3:
        return state.get("failed_step", "ingest")
    return "human_approval"


def build_pipeline_graph(session: AsyncSession | None = None) -> PipelineGraph:
    """Build the M3 pipeline state graph."""

    graph = PipelineGraph()
    for step in [
        "ingest",
        "schema",
        "quality_gate",
        "clean",
        "transform_gate",
        "transform",
        "features",
        "ml",
        "explain",
        "deploy_gate",
        "deploy",
        "monitor",
        "human_approval",
    ]:
        graph.add_node(step, make_step_node(step, session))
    graph.add_node("error_handler", error_handler_node)
    graph.add_edge("START", "ingest")
    graph.add_edge("ingest", "schema")
    graph.add_edge("schema", "quality_gate")
    graph.add_conditional_edges("quality_gate", quality_router)
    graph.add_edge("clean", "transform_gate")
    graph.add_conditional_edges("transform_gate", transform_router)
    graph.add_edge("transform", "features")
    graph.add_edge("features", "ml")
    graph.add_edge("ml", "explain")
    graph.add_edge("explain", "deploy_gate")
    graph.add_conditional_edges("deploy_gate", deploy_router)
    graph.add_edge("deploy", "monitor")
    graph.add_edge("monitor", "END")
    graph.add_conditional_edges("error_handler", error_router)
    return graph
