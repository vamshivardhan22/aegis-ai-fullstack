"""Native LangGraph execution for a real AGIES data transformation pipeline.

The graph owns lifecycle and governance. Existing domain agents perform the data work.
Dependencies are injected into the builder so the checkpointed state remains JSON-safe.
"""

from __future__ import annotations

import io
from typing import Any, Callable
from uuid import uuid4

import pandas as pd
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from src.agents.pii import PIIDetectionAgent
from src.agents.transform import TransformAgent
from src.v2.graph.state import AegisState


AgentFactory = Callable[[str], Any]


def _audit(state: AegisState, event: str, **details: Any) -> list[dict[str, Any]]:
    events = list(state.get("audit_events", []))
    events.append({"event": event, "details": details})
    return events


def build_aegis_graph(
    *,
    agent_factory: AgentFactory,
    storage: Any,
    audit_repo: Any | None = None,
    pii_agent_factory: AgentFactory | None = None,
    max_retries: int = 2,
    approval_threshold: float = 0.7,
) -> Any:
    """Compile the governed graph with a real TransformAgent execution node.

    ``agent_factory`` must return an existing AGIES domain agent such as TransformAgent.
    ``thread_id`` must be supplied by callers when invoking/resuming the compiled graph.
    Approval uses LangGraph's interrupt mechanism, so resume continues from the checkpoint.
    """

    pii_factory = pii_agent_factory or agent_factory

    async def authenticate(state: AegisState) -> AegisState:
        if not state.get("user_id") or not state.get("role"):
            return {**state, "status": "failed", "current_step": "authenticate", "error": "Authentication context is required", "audit_events": _audit(state, "AUTH_FAILED")}
        return {**state, "status": "running", "current_step": "authenticate", "audit_events": _audit(state, "AUTHENTICATED", user_id=state["user_id"], role=state["role"])}

    async def authorize(state: AegisState) -> AegisState:
        if state.get("action") in {"execute_agent", "transform", "deploy"} and state.get("role") not in {"admin", "data_engineer"}:
            return {**state, "status": "failed", "current_step": "authorize", "error": "Role is not authorized for this action", "audit_events": _audit(state, "ACCESS_DENIED", role=state.get("role"))}
        return {**state, "current_step": "authorize", "audit_events": _audit(state, "AUTHORIZED")}

    async def inspect(state: AegisState) -> AegisState:
        try:
            raw = await storage.read(state["source_data_path"])
            df = pd.read_csv(io.BytesIO(raw))
            missing = int(df.isna().sum().sum())
            cells = max(int(df.shape[0] * max(df.shape[1], 1)), 1)
            quality = max(0.0, 1.0 - (missing / cells))
            return {**state, "quality_score": quality, "current_step": "inspect", "audit_events": _audit(state, "QUALITY_INSPECTED", row_count=len(df), column_count=len(df.columns), missing_values=missing, quality_score=quality)}
        except Exception as exc:
            return {**state, "status": "failed", "current_step": "inspect", "error": str(exc), "audit_events": _audit(state, "QUALITY_INSPECTION_FAILED", error=str(exc))}

    async def pii_scan(state: AegisState) -> AegisState:
        agent = pii_factory("pii")
        result = await agent.execute({"data_sample_path": state["source_data_path"], "dataset_id": state["source_dataset_id"]})
        if result.get("pii_failed"):
            return {**state, "status": "failed", "current_step": "pii", "error": result.get("error", "PII scan failed"), "audit_events": _audit(state, "PII_SCAN_FAILED")}
        findings = result.get("masking_recommendations", [])
        return {**state, "pii_findings": findings, "current_step": "pii", "audit_events": _audit(state, "PII_SCAN_COMPLETE", columns_flagged=result.get("columns_flagged", 0))}

    async def policy(state: AegisState) -> AegisState:
        pii_risk = 0.9 if state.get("pii_findings") else 0.0
        quality_risk = 1.0 - float(state.get("quality_score", 1.0))
        operation_risk = 0.8 if state.get("action") in {"deploy", "delete", "pii_release"} else 0.0
        score = max(pii_risk, quality_risk, operation_risk)
        required = score >= approval_threshold
        return {**state, "risk_score": score, "approval_required": required, "current_step": "policy", "audit_events": _audit(state, "POLICY_EVALUATED", risk_score=score, approval_required=required)}

    async def approval(state: AegisState) -> AegisState:
        decision = state.get("approval_decision")
        if decision == "rejected":
            return {**state, "status": "rejected", "current_step": "approval", "audit_events": _audit(state, "HUMAN_DECISION", decision="rejected")}
        if decision != "approved":
            decision = interrupt({"type": "approval_required", "pipeline_id": state.get("pipeline_id"), "risk_score": state.get("risk_score"), "pii_findings": state.get("pii_findings", []), "message": "Human approval is required before transformation."})
        if decision not in {"approved", "rejected"}:
            return {**state, "status": "failed", "current_step": "approval", "error": "Invalid approval decision"}
        status = "running" if decision == "approved" else "rejected"
        return {**state, "approval_decision": decision, "status": status, "current_step": "approval", "audit_events": _audit(state, "HUMAN_DECISION", decision=decision)}

    async def execute(state: AegisState) -> AegisState:
        agent = agent_factory("transform")
        agent.current_user_id = state.get("user_id")
        result = await agent.execute({
            "source_data_path": state["source_data_path"],
            "source_dataset_id": state["source_dataset_id"],
            "output_name": state["output_name"],
            "transformation_request": state["transformation_request"],
            "project_id": state.get("pipeline_id"),
        })
        if result.get("transform_failed"):
            retries = int(state.get("retry_count", 0)) + 1
            return {**state, "retry_count": retries, "status": "retrying" if retries <= int(state.get("max_retries", max_retries)) else "failed", "current_step": "execute", "error": result.get("error", "Transformation failed"), "audit_events": _audit(state, "EXECUTION_FAILED", retry_count=retries)}
        return {**state, "status": "completed", "current_step": "execute", "result": result, "audit_events": _audit(state, "EXECUTION_COMPLETED", output_path=result.get("output_path"), row_count=result.get("row_count"))}

    def after_authorize(state: AegisState) -> str:
        return "finish" if state.get("status") == "failed" else "inspect"

    def after_inspect(state: AegisState) -> str:
        return "finish" if state.get("status") == "failed" else "pii"

    def after_pii(state: AegisState) -> str:
        return "finish" if state.get("status") == "failed" else "policy"

    def after_policy(state: AegisState) -> str:
        return "finish" if state.get("status") == "failed" else ("approval" if state.get("approval_required") else "execute")

    def after_approval(state: AegisState) -> str:
        return "finish" if state.get("status") in {"rejected", "failed"} else "execute"

    def after_execute(state: AegisState) -> str:
        if state.get("status") == "retrying":
            return "execute"
        return "finish"

    def finish(state: AegisState) -> AegisState:
        return {**state, "current_step": "finish", "audit_events": _audit(state, "PIPELINE_COMPLETED" if state.get("status") == "completed" else "PIPELINE_TERMINATED", status=state.get("status"), error=state.get("error"))}

    builder = StateGraph(AegisState)
    builder.add_node("authenticate", authenticate)
    builder.add_node("authorize", authorize)
    builder.add_node("inspect", inspect)
    builder.add_node("pii", pii_scan)
    builder.add_node("policy", policy)
    builder.add_node("approval", approval)
    builder.add_node("execute", execute)
    builder.add_node("finish", finish)
    builder.add_edge(START, "authenticate")
    builder.add_edge("authenticate", "authorize")
    builder.add_conditional_edges("authorize", after_authorize, {"inspect": "inspect", "finish": "finish"})
    builder.add_conditional_edges("inspect", after_inspect, {"pii": "pii", "finish": "finish"})
    builder.add_conditional_edges("pii", after_pii, {"policy": "policy", "finish": "finish"})
    builder.add_conditional_edges("policy", after_policy, {"approval": "approval", "execute": "execute", "finish": "finish"})
    builder.add_conditional_edges("approval", after_approval, {"execute": "execute", "finish": "finish"})
    builder.add_conditional_edges("execute", after_execute, {"execute": "execute", "finish": "finish"})
    builder.add_edge("finish", END)
    return builder.compile(checkpointer=MemorySaver())


def initial_state(**kwargs: Any) -> AegisState:
    """Build a valid serializable graph input."""
    return {
        "request_id": str(uuid4()),
        "status": "pending",
        "retry_count": 0,
        "max_retries": 2,
        "audit_events": [],
        **kwargs,
    }
