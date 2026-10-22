"""Unit tests for the governed CSV workflow's deterministic data policies."""
import pandas as pd

from src.workflows.csv_pipeline import _detect_pii, _mask_value, _profile


def test_column_hints_detect_sensitive_fields() -> None:
    frame = pd.DataFrame({
        "customer_email": ["a@example.com", "b@example.com"],
        "phone_number": ["+1 555 123 4567", "+1 555 765 4321"],
        "order_total": [12.5, 18.0],
    })
    detected = _detect_pii(frame)
    assert detected["customer_email"] == "email"
    assert detected["phone_number"] == "phone"
    assert "order_total" not in detected


def test_value_patterns_detect_email_data_without_sensitive_column_names() -> None:
    frame = pd.DataFrame({"contact": ["a@example.com", "b@example.org", "c@example.net"]})
    assert _detect_pii(frame)["contact"] == "email"


def test_masking_is_deterministic_and_does_not_return_email() -> None:
    value = "customer@example.com"
    masked = _mask_value(value, "email")
    assert masked != value
    assert "customer" not in masked
    assert masked == _mask_value(value, "email")


def test_financial_identifier_mask_keeps_only_trailing_characters() -> None:
    masked = _mask_value("4111 1111 1111 1111", "financial_identifier")
    assert masked.endswith("1111")
    assert "4111 1111 1111" not in masked


def test_profile_records_nulls_duplicates_and_checksum() -> None:
    frame = pd.DataFrame({"id": [1, 1, 2], "value": ["x", "x", None]})
    profile = _profile(frame, b"id,value\n1,x\n1,x\n2,\n")
    assert profile["row_count"] == 3
    assert profile["column_count"] == 2
    assert profile["null_cells"] == 1
    assert profile["duplicate_rows"] == 1
    assert len(profile["source_sha256"]) == 64
    assert 0 <= profile["quality_score"] <= 1
