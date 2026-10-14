import io
import json
import subprocess
import sys
import zipfile

import pytest
from fastapi.testclient import TestClient

from ossie_demo import analytics
from ossie_demo.api import create_app
from ossie_demo.catalog import SemanticError
from ossie_demo.schemas import DrillRequest, ModelComparison, PeriodComparison, SemanticQuery


def test_multi_filter_and_top_n(service):
    result = service.query(SemanticQuery(metrics=['total_stake', 'total_deposit'], dimensions=['country'],
        filters={'country': ['FI', 'SG']}, order_by=[{'field': 'total_deposit', 'direction': 'desc'}], limit=1))
    assert result['rows'] == [{'country': 'SG', 'total_stake': 420, 'total_deposit': 260}]
    with pytest.raises(ValueError):
        SemanticQuery(metrics=['total_stake'], order_by=[{'field':'evil'}])


def test_period_contribution_reconciles_before_top_n(service):
    request = PeriodComparison(metric='total_stake', dimension='country',
        previous={'start':'2026-09-01','end':'2026-09-30'},
        current={'start':'2026-10-01','end':'2026-10-31'}, top_n=1)
    result = analytics.period_comparison(service, request)
    assert result['previous'] == 160
    assert result['current'] == 815
    assert result['delta'] == 655
    assert sum(row['delta'] for row in result['rows']) + result['other_delta'] == 655
    assert result['group_count'] == 3
    with pytest.raises(SemanticError, match='SUM'):
        analytics.period_comparison(service, request.model_copy(update={'metric':'stake_per_bettor'}))
    empty = request.model_copy(update={'filters':{'country':'ZZ'}})
    assert analytics.period_comparison(service, empty)['change_pct'] is None


def test_drill_preserves_partial_period_and_filters(service):
    request = DrillRequest(query=SemanticQuery(metrics=['total_stake'], time_grain='month',
        date_from='2026-10-03', date_to='2026-10-09', filters={'country':['SG','FI']}),
        selection={'time_period':'2026-10-01'}, target='country')
    query = analytics.drill_query(service, request)
    assert str(query.date_from) == '2026-10-03'
    assert str(query.date_to) == '2026-10-09'
    assert query.filters == {'country':['SG','FI']}
    assert query.time_grain is None
    query2 = analytics.drill_query(service, DrillRequest(query=query, selection={'country':'SG'},target='game_category'))
    assert query2.filters == {'country':'SG'}
    assert sum(r['total_stake'] for r in service.query(query2)['rows']) == 190
    opts = analytics.drill_options(service, SemanticQuery(metrics=['total_stake','total_deposit']))
    assert not next(o for o in opts if o['dimension']=='game_category')['available']


def test_model_comparison_does_not_persist_and_ignores_top_n(service):
    before = analytics.fingerprint(service.catalog)
    request = ModelComparison(query=SemanticQuery(metrics=['ngr'], dimensions=['country'],limit=1),
        metric='ngr', expression='SUM(bets.amount - bets.payout_amount)')
    result = analytics.model_comparison(service, request)
    assert len(result['rows']) == 3
    assert sum(r['delta'] for r in result['rows']) == 60
    assert result['old_fingerprint'] != result['candidate_fingerprint']
    assert analytics.fingerprint(service.catalog) == before
    with pytest.raises(SemanticError):
        analytics.model_comparison(service, request.model_copy(update={'expression':'SUM(bets.amount); DROP TABLE bets'}))


def test_metric_explanation_with_real_components(service):
    result = analytics.explain_value(service, SemanticQuery(metrics=['stake_per_bettor'],
        dimensions=['country']), 'stake_per_bettor')
    assert result['ratio']
    assert result['time_fields'] == ['bets.bet_date']
    assert result['components'][-1] == {'country':'SG','explain_numerator':420,'explain_denominator':2}
    assert any(a['distinct'] for a in result['aggregates'])


def test_reproduction_executes_on_export_snapshot(service, tmp_path):
    query = SemanticQuery(metrics=['total_stake','total_deposit'],time_grain='week',
        dimensions=['country'], filters={'country':['FI','SG']})
    archive = zipfile.ZipFile(io.BytesIO(analytics.reproduction(service, query)))
    archive.extractall(tmp_path / 'replay')
    manifest = json.loads(archive.read('manifest.json'))
    assert manifest['model_fingerprint'] == analytics.fingerprint(service.catalog)
    completed = subprocess.run([sys.executable,str(tmp_path/'replay'/'replay.py')],capture_output=True,text=True,check=False)
    assert completed.returncode == 0, completed.stderr
    assert 'Replay verified' in completed.stdout


def test_workflow_api_and_chinese_question(service):
    client = TestClient(create_app(service))
    response = client.post('/api/ask',json={'question':'按月统计总投注额和总充值额','mode':'rules'})
    assert response.status_code == 200
    assert response.json()['semantic_query']['time_grain']=='month'
    assert client.post('/api/metrics/explain',json={'query':{'metrics':['stake_per_bettor']},'metric':'stake_per_bettor'}).status_code==200
    assert client.post('/api/export',json={'metrics':['total_stake']}).headers['content-type']=='application/zip'


def test_zero_delta_and_zero_baseline_contributions(service):
    conn = service.database.connect()
    try:
        conn.execute('DELETE FROM bets')
        conn.execute("INSERT INTO bets VALUES (1, 1, 1, '2026-08-01', 10, 0, 0)")
        conn.execute("INSERT INTO bets VALUES (2, 1, 1, '2026-09-01', 10, 0, 0)")
        conn.commit()
    finally:
        conn.close()
    req = PeriodComparison(previous={'start':'2026-08-01','end':'2026-08-31'},
                           current={'start':'2026-09-01','end':'2026-09-30'})
    result = analytics.period_comparison(service, req)
    assert result['delta'] == 0
    assert result['rows'][0]['contribution_pct'] is None
    with pytest.raises(ValueError):
        PeriodComparison(previous={'start':'2026-08-01','end':'2026-09-01'},
                         current={'start':'2026-09-01','end':'2026-09-30'})


def test_multi_filter_injection_is_bound(service):
    q = SemanticQuery(metrics=['bet_count'],filters={'country':["FI' OR 1=1 --",'FI']})
    result = service.query(q)
    assert result['rows'] == [{'bet_count':3}]
    assert "FI' OR" not in result['sql']
    assert result['parameters'] == ["FI' OR 1=1 --",'FI']


def test_chinese_top_n_and_day_window(service):
    from datetime import date

    from ossie_demo.parsing import rule_parse
    q = rule_parse('最近30天总投注额前5国家', service.catalog, today=date(2026,10,14))
    assert q.limit == 5
    assert q.order_by[0].field == 'total_stake'
    assert str(q.date_from) == '2026-09-15'
    assert q.dimensions == ['country']
