"""Compile safe logical branches; reconcile heterogeneous fact grains only after aggregation."""
from dataclasses import dataclass
from typing import Any

from ..catalog import SemanticError, identifier
from ..expression_ast import compile_expr, parse_metric
from .logical_plan import AggregateBranch, LogicalQueryPlan


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    parameters: list[Any]


def qualified(dataset: str, column: str) -> str:
    return f'{identifier(dataset)}.{identifier(column)}'


def metric_expression(source: str) -> str:
    return compile_expr(parse_metric(source))


def dimension_expression(dimension, dialect):
    column = qualified(dimension.dataset, dimension.column)
    grain = dimension.time_grain
    if grain is None:
        return column
    if grain not in ('day', 'week', 'month'):
        raise SemanticError("unsupported time grain")
    if dialect == 'duckdb':
        return f"CAST(DATE_TRUNC('{grain}', {column}) AS DATE)"
    if grain == 'day':
        return f"DATE({column})"
    if grain == 'month':
        return f"DATE({column}, 'start of month')"
    # Monday at or before the input date, including Mondays themselves.
    return f"DATE({column}, '-' || ((CAST(STRFTIME('%w', {column}) AS INTEGER) + 6) % 7) || ' days')"


def compile_branch(branch: AggregateBranch, dialect: str = 'duckdb') -> CompiledQuery:
    selects = [f'{dimension_expression(d, dialect)} AS {identifier(d.name)}'
               for d in branch.dimensions]
    selects += [f'{metric_expression(m.expression)} AS {identifier(m.name)}'
                for m in branch.metrics]
    sql = (f'SELECT {", ".join(selects)} FROM {identifier(branch.root_table)} '
           f'AS {identifier(branch.root_dataset)}')
    for join in branch.joins:
        conditions = ' AND '.join(
            f'{qualified(join.left_dataset, left)} = {qualified(join.right_dataset, right)}'
            for left, right in zip(join.left_columns, join.right_columns)
        )
        sql += (f' LEFT JOIN {identifier(join.right_table)} AS {identifier(join.right_dataset)}'
                f' ON {conditions}')
    params = []
    predicates = []
    symbols = {'eq': '=', 'gte': '>=', 'lte': '<='}
    for p in branch.predicates:
        if p.operator == 'in':
            predicates.append(f'{qualified(p.dataset, p.column)} IN ({", ".join("?" for _ in p.value)})')
            params.extend(p.value)
        else:
            predicates.append(f'{qualified(p.dataset, p.column)} {symbols[p.operator]} ?')
            params.append(p.value)
    if predicates:
        sql += ' WHERE ' + ' AND '.join(predicates)
    if branch.dimensions:
        sql += ' GROUP BY ' + ', '.join(str(i) for i in range(1, len(branch.dimensions) + 1))
    return CompiledQuery(sql, params)


def compile_sql(plan: LogicalQueryPlan, dialect: str = 'duckdb') -> CompiledQuery:
    if dialect not in ('duckdb', 'sqlite'):
        raise SemanticError("unsupported SQL dialect")
    branches = [compile_branch(b, dialect) for b in plan.branches]
    params = [p for b in branches for p in b.parameters]
    sort_keys = list(plan.sort_keys)
    sort_keys += [(d.name, 'asc') for d in plan.dimensions if d.name not in {k[0] for k in sort_keys}]
    order = (' ORDER BY ' + ', '.join(f'{identifier(name)} {direction.upper()} NULLS LAST'
                                    for name, direction in sort_keys)) if sort_keys else ''
    if plan.strategy == 'single_fact':
        sql = branches[0].sql
        sql += order
        return CompiledQuery(f'{sql} LIMIT {plan.limit}', params)

    # One independent aggregate for each fact grain. A fact-to-fact JOIN before
    # aggregation (bets x deposits) would multiply money amounts. We instead
    # build a union of all dimension keys and left-join aggregate subqueries.
    ctes = [f'b{i} AS ({b.sql})' for i, b in enumerate(branches)]
    if plan.dimensions:
        dim_columns = ', '.join(identifier(d.name) for d in plan.dimensions)
        keys = ' UNION '.join(f'SELECT {dim_columns} FROM b{i}' for i in range(len(branches)))
        ctes.append(f'group_keys AS ({keys})')
        selects = [f'group_keys.{identifier(d.name)} AS {identifier(d.name)}' for d in plan.dimensions]
        sources = {m.name: i for i, branch in enumerate(plan.branches) for m in branch.metrics}
        selects += [f'b{sources[m.name]}.{identifier(m.name)} AS {identifier(m.name)}'
                    for m in plan.metrics]
        sql = f'WITH {", ".join(ctes)} SELECT {", ".join(selects)} FROM group_keys'
        for i in range(len(branches)):
            on = ' AND '.join(
                f'(group_keys.{identifier(d.name)} = b{i}.{identifier(d.name)} OR '
                f'(group_keys.{identifier(d.name)} IS NULL AND b{i}.{identifier(d.name)} IS NULL))'
                for d in plan.dimensions
            )
            sql += f' LEFT JOIN b{i} ON {on}'

    else:
        sources = {m.name: i for i, branch in enumerate(plan.branches) for m in branch.metrics}
        selects = [f'b{sources[m.name]}.{identifier(m.name)} AS {identifier(m.name)}'
                   for m in plan.metrics]
        sql = f'WITH {", ".join(ctes)} SELECT {", ".join(selects)} FROM '
        sql += ' CROSS JOIN '.join(f'b{i}' for i in range(len(branches)))
    return CompiledQuery(f'{sql}{order} LIMIT {plan.limit}', params)
