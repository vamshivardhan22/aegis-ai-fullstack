"""Native LangGraph workflow for governed AGIES execution.

The graph is intentionally dependency-light: domain agents remain responsible for
business work while this graph owns governance, approval, retries, and lifecycle state.
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph


class AegisGraphState(TypedDict, total=False):
    """State persisted across one governed execution."""

    request_id: str
    pipeline_id: str
    user_id: str
    role: str
    action: str
    risk_score: float
    approval_required: bool
    approval_decision: str
    status: str
    current_step: str
    retry_count: int
    max_retries: int
    error: str
    result: dict[str, Any]
    audit_events: list[dict[str, Any]]


def _audit(state: AegisGraphState, event: str, **details: Any) -> list[dict[str, Any]]:
    events = list(state.get("audit_events", []))
    events.append({"event": event, "details": details})
    return events


def authenticate(state: AegisGraphState) -> AegisGraphState:
    if not state.get("user_id") or not state.get("role"):
        return {**state, "status": "failed", "error": "Authentication context is required", "current_step": "authenticate"}
    return {**state, "status": "running", "current_step": "authenticate", "audit_events": _audit(state, "AUTHENTICATED")}


def authorize(state: AegisGraphState) -> AegisGraphState:
    allowed_roles = {"admin", "data_engineer"}
    if state.get("action") in {"execute_agent", "transform", "deploy"} and state.get("role") not in allowed_roles:
        return {**state, "status": "failed", "error": "Role is not authorized for this action", "current_step": "authorize", "audit_events": _audit(state, "ACCESS_DENIED")}
    return {**state, "current_step": "authorize", "audit_events": _audit(state, "AUTHORIZED")}


def evaluate_policy(state: AegisGraphState) -> AegisGraphState:
    score = float(state.get("risk_score", 0.0))
    required = score >= 0.7 or state.get("action") in {"deploy", "delete", "pii_release"}
    return {**state, "approval_required": required, "current_step": "policy", "audit_events": _audit(state, "POLICY_EVALUATED", risk_score=score, approval_required=required)}


def approval_route(state: AegisGraphState) -> str:
    if state.get("status") == "failed":
        return "finish"
    if state.get("approval_required") and state.get("approval_decision") != "approved":
        return "approval"
    return "execute"


def approval_node(state: AegisGraphState) -> AegisGraphState:
    decision = state.get("approval_decision", "pending")
    if decision == "rejected":
        return {**state, "status": "rejected", "current_step": "approval", "audit_events": _audit(state, "HUMAN_DECISION", decision="rejected")}
    return {**state, "status": "approval_required", "current_step": "approval", "audit_events": _audit(state, "APPROVAL_PENDING")}


def execute(state: AegisGraphState) -> AegisGraphState:
    """Execution boundary; concrete agents can be injected by the API layer."""
    return {
        **state,
        "status": "completed",
        "current_step": "execute",
        "result": {"action": state.get("action"), "executed": True},
        "audit_events": _audit(state, "EXECUTION_COMPLETED"),
    }


def finish(state: AegisGraphState) -> AegisGraphState:
    return {**state, "current_step": "finish"}


def build_aegis_graph() -> Any:
    """Compile the native LangGraph governance graph."""
    builder = StateGraph(AegisGraphState)
    builder.add_node("authenticate", authenticate)
    builder.add_node("authorize", authorize)
    builder.add_node("policy", evaluate_policy)
    builder.add_node("approval", approval_node)
    builder.add_node("execute", execute)
    builder.add_node("finish", finish)
    builder.add_edge(START, "authenticate")
    builder.add_edge("authenticate", "authorize")
    builder.add_edge("authorize", "policy")
    builder.add_conditional_edges("policy", approval_route, {"approval": "approval", "execute": "execute", "finish": "finish"})
    builder.add_edge("approval", "finish")
    builder.add_edge("execute", "finish")
    builder.add_edge("finish", END)
    return builder.compile()
