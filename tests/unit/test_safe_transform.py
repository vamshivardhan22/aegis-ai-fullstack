"""Unit tests for the declarative transformation engine."""
import pandas as pd
import pytest

from src.agents.safe_transform import apply_transformation_plan
from src.core.exceptions import ValidationError


def test_filter_cast_and_group_aggregation() -> None:
    source = pd.DataFrame({"category": ["A", "A", "B"], "amount": ["10", "20", "-2"]})
    result = apply_transformation_plan(source, {"operations": [
        {"op": "cast", "columns": {"amount": "integer"}},
        {"op": "filter", "column": "amount", "operator": "gte", "value": 0},
        {"op": "groupby_agg", "group_by": ["category"], "aggregations": {"amount": "sum"}},
    ]})
    assert result.to_dict("records") == [{"category": "A", "amount": 30}]


def test_unknown_column_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown columns"):
        apply_transformation_plan(pd.DataFrame({"a": [1]}), {"operations": [
            {"op": "drop_columns", "columns": ["missing"]},
        ]})


def test_arbitrary_code_is_not_an_operation() -> None:
    with pytest.raises(ValidationError, match="Unsupported transformation operation"):
        apply_transformation_plan(pd.DataFrame({"a": [1]}), {"operations": [
            {"op": "exec", "code": "malicious payload"},
        ]})


def test_duplicate_names_after_rename_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate column"):
        apply_transformation_plan(pd.DataFrame({"a": [1], "b": [2]}), {"operations": [
            {"op": "rename_columns", "mapping": {"a": "b"}},
        ]})


def test_plan_shape_and_step_limit_are_enforced() -> None:
    with pytest.raises(ValidationError, match="only an operations list"):
        apply_transformation_plan(pd.DataFrame({"a": [1]}), {"code": "result=df"})
    with pytest.raises(ValidationError, match="at most 25"):
        apply_transformation_plan(pd.DataFrame({"a": [1]}), {"operations": [{}] * 26})

def test_duplicate_removal_and_safe_feature_derivation() -> None:
    source = pd.DataFrame({
        "category": [" A ", " A ", "B"],
        "unit_price": [10.0, 10.0, 5.0],
        "quantity": [2, 2, 3],
        "created_at": ["2026-01-02", "2026-01-02", "2026-02-03"],
    })
    result = apply_transformation_plan(source, {"operations": [
        {"op": "drop_duplicates"},
        {"op": "derive_numeric", "name": "revenue", "left": "unit_price", "operator": "multiply", "right_column": "quantity"},
        {"op": "derive_string", "name": "category_clean", "column": "category", "operation": "strip"},
        {"op": "derive_datetime", "name": "created_year", "column": "created_at", "part": "year"},
    ]})
    assert len(result) == 2
    assert result.loc[0, "revenue"] == 20.0
    assert result.loc[0, "category_clean"] == "A"
    assert result.loc[0, "created_year"] == 2026


def test_numeric_feature_division_by_zero_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Numeric feature derivation failed"):
        apply_transformation_plan(pd.DataFrame({"a": [4], "b": [0]}), {"operations": [
            {"op": "derive_numeric", "name": "ratio", "left": "a", "operator": "divide", "right_column": "b"},
        ]})


def test_feature_overwrite_is_rejected() -> None:
    with pytest.raises(ValidationError, match="already exists"):
        apply_transformation_plan(pd.DataFrame({"a": [1]}), {"operations": [
            {"op": "derive_numeric", "name": "a", "left": "a", "operator": "add", "value": 1},
        ]})
