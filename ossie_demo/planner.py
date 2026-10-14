"""Compatibility facade for the two-stage logical-plan query pipeline."""
from dataclasses import dataclass
from typing import Any

from .catalog import Catalog
from .planning import LogicalQueryPlan, compile_sql, resolve_query
from .schemas import SemanticQuery


@dataclass(frozen=True)
class QueryPlan:
    sql: str
    parameters: list[Any]
    metrics: list[str]
    dimensions: list[str]
    join_path: list[str]
    explanation: list[str]
    logical_plan: LogicalQueryPlan


def compile_query(catalog: Catalog, request: SemanticQuery, dialect: str = 'duckdb') -> QueryPlan:
    """SemanticQuery -> LogicalQueryPlan -> SQL, with both stages inspectable."""
    logical = resolve_query(catalog, request)
    compiled = compile_sql(logical, dialect)
    explanation = [
        f"Metric {m.name}: {m.expression}" for m in logical.metrics
    ] + [
        f"Planning strategy: {logical.strategy}",
        "Fact grains: " + ", ".join(b.root_dataset for b in logical.branches),
        f"Dimensions: {', '.join(d.name for d in logical.dimensions) or '(grand total)'}",
        "Join direction: many-to-one only (" +
        (", ".join(j.name for b in logical.branches for j in b.joins) or "none") + ")",
        "Filter values are SQL parameters, never interpolated.",
    ]
    if request.time_grain:
        explanation += [
            f"Time grouping: {request.time_grain}; weeks start Monday; dates label period starts.",
            "Date filters apply before grouping; boundary periods can be partial.",
            "Only observed periods are returned; missing fact values remain NULL.",
        ] + [f"{b.root_dataset}: {b.dimensions[0].column} -> time_period"
             for b in logical.branches]
    return QueryPlan(
        sql=compiled.sql,
        parameters=compiled.parameters,
        metrics=list(request.metrics),
        dimensions=list(request.dimensions),
        join_path=list(dict.fromkeys(j.name for b in logical.branches for j in b.joins)),
        explanation=explanation,
        logical_plan=logical,
    )
