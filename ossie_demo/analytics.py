"""Small deterministic analytical workflows built on the semantic planner."""
import calendar
import copy
import csv
import hashlib
import io
import json
import platform
import zipfile
from datetime import date, timedelta

import yaml

from .catalog import Catalog, SemanticError, expression
from .expression_ast import Aggregate, Binary, Column, Number, Unary, refs
from .planner import compile_query
from .planning.compiler import CompiledQuery
from .schemas import SemanticQuery


def fingerprint(catalog):
    payload = {'model': catalog.raw, 'values': catalog.filter_values}
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def metric_details(catalog, name):
    root = catalog.metric_base(name)
    tree = catalog.metric_ast[name]
    aggregates = []

    def visit(node):
        if isinstance(node, Aggregate):
            aggregates.append({'function': node.function, 'distinct': node.distinct,
                               'columns': ['.'.join(r) for r in sorted(refs(node))]})
        elif isinstance(node, Binary):
            visit(node.left)
            visit(node.right)
        elif isinstance(node, Unary):
            visit(node.operand)
    visit(tree)
    return {'name': name, 'description': catalog.metrics[name].get('description', ''),
            'formula': expression(catalog.metrics[name]), 'source': catalog.datasets[root]['source'],
            'columns': ['.'.join(r) for r in sorted(refs(tree))], 'aggregates': aggregates,
            'ratio': isinstance(tree, Binary) and tree.op == '/',
            'time_fields': [f'{ds}.{n}' for n, (ds, field) in catalog.dimensions.items()
                            if ds == root and field.get('dimension', {}).get('is_time')],
            'model_fingerprint': fingerprint(catalog)}


def execute(service, traces, snapshot=False):
    service.prepare_database()
    return service.database.execute_many(
        [CompiledQuery(t['sql'], t['parameters']) for t in traces],
        service.catalog if snapshot else None)


def full_plan(service, query, catalog=None):
    plan = compile_query(catalog or service.catalog, query, service.database.backend)
    # Internal analysis must not compare independently truncated Top-N lists.
    sql = plan.sql.rsplit(' LIMIT ', 1)[0]
    return {'sql': sql, 'parameters': plan.parameters,
            'semantic_query': query.model_dump(mode='json'), 'limit_applied': False,
            'model_fingerprint': fingerprint(catalog or service.catalog)}


def period_comparison(service, request):
    tree = service.catalog.metric_ast.get(request.metric)
    if not isinstance(tree, Aggregate) or tree.function not in ('SUM', 'COUNT') or tree.distinct:
        raise SemanticError('Contribution decomposition requires a SUM or non-distinct COUNT metric')
    previous, current = request.previous, request.current
    if current is None:
        first = date.today().replace(day=1)
        current_end = first - timedelta(days=1)
        current_start = current_end.replace(day=1)
        previous_end = current_start - timedelta(days=1)
        from .schemas import Period
        previous = Period(start=previous_end.replace(day=1), end=previous_end)
        current = Period(start=current_start, end=current_end)
    traces = [full_plan(service, SemanticQuery(metrics=[request.metric], dimensions=[request.dimension],
                    filters=request.filters, date_from=p.start, date_to=p.end)) for p in [previous, current]]
    data, _ = execute(service, traces)
    maps = [{row[request.dimension]: row[request.metric] for row in rows} for rows in data]
    keys = maps[0].keys() | maps[1].keys()
    rows = []
    for key in keys:
        before, after = maps[0].get(key), maps[1].get(key)
        rows.append({'group': key, 'previous': before, 'current': after,
                     'delta': (after or 0) - (before or 0),
                     'change_pct': ((after or 0) - before) / abs(before) * 100 if before else None})
    totals = [sum(v or 0 for v in m.values()) for m in maps]
    delta = totals[1] - totals[0]
    for row in rows:
        row['contribution_pct'] = row['delta'] / delta * 100 if delta else None
    rows.sort(key=lambda r: (r['delta'], str(r['group'])))
    displayed = rows[:request.top_n]
    return {'metric': request.metric, 'dimension': request.dimension,
            'previous_period': previous.model_dump(mode='json'),
            'current_period': current.model_dump(mode='json'),
            'previous': totals[0], 'current': totals[1], 'delta': delta,
            'change_pct': delta / abs(totals[0]) * 100 if totals[0] else None,
            'rows': displayed, 'group_count': len(rows),
            'other_delta': sum(r['delta'] for r in rows[request.top_n:]),
            'evidence': traces, 'causal_claim': False}


def drill_query(service, request):
    query = request.query.model_dump(mode='json')
    selected = request.selection
    allowed = set(query['dimensions']) | ({'time_period'} if query['time_grain'] else set())
    if not set(selected) <= allowed:
        raise SemanticError('Drill selection must use current grouping keys')
    if 'time_period' in selected:
        start = date.fromisoformat(selected['time_period'])
        grain = query['time_grain']
        if grain == 'month':
            if start.day != 1:
                raise SemanticError('Month selection must be a period start')
            end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        elif grain == 'week':
            if start.weekday() != 0:
                raise SemanticError('Week selection must start Monday')
            end = start + timedelta(days=6)
        else:
            end = start
        if query['date_from']:
            start = max(start, date.fromisoformat(query['date_from']))
        if query['date_to']:
            end = min(end, date.fromisoformat(query['date_to']))
        query.update(date_from=start.isoformat(), date_to=end.isoformat(), time_grain=None)
    for key, value in selected.items():
        if key == 'time_period':
            continue
        existing = query['filters'].get(key)
        if existing is not None and value not in (existing if isinstance(existing, list) else [existing]):
            raise SemanticError('Drill selection conflicts with existing filters')
        query['filters'][key] = value
    query['dimensions'] = [request.target]
    query['order_by'] = []
    resolved = SemanticQuery.model_validate(query)
    service.plan(resolved)  # Same compatibility checks as ordinary queries.
    return resolved


def drill_options(service, query):
    options = []
    for name, (_, field) in service.catalog.dimensions.items():
        if field.get('dimension', {}).get('is_time') or name in query.dimensions:
            continue
        candidate = query.model_copy(update={'dimensions': [name], 'order_by': []})
        try:
            service.plan(candidate)
            options.append({'dimension': name, 'available': True})
        except SemanticError as exc:
            options.append({'dimension': name, 'available': False, 'reason': str(exc)})
    return options


def model_comparison(service, request):
    if request.metric not in request.query.metrics:
        raise SemanticError('Changed metric must be selected in the comparison query')
    raw = copy.deepcopy(service.catalog.raw)
    item = next(m for m in raw['metrics'] if m['name'] == request.metric)
    old_expression = expression(item)
    item['expression'] = {'dialects': [{'dialect': 'ANSI_SQL', 'expression': request.expression}]}
    candidate = Catalog.from_raw(raw, service.catalog.filter_values)
    traces = [full_plan(service, request.query, catalog) for catalog in [service.catalog, candidate]]
    data, _ = execute(service, traces)
    dimensions = (['time_period'] if request.query.time_grain else []) + request.query.dimensions
    maps = [{tuple(row[d] for d in dimensions): row for row in rows} for rows in data]
    rows = []
    for key in sorted(maps[0].keys() | maps[1].keys(), key=str):
        before = maps[0].get(key, {}).get(request.metric)
        after = maps[1].get(key, {}).get(request.metric)
        rows.append({**dict(zip(dimensions, key)), 'previous': before, 'candidate': after,
                     'delta': after - before if before is not None and after is not None else None})
    return {'metric': request.metric, 'old_expression': old_expression,
            'candidate_expression': request.expression, 'rows': rows, 'evidence': traces,
            'old_fingerprint': fingerprint(service.catalog), 'candidate_fingerprint': fingerprint(candidate),
            'persisted': False}


def expression_source(node):
    """Serialize the restricted AST back into its own grammar, not SQL dialect syntax."""
    if isinstance(node, Column):
        return f'{node.dataset}.{node.name}'
    if isinstance(node, Number):
        return node.value
    if isinstance(node, Aggregate):
        return f'{node.function}({"DISTINCT " if node.distinct else ""}{expression_source(node.argument)})'
    if isinstance(node, Binary):
        return f'({expression_source(node.left)} {node.op} {expression_source(node.right)})'
    if isinstance(node, Unary):
        return f'(-{expression_source(node.operand)})'
    raise SemanticError('Unknown metric node')


def explain_value(service, query, metric):
    details = metric_details(service.catalog, metric)
    tree = service.catalog.metric_ast[metric]
    if details['ratio']:
        # Reuse the planner for numerator/denominator with exactly the same scope.
        raw = copy.deepcopy(service.catalog.raw)
        for name, node in [('explain_numerator', tree.left), ('explain_denominator', tree.right)]:
            if name in service.catalog.metrics:
                raise SemanticError('Reserved explanation metric name')
            raw['metrics'].append({'name': name, 'datatype': 'Decimal',
                'expression': {'dialects': [{'dialect': 'ANSI_SQL', 'expression': expression_source(node)}]}})
        candidate = Catalog.from_raw(raw, service.catalog.filter_values)
        q = query.model_copy(update={'metrics': ['explain_numerator', 'explain_denominator'], 'order_by': []})
        trace = full_plan(service, q, candidate)
        rows, _ = execute(service, [trace])
        details['components'] = rows[0]
        details['evidence'] = trace
    details['scope'] = query.model_dump(mode='json')
    return details


def reproduction(service, query):
    trace = service.plan(query)
    data, snapshot = execute(service, [trace], snapshot=True)
    result = {**trace, 'rows': data[0], 'model_fingerprint': fingerprint(service.catalog)}
    from . import __version__
    manifest = {'project_version': __version__, 'python_version': platform.python_version(), 'format_version': 1, 'backend': service.database.backend,
                'model_fingerprint': fingerprint(service.catalog),
                'snapshot_sha256': hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest(),
                'note': 'Fresh export execution and source data captured in one read transaction.'}
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in [('request.json', query.model_dump(mode='json')), ('result.json', result),
                            ('parameters.json', trace['parameters']), ('manifest.json', manifest),
                            ('data.json', snapshot)]:
            archive.writestr(name, json.dumps(value, ensure_ascii=False, indent=2))
        csv_file = io.StringIO()
        columns = list(data[0][0]) if data[0] else [d['name'] for d in trace['logical_plan']['dimensions']] + query.metrics
        writer = csv.DictWriter(csv_file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(data[0])
        archive.writestr('result.csv', csv_file.getvalue())
        archive.writestr('query.sql', trace['sql'])
        archive.writestr('model.yaml', yaml.safe_dump(service.catalog.raw))
        archive.writestr('model.values.yaml', yaml.safe_dump(service.catalog.filter_values))
        archive.writestr('replay.py', REPLAY)
        archive.writestr('README.md', '# Query reproduction\n\nRun `python replay.py` after extracting.\n'
            'DuckDB exports require duckdb; SQLite exports use the Python standard library.\n'
            'The package includes source rows from the model tables, not API tokens.\n'
            'Export executes a fresh query in the same snapshot as the included data.\n'
            'NULL and dates are preserved in JSON. Model and data hashes are in manifest.json.\n')
    return output.getvalue()


REPLAY = '''import json
import sqlite3
from pathlib import Path
from decimal import Decimal
from datetime import date
root = Path(__file__).resolve().parent
manifest = json.loads((root / 'manifest.json').read_text())
if manifest['backend'] == 'duckdb':
    import duckdb
    conn = duckdb.connect(':memory:')
else:
    conn = sqlite3.connect(':memory:')
def ident(value):
    return '"' + value.replace('"', '""') + '"'
for table in json.loads((root / 'data.json').read_text()):
    fields = table['fields']
    columns = ', '.join(ident(f['name']) + ' ' + dtype for f, dtype in zip(fields, table['column_types']))
    conn.execute('CREATE TABLE ' + ident(table['table']) + ' (' + columns + ')')
    if table['rows']:
        conn.executemany('INSERT INTO ' + ident(table['table']) + ' VALUES (' + ','.join('?' for _ in fields) + ')', table['rows'])
cursor = conn.execute((root / 'query.sql').read_text(), json.loads((root / 'parameters.json').read_text()))
columns = [c[0] for c in cursor.description]
rows = [dict(zip(columns, [float(v) if isinstance(v, Decimal) else v.isoformat() if isinstance(v, date) else v for v in row])) for row in cursor.fetchall()]
expected = json.loads((root / 'result.json').read_text())['rows']
assert rows == expected, 'Replay differs from exported result'
print(json.dumps(rows, ensure_ascii=False, indent=2))
print('Replay verified')
'''
