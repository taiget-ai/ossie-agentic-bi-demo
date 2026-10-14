import pytest
import yaml

from ossie_demo.catalog import Catalog, SemanticError


def save(tmp_path, data):
    p = tmp_path / "model.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_draft_flat_schema(service):
    assert service.catalog.raw["version"] == "0.2.0.dev0"
    assert "semantic_model" not in service.catalog.raw
    assert service.catalog.public_model()["name"] == "gaming_analytics"


def test_reject_unsupported_expression(service, tmp_path):
    model = service.catalog.raw.copy()
    model = yaml.safe_load(yaml.safe_dump(model))
    model["metrics"][0]["expression"]["dialects"][0]["expression"] = "SUM(bets.amount); DROP TABLE bets"
    with pytest.raises(SemanticError, match="unsupported aggregation"):
        Catalog(save(tmp_path, model))


def test_reject_many_side_join_without_unique_target(service, tmp_path):
    model = yaml.safe_load(yaml.safe_dump(service.catalog.raw))
    model["datasets"][1]["primary_key"] = []
    with pytest.raises(SemanticError, match="not declared unique"):
        Catalog(save(tmp_path, model))


def test_reject_legacy_wrapper(service, tmp_path):
    model = {"version": "0.2.0.dev0", "semantic_model": [service.catalog.raw]}
    with pytest.raises(SemanticError):
        Catalog(save(tmp_path, model))
