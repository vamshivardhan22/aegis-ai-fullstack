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
