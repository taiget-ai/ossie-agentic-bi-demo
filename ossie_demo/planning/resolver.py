"""Semantic intent -> logical branch plan, grouping metrics by fact grain."""
from collections import defaultdict

from ..catalog import Catalog, SemanticError, expression
from ..schemas import SemanticQuery
from .joins import find_join_paths
from .logical_plan import (
    AggregateBranch,
    LogicalDimension,
    LogicalJoin,
    LogicalMetric,
    LogicalPredicate,
    LogicalQueryPlan,
)


def resolve_query(catalog: Catalog, request: SemanticQuery) -> LogicalQueryPlan:
    dimensions = []
    for name in request.dimensions:
        if name not in catalog.dimensions:
            raise SemanticError(f"unknown dimension: {name}")
        dataset, _ = catalog.dimensions[name]
        dimensions.append(LogicalDimension(name, dataset, name))

    for name, value in request.filters.items():
        if name not in catalog.dimensions:
            raise SemanticError(f"filter must use a declared dimension: {name}")
        values = value if isinstance(value, list) else [value]
        if not values or any(not isinstance(v, str) or len(v) > 80 for v in values):
            raise SemanticError(f"invalid filter value for {name}")

    if request.time_grain:
        if 'time_period' in catalog.dimensions or 'time_period' in request.metrics:
            raise SemanticError("time_period is reserved for time grouping output")
        if any(catalog.dimensions[d][1].get('dimension', {}).get('is_time')
               for d in request.dimensions):
            raise SemanticError("time_grain cannot be combined with a raw time dimension")

    metrics = []
    grouped = defaultdict(list)
    for name in request.metrics:
        root = catalog.metric_base(name)
        metric = LogicalMetric(name, expression(catalog.metrics[name]), root)
        metrics.append(metric)
        grouped[root].append(metric)

    branches = []
    for root, root_metrics in grouped.items():
        branch_dimensions = list(dimensions)
        predicates = []
        for name, value in sorted(request.filters.items()):
            dataset, _ = catalog.dimensions[name]
            predicates.append(LogicalPredicate(dataset, name, 'in' if isinstance(value, list) else 'eq', value))
        if request.date_from or request.date_to or request.time_grain:
            time_dims = [(name, dataset) for name, (dataset, field) in catalog.dimensions.items()
                         if field.get('dimension', {}).get('is_time') and dataset == root]
            if len(time_dims) != 1:
                raise SemanticError(f"time queries need exactly one time dimension on fact {root}")
            time_name, time_dataset = time_dims[0]
            if request.time_grain:
                if catalog.dimensions[time_name][1].get('datatype') != 'Date':
                    raise SemanticError("time grouping currently requires a Date field")
                branch_dimensions.insert(0, LogicalDimension(
                    'time_period', time_dataset, time_name, request.time_grain))
            if request.date_from:
                predicates.append(LogicalPredicate(time_dataset, time_name, 'gte', request.date_from.isoformat()))
            if request.date_to:
                predicates.append(LogicalPredicate(time_dataset, time_name, 'lte', request.date_to.isoformat()))
        targets = {d.dataset for d in branch_dimensions} | {p.dataset for p in predicates}
        edges = find_join_paths(catalog, root, targets)
        joins = tuple(LogicalJoin(
            name=r['name'], left_dataset=r['from'], right_dataset=r['to'],
            right_table=catalog.datasets[r['to']]['source'],
            left_columns=tuple(r['from_columns']), right_columns=tuple(r['to_columns']),
        ) for r in edges)
        branches.append(AggregateBranch(
            root_dataset=root,
            root_table=catalog.datasets[root]['source'],
            metrics=tuple(root_metrics), dimensions=tuple(branch_dimensions),
            joins=joins, predicates=tuple(predicates),
        ))

    if request.time_grain:
        # Output key is shared; its physical field belongs to each branch.
        dimensions.insert(0, LogicalDimension('time_period', '', '', request.time_grain))
    single = len(branches) == 1
    only = branches[0]
    return LogicalQueryPlan(
        root_dataset=only.root_dataset if single else 'multiple',
        root_table=only.root_table if single else '',
        metrics=tuple(metrics), dimensions=tuple(dimensions),
        joins=only.joins if single else (),
        predicates=only.predicates if single else (),
        branches=tuple(branches),
        order_by=tuple(d.name for d in dimensions), limit=request.limit,
        sort_keys=tuple((key.field, key.direction) for key in request.order_by),
        strategy='single_fact' if single else 'aggregate_then_join',
    )
