"""Safe, deterministic execution of declarative dataframe transformation plans."""
from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from src.core.exceptions import ValidationError

_ALLOWED_FILTERS = {
    "eq": lambda series, value: series == value,
    "ne": lambda series, value: series != value,
    "gt": lambda series, value: series > value,
    "gte": lambda series, value: series >= value,
    "lt": lambda series, value: series < value,
    "lte": lambda series, value: series <= value,
    "contains": lambda series, value: series.astype("string").str.contains(str(value), regex=False, na=False),
    "is_null": lambda series, value: series.isna(),
    "not_null": lambda series, value: series.notna(),
}
_ALLOWED_AGGREGATIONS = {"sum", "mean", "min", "max", "count", "nunique"}
_ALLOWED_DTYPES = {"string", "integer", "float", "boolean", "datetime"}
_ALLOWED_NUMERIC_DERIVATIONS = {"add", "subtract", "multiply", "divide"}
_ALLOWED_STRING_DERIVATIONS = {"lower", "upper", "strip", "length"}
_ALLOWED_DATE_PARTS = {"year", "month", "day"}
_COLUMN_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValidationError("Transformation references unknown columns", {"columns": missing})


def _new_column_name(frame: pd.DataFrame, name: Any) -> str:
    if not isinstance(name, str) or not _COLUMN_NAME.fullmatch(name):
        raise ValidationError("Derived column name must be a simple identifier of at most 64 characters")
    if name in frame.columns:
        raise ValidationError("Derived column already exists; overwrite is not allowed", {"column": name})
    return name


def apply_transformation_plan(frame: pd.DataFrame, plan: dict[str, Any]) -> pd.DataFrame:
    """Apply allow-listed operations; never evaluate Python, SQL, or shell from a model."""
    if not isinstance(plan, dict) or set(plan) != {"operations"}:
        raise ValidationError("Plan must contain only an operations list")
    operations = plan["operations"]
    if not isinstance(operations, list) or len(operations) > 25:
        raise ValidationError("Plan operations must be a list containing at most 25 steps")

    result = frame.copy(deep=True)
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or not isinstance(operation.get("op"), str):
            raise ValidationError("Each operation must be an object with an op field", {"step": index})
        op = operation["op"]
        if op == "select_columns":
            columns = operation.get("columns")
            if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
                raise ValidationError("select_columns requires a list of column names", {"step": index})
            _require_columns(result, columns)
            result = result.loc[:, columns].copy()
        elif op == "drop_columns":
            columns = operation.get("columns")
            if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
                raise ValidationError("drop_columns requires a list of column names", {"step": index})
            _require_columns(result, columns)
            result = result.drop(columns=columns)
        elif op == "drop_duplicates":
            subset = operation.get("subset")
            keep = operation.get("keep", "first")
            if subset is not None:
                if not isinstance(subset, list) or not all(isinstance(column, str) for column in subset):
                    raise ValidationError("drop_duplicates subset must be a list of column names", {"step": index})
                _require_columns(result, subset)
            if keep not in ("first", "last", False):
                raise ValidationError("drop_duplicates keep must be first, last, or false", {"step": index})
            result = result.drop_duplicates(subset=subset, keep=keep).copy()
        elif op == "rename_columns":
            mapping = operation.get("mapping")
            if not isinstance(mapping, dict) or not mapping or not all(
                isinstance(key, str) and isinstance(value, str) and value.strip()
                for key, value in mapping.items()
            ):
                raise ValidationError("rename_columns requires a non-empty string mapping", {"step": index})
            _require_columns(result, list(mapping))
            new_names = [mapping.get(column, column) for column in result.columns]
            if len(new_names) != len(set(new_names)):
                raise ValidationError("Renaming would create duplicate column names", {"step": index})
            result = result.rename(columns=mapping)
        elif op == "fillna":
            columns = operation.get("columns")
            if not isinstance(columns, list) or not columns or not all(isinstance(column, str) for column in columns):
                raise ValidationError("fillna requires a non-empty columns list", {"step": index})
            _require_columns(result, columns)
            if "value" not in operation or isinstance(operation["value"], (dict, list)):
                raise ValidationError("fillna requires a scalar value", {"step": index})
            result.loc[:, columns] = result.loc[:, columns].fillna(operation["value"])
        elif op == "filter":
            column, operator = operation.get("column"), operation.get("operator")
            if not isinstance(column, str) or not isinstance(operator, str) or operator not in _ALLOWED_FILTERS:
                raise ValidationError("filter uses an unsupported column or operator", {"step": index})
            _require_columns(result, [column])
            try:
                result = result.loc[_ALLOWED_FILTERS[operator](result[column], operation.get("value"))].copy()
            except (TypeError, ValueError) as exc:
                raise ValidationError("Filter value is incompatible with the selected column", {"step": index}) from exc
        elif op == "groupby_agg":
            groups, aggregations = operation.get("group_by"), operation.get("aggregations")
            if not isinstance(groups, list) or not groups or not all(isinstance(column, str) for column in groups):
                raise ValidationError("groupby_agg requires a non-empty group_by list", {"step": index})
            if not isinstance(aggregations, dict) or not aggregations:
                raise ValidationError("groupby_agg requires an aggregation mapping", {"step": index})
            _require_columns(result, groups + list(aggregations))
            if not all(isinstance(column, str) and isinstance(aggregation, str) and aggregation in _ALLOWED_AGGREGATIONS for column, aggregation in aggregations.items()):
                raise ValidationError("groupby_agg contains an unsupported aggregation", {"step": index})
            result = result.groupby(groups, dropna=False, as_index=False).agg(aggregations)
        elif op == "cast":
            columns = operation.get("columns")
            if not isinstance(columns, dict) or not columns:
                raise ValidationError("cast requires a column-to-type mapping", {"step": index})
            _require_columns(result, list(columns))
            for column, dtype in columns.items():
                if not isinstance(dtype, str) or dtype not in _ALLOWED_DTYPES:
                    raise ValidationError("cast uses an unsupported dtype", {"step": index, "dtype": dtype})
                try:
                    if dtype == "string":
                        result[column] = result[column].astype("string")
                    elif dtype == "integer":
                        result[column] = pd.to_numeric(result[column], errors="raise").astype("Int64")
                    elif dtype == "float":
                        result[column] = pd.to_numeric(result[column], errors="raise").astype("float64")
                    elif dtype == "boolean":
                        normalized = result[column].astype("string").str.lower()
                        mapping = {"true": True, "false": False, "1": True, "0": False}
                        invalid = normalized.notna() & ~normalized.isin(mapping)
                        if invalid.any():
                            raise ValueError("non-boolean value")
                        result[column] = normalized.map(mapping).astype("boolean")
                    else:
                        result[column] = pd.to_datetime(result[column], errors="raise")
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValidationError("Cast failed for column", {"step": index, "column": column}) from exc
        elif op == "derive_numeric":
            name = _new_column_name(result, operation.get("name"))
            left_column, operator = operation.get("left"), operation.get("operator")
            right_column = operation.get("right_column")
            has_value = "value" in operation
            if not isinstance(left_column, str) or not isinstance(operator, str) or operator not in _ALLOWED_NUMERIC_DERIVATIONS:
                raise ValidationError("derive_numeric requires a source column and supported operator", {"step": index})
            if (right_column is None) == (not has_value):
                raise ValidationError("derive_numeric requires exactly one of right_column or value", {"step": index})
            _require_columns(result, [left_column] + ([right_column] if right_column is not None else []))
            try:
                left = pd.to_numeric(result[left_column], errors="raise")
                if right_column is not None:
                    right = pd.to_numeric(result[right_column], errors="raise")
                else:
                    value = operation["value"]
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                        raise ValueError("value must be a finite number")
                    right = value
                if operator == "add":
                    derived = left + right
                elif operator == "subtract":
                    derived = left - right
                elif operator == "multiply":
                    derived = left * right
                else:
                    if isinstance(right, pd.Series) and (right == 0).any():
                        raise ValueError("division by zero")
                    if not isinstance(right, pd.Series) and right == 0:
                        raise ValueError("division by zero")
                    derived = left / right
                result[name] = derived
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValidationError("Numeric feature derivation failed", {"step": index}) from exc
        elif op == "derive_string":
            name = _new_column_name(result, operation.get("name"))
            source, action = operation.get("column"), operation.get("operation")
            if not isinstance(source, str) or not isinstance(action, str) or action not in _ALLOWED_STRING_DERIVATIONS:
                raise ValidationError("derive_string uses an unsupported source or operation", {"step": index})
            _require_columns(result, [source])
            series = result[source].astype("string")
            if action == "lower":
                result[name] = series.str.lower()
            elif action == "upper":
                result[name] = series.str.upper()
            elif action == "strip":
                result[name] = series.str.strip()
            else:
                result[name] = series.str.len().astype("Int64")
        elif op == "derive_datetime":
            name = _new_column_name(result, operation.get("name"))
            source, part = operation.get("column"), operation.get("part")
            if not isinstance(source, str) or not isinstance(part, str) or part not in _ALLOWED_DATE_PARTS:
                raise ValidationError("derive_datetime uses an unsupported source or date part", {"step": index})
            _require_columns(result, [source])
            try:
                dates = pd.to_datetime(result[source], errors="raise")
                result[name] = getattr(dates.dt, part).astype("Int64")
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValidationError("Date feature derivation failed", {"step": index}) from exc
        else:
            raise ValidationError("Unsupported transformation operation", {"step": index, "op": op})

        if len(result.columns) == 0:
            raise ValidationError("Transformation cannot produce a dataset with zero columns", {"step": index})
        if len(result.columns) > 500:
            raise ValidationError("Transformation output exceeds the 500-column limit", {"step": index})
    return result
