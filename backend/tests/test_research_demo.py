"""Offline acceptance tests for the first Novera research experience."""

import json
import socket
import subprocess
import sys
from datetime import datetime
from decimal import Decimal

import pytest
from novera.contracts import Quality
from novera.research_demo import (
    AS_OF,
    DISCLAIMER,
    SCENARIOS,
    SCOPE,
    _build_report,
    _seed_demo,
    main,
    render_text,
    report_json,
    run_scenario,
)
from novera.storage import ObservationStore
from novera.strategies import EvaluationState


@pytest.mark.parametrize(
    ("scenario", "expected"),
    [
        ("complete", EvaluationState.PASS),
        ("expensive", EvaluationState.FAIL),
        ("incomplete", EvaluationState.UNKNOWN),
    ],
)
def test_both_strategies_return_expected_evaluation_states(scenario, expected):
    report = run_scenario(scenario)
    assert report.asset.namespace == "novera.demo"
    assert report.asset.identifier == SCENARIOS[scenario][0]
    assert report.synthetic
    assert all(strategy.state is expected for strategy in report.strategies)
    assert all(strategy.synthetic for strategy in report.strategies)
    assert all(strategy.as_of == AS_OF for strategy in report.strategies)


def test_complete_fixture_calculations_use_stored_decimal_observations():
    report = run_scenario("complete")
    graham, bazin = report.strategies
    assert len(report.receipts) == 8
    assert next(item.value for item in graham.metrics if item.name == "graham_number") == Decimal(
        "30"
    )
    assert next(item.value for item in graham.metrics if item.name == "margin") == Decimal("2.75")
    assert next(item.value for item in bazin.metrics if item.name == "bazin_ceiling") == Decimal(
        "10"
    )
    assert next(item.value for item in bazin.metrics if item.name == "yield_365d") == Decimal(
        "0.075"
    )
    assert all(item.version == 1 for item in report.receipts)
    assert all(item.observation.provenance.source.synthetic for item in report.receipts)
    assert all(item.observation.provenance.published_at <= AS_OF for item in report.receipts)


def test_expensive_case_shows_explainable_negative_checks():
    report = run_scenario("expensive")
    graham, bazin = report.strategies
    assert graham.state is EvaluationState.FAIL
    assert bazin.state is EvaluationState.FAIL
    assert any(item.state is EvaluationState.FAIL for item in graham.criteria)
    assert any(item.state is EvaluationState.FAIL for item in bazin.criteria)
    assert all(item.reason for item in graham.criteria + bazin.criteria)


def test_missing_eps_and_uncertified_dividend_coverage_remain_unknown():
    report = run_scenario("incomplete")
    assert len(report.receipts) == 4
    assert not report.dividend_coverage_certified_by_fixture
    eps = next(
        x.observation for x in report.receipts if x.observation.metric == "earnings_per_share"
    )
    assert eps.value is None and eps.quality is Quality.MISSING
    assert eps.reason
    graham, bazin = report.strategies
    assert graham.state is EvaluationState.UNKNOWN
    assert bazin.state is EvaluationState.UNKNOWN
    assert next(x.value for x in graham.metrics if x.name == "graham_number") is None
    assert next(x.value for x in bazin.metrics if x.name == "bazin_ceiling") is None
    assert any(x.state is EvaluationState.UNKNOWN for x in graham.criteria)
    assert any(x.state is EvaluationState.UNKNOWN for x in bazin.criteria)


def test_repeat_seed_does_not_duplicate_sqlite_economic_records():
    with ObservationStore.memory(scope=SCOPE, synthetic=True) as store:
        original = _seed_demo(store, "complete")
        repeated = _seed_demo(store, "complete")
        assert original == repeated
        report = _build_report(store, "complete")
        assert set(report.receipts) == set(original)
        assert len(report.receipts) == 8


@pytest.mark.parametrize("scenario", tuple(SCENARIOS))
def test_deterministic_json_has_full_evidence_and_no_float_values(scenario):
    report = run_scenario(scenario)
    first = report_json(report)
    second = report_json(run_scenario(scenario))
    assert first == second
    serialized = json.dumps(first, ensure_ascii=False, allow_nan=False)
    assert json.loads(serialized) == first
    assert first["schema"] == "novera-synthetic-research-v1"
    assert first["synthetic"] is True
    assert "FICTÍCIOS" in first["disclaimer"]
    assert first["asset"]["namespace"] == "novera.demo"
    assert first["share_basis"] == "unadjusted"
    for obs in first["observations"]:
        assert type(obs["value"]) is str or obs["value"] is None
        assert obs["source"]["synthetic"] is True
        assert obs["source"]["provider"] == "novera-synthetic-fixture"
        assert obs["source"]["reference"].startswith("https://example.invalid/")
        assert obs["collected_at"] and obs["published_at"]
        assert len(obs["content_id"]) == 64
        assert len(obs["receipt_id"]) == 64
    assert first["strategies"][0]["coverage"] is None
    bazin_coverage = first["strategies"][1]["coverage"]
    assert bazin_coverage["source"] == "novera-synthetic-fixture"
    assert bazin_coverage["synthetic"] is True
    assert bazin_coverage["complete_by_fixture"] is (scenario != "incomplete")
    assert bazin_coverage["published_at"]
    for strategy in first["strategies"]:
        for metric in strategy["metrics"]:
            assert type(metric["value"]) is str or metric["value"] is None
            assert metric["quality"] in {"present", "missing"}
            assert (metric["value"] is None) is (metric["quality"] == "missing")
            assert metric["reason"]
        assert all(check["reason"] for check in strategy["criteria"])


@pytest.mark.parametrize("scenario", tuple(SCENARIOS))
def test_text_report_is_human_readable_and_explicitly_fictitious(scenario):
    report = run_scenario(scenario)
    rendered = render_text(report)
    assert DISCLAIMER in rendered
    assert "Bazin" in rendered.lower().title()
    assert "graham" in rendered.lower()
    assert "Proveniência e qualidade" in rendered
    assert "publicado" in rendered
    assert str(report.asset.identifier) in rendered
    assert "recomendação" in rendered


def test_installed_module_entrypoint_runs_without_credentials():
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "novera.research_demo",
            "--scenario",
            "incomplete",
            "--format",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    payload = json.loads(completed.stdout)
    assert payload["scenario"] == "incomplete"
    assert all(item["state"] == "unknown" for item in payload["strategies"])
    assert completed.stderr == ""


def test_cli_outputs_parseable_json_without_html_or_network(capsys):
    assert main(["--scenario", "complete", "--format", "json"]) == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["scenario"] == "complete"
    assert len(parsed["strategies"]) == 2
    assert captured.err == ""
    assert main(["--scenario", "incomplete", "--format", "text"]) == 0
    text_out = capsys.readouterr().out
    assert "UNKNOWN" in text_out
    assert "não certificada" in text_out


@pytest.mark.parametrize(
    "args", [["--scenario", "not-real"], ["--format", "xml"], ["--secret", "x"]]
)
def test_cli_rejects_unsupported_parameters(args):
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2


def test_invalid_scenario_never_opens_a_demo(capsys):
    with pytest.raises(ValueError, match="unknown"):
        run_scenario("BRAZIL")
    assert capsys.readouterr().out == ""


def test_local_demo_does_not_need_a_network_socket(monkeypatch):
    def deny_network(*_args, **_kwargs):
        raise AssertionError("research demo attempted a network socket")

    monkeypatch.setattr(socket, "socket", deny_network)
    report = run_scenario("complete")
    assert report.strategies[0].state is EvaluationState.PASS


def test_all_dates_and_receipts_are_consistent():
    report = run_scenario("complete")
    for item in report.receipts:
        assert item.observation.provenance.collected_at <= report.as_of
        assert item.observation.provenance.published_at <= report.as_of
        assert isinstance(
            datetime.fromisoformat(item.observation.provenance.collected_at.isoformat()), datetime
        )
        assert item.observation.asset == report.asset
        assert item.version == 1
    assert len({receipt.record_key for receipt in report.receipts}) == len(report.receipts)
