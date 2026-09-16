"""Serializable state carried by the AGIES LangGraph workflow."""

from __future__ import annotations

from typing import Any, TypedDict


class AegisState(TypedDict, total=False):
    request_id: str
    pipeline_id: str
    user_id: str
    role: str
    action: str
    source_dataset_id: str
    source_data_path: str
    output_name: str
    transformation_request: str
    risk_score: float
    pii_findings: list[dict[str, Any]]
    quality_score: float
    approval_required: bool
    approval_decision: str
    status: str
    current_step: str
    retry_count: int
    max_retries: int
    result: dict[str, Any]
    error: str
    audit_events: list[dict[str, Any]]
