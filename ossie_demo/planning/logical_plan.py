"""Inspectible, SQL-independent logical plan with per-fact aggregate branches."""
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class LogicalMetric:
    name: str
    expression: str
    dataset: str


@dataclass(frozen=True)
class LogicalDimension:
    name: str
    dataset: str
    column: str
    time_grain: Literal["day", "week", "month"] | None = None


@dataclass(frozen=True)
class LogicalJoin:
    name: str
    left_dataset: str
    right_dataset: str
    right_table: str
    left_columns: tuple[str, ...]
    right_columns: tuple[str, ...]
    join_type: Literal['left'] = 'left'


@dataclass(frozen=True)
class LogicalPredicate:
    dataset: str
    column: str
    operator: Literal['eq', 'in', 'gte', 'lte']
    value: Any


@dataclass(frozen=True)
class AggregateBranch:
    """One aggregate per fact grain; no fact-to-fact row-level joins."""
    root_dataset: str
    root_table: str
    metrics: tuple[LogicalMetric, ...]
    dimensions: tuple[LogicalDimension, ...]
    joins: tuple[LogicalJoin, ...]
    predicates: tuple[LogicalPredicate, ...]


@dataclass(frozen=True)
class LogicalQueryPlan:
    root_dataset: str               # name when single fact, 'multiple' otherwise
    root_table: str
    metrics: tuple[LogicalMetric, ...]
    dimensions: tuple[LogicalDimension, ...]
    joins: tuple[LogicalJoin, ...]  # single-branch convenience; multi uses branches
    predicates: tuple[LogicalPredicate, ...]
    branches: tuple[AggregateBranch, ...]
    order_by: tuple[str, ...]
    limit: int
    strategy: Literal['single_fact', 'aggregate_then_join']
    sort_keys: tuple[tuple[str, str], ...] = ()
