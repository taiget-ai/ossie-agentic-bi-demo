from fastapi.testclient import TestClient

from ossie_demo.api import create_app


def test_api_query(service):
    client = TestClient(create_app(service))
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/model").json()["name"] == "gaming_analytics"
    response = client.post("/api/query", json={"metrics": ["total_stake"],
                                               "dimensions": ["country"]})
    assert response.status_code == 200
    assert response.json()["rows"][1] == {"country": "FI", "total_stake": 240}
    assert response.json()["logical_plan"]["root_dataset"] == "bets"


def test_api_multi_metric(service):
    client = TestClient(create_app(service))
    response = client.post("/api/query", json={"metrics": ["total_stake", "bet_count"],
                                               "dimensions": ["country"]})
    assert response.status_code == 200
    assert response.json()["rows"][1] == {"country": "FI", "total_stake": 240, "bet_count": 3}


def test_api_natural_language_offline(service):
    client = TestClient(create_app(service))
    response = client.post("/api/ask", json={"question": "Show total stake by country", "mode": "rules"})
    assert response.status_code == 200
    assert response.json()["semantic_query"]["metrics"] == ["total_stake"]


def test_api_rejects_hallucinated_metric(service):
    client = TestClient(create_app(service))
    response = client.post("/api/query", json={"metrics": ["invented_metric"]})
    assert response.status_code == 422


def test_api_rejects_old_contract(service):
    client = TestClient(create_app(service))
    response = client.post("/api/query", json={"metric": "total_stake"})
    assert response.status_code == 422


def test_api_plan_without_database(service):
    client = TestClient(create_app(service))
    response = client.post("/api/plan", json={"metrics": ["ngr", "total_stake"],
                                              "dimensions": ["country"]})
    assert response.status_code == 200
    assert response.json()["logical_plan"]["metrics"][0]["name"] == "ngr"
    assert response.json()["join_path"] == ["bets_to_players"]
