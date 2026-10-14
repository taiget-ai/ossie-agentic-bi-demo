from datetime import date

import pytest

from ossie_demo.database import Database
from ossie_demo.parsing import rule_parse
from ossie_demo.schemas import SemanticQuery
from ossie_demo.service import SemanticService


@pytest.mark.parametrize('backend', ['duckdb', 'sqlite'])
def test_expanded_market_data(tmp_path, backend):
    db = Database(tmp_path / 'expanded', backend)
    counts = db.seed(today=date(2026, 10, 13))
    assert {k: counts[k] for k in ['players', 'bets', 'deposits']} == {
        'players': 36, 'bets': 176, 'deposits': 89}
    svc = SemanticService(database=db)
    result = svc.query(SemanticQuery(
        metrics=['total_stake', 'total_deposit', 'unique_bettors', 'stake_per_bettor'],
        dimensions=['country'],
    ))
    assert len(result['rows']) == 12
    assert all(r['unique_bettors'] == 3 for r in result['rows'])
    assert sum(r['total_stake'] for r in result['rows']) == 29570
    assert sum(r['total_deposit'] for r in result['rows']) == 31000
    us = svc.query(rule_parse('Show total stake in United States by month', svc.catalog))
    assert sum(r['total_stake'] for r in us['rows']) == 2170
    assert len(us['rows']) >= 3
    assert len(svc.catalog.public_model()['filter_values']['country']) == 12


@pytest.mark.parametrize(('phrase', 'code'), [
    ('United States', 'US'), ('USA', 'US'), ('UK', 'GB'), ('Japan', 'JP'),
    ('India', 'IN'), ('IN', 'IN'), ('Brazil', 'BR'), ('Canada', 'CA'),
    ('Australia', 'AU'), ('France', 'FR'), ('Spain', 'ES'),
])
def test_configured_country_vocabulary(service, phrase, code):
    assert rule_parse(f'Show total stake in {phrase}', service.catalog).filters == {'country': code}


def test_country_codes_do_not_match_english_words(service):
    assert rule_parse('Show us total stake in the last 7 days', service.catalog).filters == {}
    assert rule_parse('Show total stake in Finland and Germany', service.catalog).filters == {'country': ['DE', 'FI']}
