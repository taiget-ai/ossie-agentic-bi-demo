"""Time semantics use asserted calendar boundaries on both supported engines."""
import copy
from datetime import date

import pytest
import yaml
from fastapi.testclient import TestClient

from ossie_demo.api import create_app
from ossie_demo.catalog import SemanticError
from ossie_demo.parsing import rule_parse
from ossie_demo.schemas import SemanticQuery
from ossie_demo.service import SemanticService


@pytest.fixture
def calendar_service(service):
    conn = service.database.connect()
    try:
        conn.execute('DELETE FROM bets')
        conn.execute('DELETE FROM deposits')
        # Sunday, Monday/new year, month end, leap day, and a separate month.
        for i, day in enumerate(['2023-12-31', '2024-01-01', '2024-01-31', '2024-02-29'], 1):
            conn.execute('INSERT INTO bets VALUES (?, 1, 1, ?, ?, 0, 0)', [i, day, i * 10])
        for i, day in enumerate(['2024-01-01', '2024-02-29', '2024-03-01'], 1):
            conn.execute('INSERT INTO deposits VALUES (?, 1, ?, ?)', [i, day, i * 100])
        conn.commit()
    finally:
        conn.close()
    return service


@pytest.mark.parametrize(('grain', 'expected'), [
    ('day', [('2023-12-31', 10, None), ('2024-01-01', 20, 100),
             ('2024-01-31', 30, None), ('2024-02-29', 40, 200), ('2024-03-01', None, 300)]),
    ('week', [('2023-12-25', 10, None), ('2024-01-01', 20, 100),
              ('2024-01-29', 30, None), ('2024-02-26', 40, 500)]),
    ('month', [('2023-12-01', 10, None), ('2024-01-01', 50, 100),
               ('2024-02-01', 40, 200), ('2024-03-01', None, 300)]),
])
def test_cross_fact_calendar_alignment(calendar_service, grain, expected):
    result = calendar_service.query(SemanticQuery(
        metrics=['total_stake', 'total_deposit'], time_grain=grain))
    assert result['rows'] == [dict(zip(['time_period', 'total_stake', 'total_deposit'], row))
                              for row in expected]
    branches = result['logical_plan']['branches']
    assert [b['dimensions'][0]['column'] for b in branches] == ['bet_date', 'deposit_date']


def test_filter_precedes_grouping_and_ratio_is_recomputed(calendar_service):
    result = calendar_service.query(SemanticQuery(
        metrics=['total_stake', 'total_deposit', 'stake_per_bettor'],
        dimensions=['country'], time_grain='month',
        date_from=date(2024, 1, 15), date_to=date(2024, 2, 29)))
    assert [(r['time_period'], r['total_stake'], r['total_deposit'], r['stake_per_bettor'])
            for r in result['rows']] == [('2024-01-01', 30, None, 30), ('2024-02-01', 40, 200, 40)]
    single = calendar_service.query(SemanticQuery(metrics=['stake_per_bettor'], time_grain='month'))
    assert single['rows'][1] == {'time_period': '2024-01-01', 'stake_per_bettor': 50}


def test_empty_time_range_has_no_synthetic_buckets(calendar_service):
    assert calendar_service.query(SemanticQuery(metrics=['total_stake', 'total_deposit'],
        time_grain='week', date_from=date(2099, 1, 1)))['rows'] == []


@pytest.mark.parametrize('grain', ['day', 'week', 'month'])
def test_rule_parser_and_api_time_contract(service, grain):
    req = rule_parse(f'Show total stake and total deposit by {grain} and country', service.catalog)
    assert req.time_grain == grain
    assert req.dimensions == ['country']
    response = TestClient(create_app(service)).post('/api/query', json=req.model_dump(mode='json'))
    assert response.status_code == 200
    assert all('time_period' in row for row in response.json()['rows'])


def test_reject_ambiguous_time_contract(service, tmp_path):
    with pytest.raises(ValueError):
        SemanticQuery(metrics=['total_stake'], time_grain='quarter')
    with pytest.raises(SemanticError, match='raw time'):
        service.plan(SemanticQuery(metrics=['total_stake'], dimensions=['bet_date'], time_grain='day'))
    with pytest.raises(SemanticError, match='one time grain'):
        rule_parse('Show total stake by month and per week', service.catalog)
    model = copy.deepcopy(service.catalog.raw)
    bets = next(d for d in model['datasets'] if d['name'] == 'bets')
    next(f for f in bets['fields'] if f['name'] == 'bet_date')['dimension']['is_time'] = False
    path = tmp_path / 'no-time.yaml'
    path.write_text(yaml.safe_dump(model))
    with pytest.raises(SemanticError, match='exactly one time dimension'):
        SemanticService(path, database=service.database).plan(
            SemanticQuery(metrics=['total_stake'], time_grain='month'))
