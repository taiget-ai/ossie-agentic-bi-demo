import sys
from datetime import date
from types import SimpleNamespace

import pytest

from ossie_demo.catalog import SemanticError
from ossie_demo.parsing import llm_parse, rule_parse


@pytest.mark.parametrize("question,metrics,dimensions", [
    ("Show total stake by country", ["total_stake"], ["country"]),
    ("Show net gaming revenue by game category", ["ngr"], ["game_category"]),
    ("Show bet count by country for the last 7 days", ["bet_count"], ["country"]),
    ("Show total stake by country and game category", ["total_stake"], ["country", "game_category"]),
    ("Show NGR and total stake by game category", ["ngr", "total_stake"], ["game_category"]),
])
def test_english_rules(service, question, metrics, dimensions):
    intent = rule_parse(question, service.catalog, today=date(2026, 10, 9))
    assert intent.metrics == metrics
    assert intent.dimensions == dimensions


def test_last_seven_days(service):
    intent = rule_parse("Show total stake in Finland in the last 7 days", service.catalog,
                        today=date(2026, 10, 9))
    assert intent.filters == {"country": "FI"}
    assert intent.date_from == date(2026, 10, 3)
    assert intent.date_to == date(2026, 10, 9)
    assert service.query(intent)["rows"] == [{"total_stake": 200}]


def test_rules_reject_unknown_metric(service):
    with pytest.raises(SemanticError, match="recognizable metric"):
        rule_parse("Show trends in our business", service.catalog)


def test_openai_model_contract(service, monkeypatch):
    """Mock only OpenAI network transport; test the public parser contract."""
    from ossie_demo import parsing

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["model"] == "gpt-4o-mini"
            assert kwargs["response_format"] == {"type": "json_object"}
            assert "total_stake" in kwargs["messages"][0]["content"]
            assert "metrics" in kwargs["messages"][0]["content"]
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=(
                '{"metrics":["total_stake","ngr"],"dimensions":["country"],'
                '"filters":{},"date_from":null,"date_to":null}'
            )))])

    class FakeOpenAI:
        def __init__(self, **kwargs):
            assert "base_url" not in kwargs
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    intent = parsing.llm_parse("Show total stake and NGR by country", service.catalog,
                               today=date(2026, 10, 9))
    assert intent.metrics == ["total_stake", "ngr"]
    assert intent.dimensions == ["country"]
    assert service.query(intent)["rows"][1]["total_stake"] == 240


def test_llm_mode_without_api_key(service, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(SemanticError, match="OPENAI_API_KEY"):
        llm_parse("Show total stake by country", service.catalog)


def test_openai_hallucinated_metric_rejected(service, monkeypatch):
    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs:
                SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=(
                    '{"metrics":["fictional_metric"],"dimensions":[],"filters":{}}'
                )))])))

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    intent = llm_parse("Show fictional metric", service.catalog)
    with pytest.raises(SemanticError, match="unknown metric"):
        service.query(intent)
