from dataclasses import asdict
from datetime import date

import pytest

from ossie_demo.catalog import Catalog, SemanticError
from ossie_demo.planner import compile_query
from ossie_demo.planning import compile_sql, resolve_query
from ossie_demo.schemas import SemanticQuery


def test_total_stake_country(service):
    result = service.query(SemanticQuery(metrics=["total_stake"], dimensions=["country"]))
    assert result["rows"] == [
        {"country": "DE", "total_stake": 315},
        {"country": "FI", "total_stake": 240},
        {"country": "SG", "total_stake": 420},
    ]
    assert result["join_path"] == ["bets_to_players"]
    assert result["logical_plan"]["metrics"][0] == {
        "name": "total_stake", "expression": "SUM(bets.amount)", "dataset": "bets"
    }


def test_ngr_game_category(service):
    result = service.query(SemanticQuery(metrics=["ngr"], dimensions=["game_category"]))
    assert result["rows"] == [
        {"game_category": "Casino", "ngr": 60},
        {"game_category": "Sports", "ngr": 160},
    ]


def test_two_dimensions_no_fanout(service):
    result = service.query(SemanticQuery(metrics=["total_stake"],
                                          dimensions=["country", "game_category"]))
    assert len(result["join_path"]) == 2
    assert len(result["rows"]) == 6
    assert sum(row["total_stake"] for row in result["rows"]) == 975


def test_multiple_metrics_one_pass(service):
    result = service.query(SemanticQuery(metrics=["total_stake", "bet_count", "ngr"],
                                         dimensions=["country"]))
    assert result["rows"] == [
        {"country": "DE", "total_stake": 315, "bet_count": 3, "ngr": 60},
        {"country": "FI", "total_stake": 240, "bet_count": 3, "ngr": 65},
        {"country": "SG", "total_stake": 420, "bet_count": 6, "ngr": 95},
    ]
    assert result["sql"].count('LEFT JOIN "players"') == 1
    assert len(result["logical_plan"]["metrics"]) == 3


def test_logical_plan_separate_from_sql_compiler(service):
    request = SemanticQuery(metrics=["ngr", "bet_count"], dimensions=["country"],
                            filters={"country": "FI"})
    logical = resolve_query(service.catalog, request)
    assert not hasattr(logical, "sql")
    assert asdict(logical)["joins"][0]["name"] == "bets_to_players"
    compiled = compile_sql(logical)
    assert 'SUM((("bets"."amount" - "bets"."payout_amount") - "bets"."bonus_cost"))' in compiled.sql
    assert compiled.parameters == ["FI"]
    assert compiled.sql == compile_query(service.catalog, request).sql


def test_country_filter_and_dates_are_parameterized(service):
    request = SemanticQuery(metrics=["total_stake"], filters={"country": "FI"},
                            date_from=date(2026, 10, 3), date_to=date(2026, 10, 9))
    result = service.query(request)
    assert result["rows"] == [{"total_stake": 200}]
    assert result["parameters"] == ["FI", "2026-10-03", "2026-10-09"]
    assert '"bets"."bet_date" >=' in result["sql"]
    assert "FI" not in result["sql"]


def test_add_new_metric_without_python_changes(service, tmp_path):
    """An additional catalog metric is available to the generic resolver/compiler."""
    import copy

    import yaml
    model = copy.deepcopy(service.catalog.raw)
    metric = copy.deepcopy(model["metrics"][0])
    metric["name"] = "total_payout"
    metric["expression"]["dialects"][0]["expression"] = "SUM(bets.payout_amount)"
    metric["ai_context"]["synonyms"] = ["total payout"]
    model["metrics"].append(metric)
    path = tmp_path / "new-metric.yaml"
    path.write_text(yaml.safe_dump(model), encoding="utf-8")
    catalog = Catalog(path)
    request = SemanticQuery(metrics=["total_stake", "total_payout"], dimensions=["country"])
    logical = resolve_query(catalog, request)
    sql = compile_sql(logical)
    assert 'SUM("bets"."payout_amount") AS "total_payout"' in sql.sql
    from ossie_demo.service import SemanticService
    result = SemanticService(path, database=service.database).query(request)
    assert result["rows"][1]["total_payout"] == 160


def test_cross_grain_metrics_aggregate_before_join(service):
    result = service.query(SemanticQuery(
        metrics=["total_stake", "total_deposit"], dimensions=["country"]
    ))
    assert result["logical_plan"]["strategy"] == "aggregate_then_join"
    assert len(result["logical_plan"]["branches"]) == 2
    assert result["rows"] == [
        {"country": "DE", "total_stake": 315, "total_deposit": 200},
        {"country": "FI", "total_stake": 240, "total_deposit": 180},
        {"country": "SG", "total_stake": 420, "total_deposit": 260},
    ]
    # Joining raw bet and deposit facts on player would create a many-to-many fanout.
    assert "WITH b0 AS (" in result["sql"]
    assert "group_keys AS (" in result["sql"]
    assert 'FROM "bets"' in result["sql"] and 'FROM "deposits"' in result["sql"]




def test_reject_sql_injection_name(service):
    with pytest.raises(SemanticError, match="unknown metric"):
        service.query(SemanticQuery(metrics=["total_stake; DROP TABLE bets"]))
    with pytest.raises(SemanticError, match="unknown dimension"):
        service.query(SemanticQuery(metrics=["total_stake"],
                                    dimensions=["country; DROP TABLE bets"]))


def test_filter_value_injection_stays_bound(service):
    payload = "FI' OR 1=1 --"
    result = service.query(SemanticQuery(metrics=["bet_count"], filters={"country": payload}))
    assert result["rows"] == [{"bet_count": 0}]
    assert payload not in result["sql"]
    assert result["parameters"] == [payload]


def test_reject_unsupported_filter(service):
    with pytest.raises(SemanticError, match="filter must use a declared dimension"):
        compile_query(service.catalog, SemanticQuery(metrics=["total_stake"],
                                                     filters={"player_id": "1"}))


def test_date_validation():
    with pytest.raises(ValueError):
        SemanticQuery(metrics=["total_stake"], date_from="2026-10-09", date_to="2026-10-01")
    with pytest.raises(ValueError):
        SemanticQuery(metrics=["total_stake"], dimensions=["country", "country"])
    with pytest.raises(ValueError):
        SemanticQuery(metrics=["total_stake"], limit=1000)
    with pytest.raises(ValueError):
        SemanticQuery(metrics=["total_stake", "total_stake"])
    with pytest.raises(ValueError):
        SemanticQuery(metrics=[])


def test_ambiguous_join_paths_are_rejected(service, tmp_path):
    import copy

    import yaml
    model = copy.deepcopy(service.catalog.raw)
    duplicate = copy.deepcopy(model["relationships"][0])
    duplicate["name"] = "bets_to_players_alternative"
    model["relationships"].append(duplicate)
    path = tmp_path / "ambiguous.yaml"
    path.write_text(yaml.safe_dump(model), encoding="utf-8")
    catalog = Catalog(path)
    with pytest.raises(SemanticError, match="ambiguous shortest join path"):
        resolve_query(catalog, SemanticQuery(metrics=["total_stake"], dimensions=["country"]))
