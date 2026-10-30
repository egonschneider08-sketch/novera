"""API acceptance tests: local synthetic GETs, schema, defensive HTTP policy."""

import csv
import io
import socket

import pytest
from fastapi.testclient import TestClient
from novera.demo_api import ReportOut, create_app
from novera.research_compare import compare_scenarios, comparison_csv, comparison_json
from novera.research_demo import report_json, run_scenario
from pydantic import ValidationError


@pytest.fixture
def client():
    with TestClient(create_app()) as service:
        yield service


def test_local_health_is_only_lab_status(client):
    response = client.get("/api/v1/demo/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "api_version": "v1",
        "data_mode": "synthetic-only",
    }


def test_catalog_is_only_three_fictional_instruments(client):
    response = client.get("/api/v1/demo/scenarios")
    assert response.status_code == 200
    payload = response.json()
    assert payload["synthetic"] is True
    assert "100% FICTÍCIOS" in payload["disclaimer"]
    assert [item["id"] for item in payload["scenarios"]] == [
        "complete",
        "expensive",
        "incomplete",
    ]
    assert [item["asset_id"] for item in payload["scenarios"]] == [
        "LAB-A",
        "LAB-B",
        "LAB-C",
    ]
    assert all(item["synthetic"] is True for item in payload["scenarios"])


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("complete", "pass"),
        ("expensive", "fail"),
        ("incomplete", "unknown"),
    ],
)
def test_scenario_response_matches_python_contract_and_evaluations(client, scenario, expected):
    response = client.get(f"/api/v1/demo/scenarios/{scenario}")
    assert response.status_code == 200
    assert response.json() == report_json(run_scenario(scenario))
    payload = response.json()
    assert payload["synthetic"] is True
    assert payload["asset"]["namespace"] == "novera.demo"
    assert [strategy["state"] for strategy in payload["strategies"]] == [
        expected,
        expected,
    ]
    assert all(item["source"]["synthetic"] is True for item in payload["observations"])
    assert all(
        type(item["value"]) is str or item["value"] is None for item in payload["observations"]
    )


def test_missing_data_is_not_zero_or_fail(client):
    response = client.get("/api/v1/demo/scenarios/incomplete")
    data = response.json()
    missing = next(item for item in data["observations"] if item["metric"] == "earnings_per_share")
    assert missing["value"] is None
    assert missing["quality"] == "missing"
    assert data["strategies"][0]["state"] == "unknown"


def test_comparison_is_exactly_the_python_output_and_not_a_ranking(client):
    response = client.get("/api/v1/demo/comparison")
    assert response.status_code == 200
    assert response.json() == comparison_json(compare_scenarios())
    assert response.json()["ordering"] == "user_selection_not_investment_ranking"
    assert response.json()["total_scenarios"] == 3


def test_csv_is_exactly_the_python_output_with_constant_synthetic_filename(client):
    response = client.get("/api/v1/demo/comparison.csv")
    assert response.status_code == 200
    assert response.text == comparison_csv(compare_scenarios())
    assert response.headers["content-disposition"] == (
        'attachment; filename="novera-lab-ficticio.csv"'
    )
    assert "text/csv" in response.headers["content-type"]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert rows
    assert {row["synthetic"] for row in rows} == {"true"}
    assert all("FICTÍCIOS" in row["disclaimer"] for row in rows)
    assert all(row["source"] == "novera-synthetic-fixture" for row in rows)


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/demo/scenarios/PETR4",
        "/api/v1/demo/scenarios/unknown",
        "/api/v1/demo/scenarios/../BRAPI",
    ],
)
def test_unknown_scenarios_cannot_return_real_market_data(client, path):
    response = client.get(path, follow_redirects=False)
    assert response.status_code in (404, 405)
    assert "api_key" not in response.text.lower()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/demo/scenarios"),
        ("PUT", "/api/v1/demo/scenarios/complete"),
        ("DELETE", "/api/v1/demo/scenarios/complete"),
        ("PATCH", "/api/v1/demo/comparison"),
    ],
)
def test_mutating_http_methods_are_not_allowed(client, method, path):
    response = client.request(method, path, json={"value": "100"})
    assert response.status_code == 405


def test_unreviewed_query_parameters_are_rejected_without_ignoring_them(client):
    response = client.get("/api/v1/demo/comparison?provider=brapi&token=never")
    assert response.status_code == 400
    assert "never" not in response.text
    assert "brapi" not in response.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/demo/health",
        "/api/v1/demo/scenarios/complete",
        "/api/v1/demo/comparison.csv",
        "/api/v1/demo/scenarios/unknown",
        "/api/v1/demo/comparison?extra=1",
    ],
)
def test_no_store_and_nosniff_headers_also_cover_errors(client, path):
    response = client.get(path)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-robots-tag"] == "noindex"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_disallowed_host_is_rejected(client):
    response = client.get(
        "/api/v1/demo/health",
        headers={"host": "market-api.example.org"},
    )
    assert response.status_code == 400


def test_cross_origin_preflight_does_not_grant_cors_access(client):
    response = client.options(
        "/api/v1/demo/comparison",
        headers={
            "origin": "https://attacker.example.net",
            "access-control-request-method": "GET",
        },
    )
    assert response.status_code == 405
    assert "access-control-allow-origin" not in response.headers


def test_docs_disabled_but_versioned_openapi_is_available(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    schema = client.get("/api/v1/openapi.json")
    assert schema.status_code == 200
    routes = schema.json()["paths"]
    assert "/api/v1/demo/scenarios/{scenario}" in routes
    assert "/api/v1/demo/comparison" in routes
    assert "ReportOut" in schema.json()["components"]["schemas"]


def test_contract_rejects_provider_spoofing_and_invalid_decimal():
    raw = report_json(run_scenario("complete"))
    raw["observations"][0]["source"]["synthetic"] = False
    with pytest.raises(ValidationError):
        ReportOut.model_validate(raw)

    raw = report_json(run_scenario("complete"))
    raw["observations"][0]["value"] = 1.2
    with pytest.raises(ValidationError):
        ReportOut.model_validate(raw)


def test_contract_rejects_quality_mismatch_and_undeclared_fields():
    raw = report_json(run_scenario("complete"))
    raw["observations"][0]["quality"] = "missing"
    with pytest.raises(ValidationError):
        ReportOut.model_validate(raw)
    raw = report_json(run_scenario("complete"))
    raw["secret_token"] = "never-persist"
    with pytest.raises(ValidationError):
        ReportOut.model_validate(raw)


def test_testclient_runs_fully_offline(monkeypatch):
    def deny_socket(*_args, **_kwargs):
        raise AssertionError("network access attempted during synthetic API call")

    monkeypatch.setattr(socket.socket, "connect", deny_socket)
    with TestClient(create_app()) as service:
        assert service.get("/api/v1/demo/scenarios/complete").status_code == 200
        assert service.get("/api/v1/demo/comparison").status_code == 200
