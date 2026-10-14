"""Advanced metric expressions, fact-grain alignment, data preview, provider options."""
import copy
import json
import sys
from datetime import date
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from ossie_demo.api import create_app
from ossie_demo.catalog import Catalog, SemanticError
from ossie_demo.parsing import llm_parse
from ossie_demo.schemas import LLMOptions, SemanticQuery


def test_safe_ratio_and_distinct_per_dimension(service):
    result = service.query(SemanticQuery(
        metrics=['total_stake', 'unique_bettors', 'stake_per_bettor'], dimensions=['country']))
    assert result['rows'] == [
        {'country': 'DE', 'total_stake': 315, 'unique_bettors': 1, 'stake_per_bettor': 315.0},
        {'country': 'FI', 'total_stake': 240, 'unique_bettors': 1, 'stake_per_bettor': 240.0},
        {'country': 'SG', 'total_stake': 420, 'unique_bettors': 2, 'stake_per_bettor': 210.0},
    ]
    assert 'COUNT(DISTINCT "bets"."player_id")' in result['sql']
    assert 'NULLIF(' in result['sql']


def test_ratio_and_two_fact_grains_at_once(service):
    result = service.query(SemanticQuery(
        metrics=['total_stake', 'total_deposit', 'stake_per_bettor'], dimensions=['country']))
    assert result['logical_plan']['strategy'] == 'aggregate_then_join'
    assert result['rows'][2] == {
        'country': 'SG', 'total_stake': 420, 'total_deposit': 260, 'stake_per_bettor': 210.0}


def test_cross_grain_grand_total_and_group_date_filter(service):
    result = service.query(SemanticQuery(metrics=['total_stake', 'total_deposit']))
    assert result['rows'] == [{'total_stake': 975, 'total_deposit': 640}]
    result = service.query(SemanticQuery(
        metrics=['total_stake', 'total_deposit'], dimensions=['country'],
        date_from=date(2026, 10, 3), date_to=date(2026, 10, 9)))
    # Both branches filter on their respective time dimension.
    assert result['parameters'] == ['2026-10-03', '2026-10-09'] * 2
    assert result['rows'][0] == {'country': 'DE', 'total_stake': 260, 'total_deposit': 200}
    assert result['rows'][1] == {'country': 'FI', 'total_stake': 200, 'total_deposit': 110}
    assert result['rows'][2] == {'country': 'SG', 'total_stake': 190, 'total_deposit': 230}


def test_incompatible_dimension_is_rejected(service):
    with pytest.raises(SemanticError, match='no safe many-to-one join path'):
        service.query(SemanticQuery(metrics=['total_stake','total_deposit'],
                                    dimensions=['country','game_category']))


def test_metric_ratio_added_only_through_yaml(service, tmp_path):
    model = copy.deepcopy(service.catalog.raw)
    model['metrics'].append({
        'name': 'payout_per_bet', 'datatype': 'Decimal',
        'expression': {'dialects': [{'dialect': 'ANSI_SQL',
                                    'expression': 'SUM(bets.payout_amount) / COUNT(bets.bet_id)'}]},
    })
    path = tmp_path / 'extended.yaml'
    path.write_text(yaml.safe_dump(model), encoding='utf-8')
    from ossie_demo.service import SemanticService
    svc = SemanticService(path, database=service.database)
    result = svc.query(SemanticQuery(metrics=['payout_per_bet'], dimensions=['country']))
    assert result['rows'][1]['payout_per_bet'] == pytest.approx(160 / 3)


@pytest.mark.parametrize('bad', [
    'SUM(bets.amount); DROP TABLE bets',
    'SUM(bets.amount) / (SELECT 1)',
    'SUM(bets.amount) / SLEEP(1)',
    'SUM(bets.amount) / COUNT(DISTINCT bets.player_id, bets.bet_id)',
    'SUM(bets.amount) / bets.player_id',
])
def test_ast_rejects_sql_and_bare_columns(service, tmp_path, bad):
    model = copy.deepcopy(service.catalog.raw)
    model['metrics'][0]['expression']['dialects'][0]['expression'] = bad
    path = tmp_path / 'bad.yaml'
    path.write_text(yaml.safe_dump(model), encoding='utf-8')
    with pytest.raises(SemanticError):
        Catalog(path)


def test_data_fixture_explorer_api(service):
    api = TestClient(create_app(service))
    overview = api.get('/api/data')
    assert overview.status_code == 200
    assert overview.json()['backend'] == service.database.backend
    assert {row['name']: row['row_count'] for row in overview.json()['tables']} == {
        'players': 4, 'games': 2, 'bets': 12, 'deposits': 7,
    }
    preview = api.get('/api/data/preview', params={'table': 'deposits', 'limit': 2})
    assert preview.status_code == 200
    assert len(preview.json()['rows']) == 2
    assert api.get('/api/data/preview?table=sqlite_master').status_code == 422
    assert api.get('/api/data/preview?table=bets&limit=1000').status_code == 422


def test_provider_options_are_transient_and_customizable(service, monkeypatch):
    calls = {}
    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls['client'] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        def create(self, **kwargs):
            calls['request'] = kwargs
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
                content='{"metrics":["total_stake","total_deposit"],"dimensions":["country"]}'))])
    monkeypatch.setitem(sys.modules, 'openai', SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    options = LLMOptions(base_url='http://127.0.0.1:11434/v1', model='local-model',
                         api_key='temporary-secret', json_mode=False)
    request = llm_parse('Show deposits and stakes by country', service.catalog, options=options)
    assert request.metrics == ['total_stake', 'total_deposit']
    assert calls['client']['base_url'] == 'http://127.0.0.1:11434/v1'
    assert calls['client']['api_key'] == 'temporary-secret'
    assert calls['request']['model'] == 'local-model'
    assert 'response_format' not in calls['request']
    response = service.query(request)
    assert 'temporary-secret' not in json.dumps(response)


def test_api_custom_llm_key_not_echoed(service, monkeypatch):
    from ossie_demo import parsing
    def fake_parser(question, catalog, today=None, options=None):
        assert options.api_key.get_secret_value() == 'secret-abc'
        return SemanticQuery(metrics=['total_stake'], dimensions=['country'])
    monkeypatch.setattr(parsing, 'llm_parse', fake_parser)
    # service module imports its own reference
    import ossie_demo.service as service_module
    monkeypatch.setattr(service_module, 'llm_parse', fake_parser)
    api = TestClient(create_app(service))
    response = api.post('/api/ask', json={'question': 'Show stake by country', 'mode': 'llm',
                    'llm': {'base_url': 'http://localhost:11434/v1', 'model': 'my-model',
                            'api_key': 'secret-abc'}})
    assert response.status_code == 200
    assert 'secret-abc' not in response.text


def test_provider_validation():
    with pytest.raises(ValueError):
        LLMOptions(base_url='file:///etc/passwd')
    assert LLMOptions(base_url='http://169.254.169.254/latest/').base_url == 'http://169.254.169.254/latest'
    assert LLMOptions(base_url='http://100.100.100.200/').base_url == 'http://100.100.100.200'
