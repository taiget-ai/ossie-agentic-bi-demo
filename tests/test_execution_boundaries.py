"""Result assertions run against real DuckDB and SQLite, including missing facts."""
import sqlite3
from datetime import date

import duckdb
import pytest
from fastapi.testclient import TestClient

from ossie_demo.api import create_app
from ossie_demo.database import Database
from ossie_demo.planning.compiler import CompiledQuery
from ossie_demo.schemas import SemanticQuery
from ossie_demo.service import SemanticService


def mutate(service, *statements):
    conn = service.database.connect()
    try:
        for statement in statements:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


def test_empty_aggregates_preserve_null_and_count_semantics(service):
    request = SemanticQuery(metrics=['total_stake', 'bet_count', 'stake_per_bettor',
                                     'total_deposit', 'deposit_count'],
                            date_from=date(2099, 1, 1))
    assert service.query(request)['rows'] == [{
        'total_stake': None, 'bet_count': 0, 'stake_per_bettor': None,
        'total_deposit': None, 'deposit_count': 0,
    }]
    assert service.query(request.model_copy(update={'dimensions': ['country']}))['rows'] == []


def test_keys_present_in_only_one_fact_are_preserved(service):
    mutate(service,
           "DELETE FROM bets WHERE player_id IN (SELECT player_id FROM players WHERE country='DE')",
           "DELETE FROM deposits WHERE player_id IN (SELECT player_id FROM players WHERE country='FI')")
    assert service.query(SemanticQuery(metrics=['total_stake', 'total_deposit'],
                                      dimensions=['country']))['rows'] == [
        {'country': 'DE', 'total_stake': None, 'total_deposit': 200},
        {'country': 'FI', 'total_stake': 240, 'total_deposit': None},
        {'country': 'SG', 'total_stake': 420, 'total_deposit': 260},
    ]


def test_missing_dimension_keys_align_without_losing_money(service):
    mutate(service, "DELETE FROM players WHERE country='SG'")
    rows = service.query(SemanticQuery(metrics=['total_stake', 'total_deposit'],
                                       dimensions=['country']))['rows']
    # NULL ordering differs by engine; alignment and amounts must not.
    assert len(rows) == 3
    assert next(row for row in rows if row['country'] is None) == {
        'country': None, 'total_stake': 420, 'total_deposit': 260}
    assert sum(row['total_stake'] for row in rows) == 975
    assert sum(row['total_deposit'] for row in rows) == 640


@pytest.mark.parametrize('backend', ['duckdb', 'sqlite'])
def test_plan_and_missing_database_never_create_files(tmp_path, backend):
    db = Database(tmp_path / 'missing' / 'warehouse', backend)
    svc = SemanticService(database=db)
    client = TestClient(create_app(svc))
    request = {'metrics': ['total_stake']}
    assert client.post('/api/plan', json=request).status_code == 200
    response = client.post('/api/query', json=request)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'database_unavailable'
    assert not db.path.parent.exists()


def test_query_connection_is_read_only(service):
    with pytest.raises((duckdb.InvalidInputException, sqlite3.OperationalError)):
        service.database.run(CompiledQuery('DELETE FROM bets', []))
    assert service.query(SemanticQuery(metrics=['bet_count']))['rows'] == [{'bet_count': 12}]


def test_plan_api_and_execution_share_trace(service):
    client = TestClient(create_app(service))
    request = {'metrics': ['total_stake', 'total_deposit'], 'dimensions': ['country']}
    plan = client.post('/api/plan', json=request).json()
    result = client.post('/api/query', json=request).json()
    assert plan == {key: result[key] for key in plan}


def test_structured_error_stages_and_secret_redaction(service, monkeypatch):
    client = TestClient(create_app(service))
    response = client.post('/api/query', json={'metrics': ['unknown']})
    assert response.json()['error']['stage'] == 'planning'
    response = client.post('/api/ask', json={
        'question': 'Show stake', 'llm': {'api_key': 'secret-token', 'json_mode': 'secret-token'}})
    assert response.status_code == 422
    assert response.json()['error']['stage'] == 'validation'
    assert 'secret-token' not in response.text

    def fail(*args, **kwargs):
        raise RuntimeError('provider leaked secret-token')
    monkeypatch.setattr('ossie_demo.service.llm_parse', fail)
    response = client.post('/api/ask', json={'question': 'Show stake', 'mode': 'llm'})
    assert response.json()['error']['stage'] == 'interpretation'
    assert 'secret-token' not in response.text
    monkeypatch.setattr(service.database, 'run', fail)
    response = client.post('/api/query', json={'metrics': ['total_stake']})
    assert response.json()['error']['stage'] == 'execution'
    assert 'secret-token' not in response.text


@pytest.mark.parametrize('backend', ['duckdb', 'sqlite'])
def test_bootstrap_is_explicit_and_does_not_reset_existing_data(tmp_path, backend):
    db = Database(tmp_path / 'demo', backend)
    svc = SemanticService(database=db, bootstrap_demo=True)
    request = SemanticQuery(metrics=['bet_count'])
    assert svc.query(request)['rows'] == [{'bet_count': 176}]
    mutate(svc, 'DELETE FROM bets')
    assert svc.query(request)['rows'] == [{'bet_count': 0}]


def test_interpretation_failure_is_not_reported_as_planning(service, monkeypatch):
    client = TestClient(create_app(service))
    response = client.post('/api/ask', json={'question': 'unrecognized question'})
    assert response.status_code == 422
    assert response.json()['error']['stage'] == 'interpretation'

    def invalid(*args, **kwargs):
        raise ValueError('invalid model output with secret-token')
    monkeypatch.setattr('ossie_demo.service.llm_parse', invalid)
    response = client.post('/api/ask', json={'question': 'Show stake', 'mode': 'llm'})
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'invalid_interpretation'
    assert 'secret-token' not in response.text


def test_failed_seed_rolls_back_existing_warehouse(service, monkeypatch):
    def broken_fixture(name):
        raise ValueError('invalid fixture')
    monkeypatch.setattr('ossie_demo.demo_data.fixture', broken_fixture)
    with pytest.raises(ValueError, match='invalid fixture'):
        service.database.seed()
    assert service.query(SemanticQuery(metrics=['total_stake']))['rows'] == [{'total_stake': 975}]
