"""Synthetic-only comparison and export integration tests."""

import csv
import io
import json
import socket
import subprocess
import sys

import pytest
from novera.research_compare import (
    CSV_COLUMNS,
    SCHEMA_VERSION,
    compare_scenarios,
    comparison_csv,
    comparison_json,
    main,
    render_comparison,
)
from novera.research_demo import DISCLAIMER, SCENARIOS


def test_default_comparison_preserves_explicit_scenario_order_without_ranking():
    comparison = compare_scenarios()
    assert tuple(item.scenario for item in comparison.reports) == tuple(SCENARIOS)
    actual_states = {
        item.scenario: tuple(strategy.state.value for strategy in item.strategies)
        for item in comparison.reports
    }
    assert actual_states == {
        "complete": ("pass", "pass"),
        "expensive": ("fail", "fail"),
        "incomplete": ("unknown", "unknown"),
    }


def test_selected_comparison_never_sorts_by_investment_state():
    comparison = compare_scenarios(["incomplete", "expensive", "complete"])
    assert tuple(report.scenario for report in comparison.reports) == (
        "incomplete",
        "expensive",
        "complete",
    )
    assert all(report.synthetic for report in comparison.reports)


@pytest.mark.parametrize(
    "invalid",
    [
        [],
        (),
        "complete",
        ["unknown"],
        ["complete", "complete"],
        ["complete", "PETR4"],
    ],
)
def test_only_distinct_reviewed_synthetic_fixtures_can_be_compared(invalid):
    with pytest.raises(ValueError):
        compare_scenarios(invalid)


def test_json_comparison_includes_full_auditable_per_scenario_evidence():
    payload = comparison_json(compare_scenarios())
    assert payload["schema"] == SCHEMA_VERSION
    assert payload["synthetic"] is True
    assert payload["ordering"] == "user_selection_not_investment_ranking"
    assert payload["disclaimer"] == DISCLAIMER
    assert payload["total_scenarios"] == 3
    assert tuple(item["scenario"] for item in payload["reports"]) == tuple(SCENARIOS)
    for report in payload["reports"]:
        assert report["synthetic"] is True
        assert report["share_basis"] == "unadjusted"
        assert report["observations"]
        assert all(row["source"]["synthetic"] for row in report["observations"])
        assert all(len(row["receipt_id"]) == 64 for row in report["observations"])
        for result in report["strategies"]:
            assert result["rule_version"]
            assert result["criteria"]
            for metric in result["metrics"]:
                assert isinstance(metric["value"], str) or metric["value"] is None
    serialized = json.dumps(payload, allow_nan=False, ensure_ascii=False)
    assert json.loads(serialized) == payload


def test_csv_has_fixed_schema_quality_and_source_without_float_conversion():
    comparison = compare_scenarios()
    exported = comparison_csv(comparison)
    rows = list(csv.DictReader(io.StringIO(exported)))
    assert exported.startswith(",".join(CSV_COLUMNS) + "\n")
    assert len(rows) == sum(
        len(strategy.metrics) + len(strategy.criteria)
        for report in comparison.reports
        for strategy in report.strategies
    )
    assert {row["row_type"] for row in rows} == {"metric", "criterion"}
    assert {row["synthetic"] for row in rows} == {"true"}
    assert {row["source"] for row in rows} == {"novera-synthetic-fixture"}
    assert all(row["receipt_ids"] for row in rows)
    assert all(row["disclaimer"] == DISCLAIMER for row in rows)
    assert all(row["as_of"] == "2026-10-28T23:00:00+00:00" for row in rows)
    assert all(row["rule_version"] for row in rows)
    for row in rows:
        if row["row_type"] == "metric":
            assert row["quality"] in {"present", "missing"}
            assert (row["value"] == "") is (row["quality"] == "missing")
            assert row["criterion_state"] == ""
        else:
            assert row["criterion_state"] in {"pass", "fail", "unknown"}
            assert row["quality"] == ""
            assert row["value"] == ""
        assert row["reason"]


def test_csv_incomplete_eps_never_appears_as_zero():
    csv_rows = list(csv.DictReader(io.StringIO(comparison_csv(compare_scenarios(["incomplete"])))))
    entries = [
        row
        for row in csv_rows
        if row["methodology"] == "graham-number-partial"
        and row["row_type"] == "metric"
        and row["name"] == "graham_number"
    ]
    assert len(entries) == 1
    assert entries[0]["quality"] == "missing"
    assert entries[0]["value"] == ""


def test_text_comparison_explains_synthetic_limits_and_unknown():
    text = render_comparison(compare_scenarios())
    assert "NOVERA" in text
    assert DISCLAIMER in text
    assert "UNKNOWN" in text
    assert "sem" not in text.lower() or "ranking" in text.lower()
    assert "ranking" in text.lower()
    assert "não avaliável" in text
    assert all(scenario[0] in text for scenario in SCENARIOS.values())


def test_csv_and_json_are_reproducible_without_network_sockets(monkeypatch):
    def blocked(*_args, **_kwargs):
        raise AssertionError("comparison attempted network I/O")

    monkeypatch.setattr(socket, "socket", blocked)
    first = compare_scenarios()
    second = compare_scenarios()
    assert comparison_json(first) == comparison_json(second)
    assert comparison_csv(first) == comparison_csv(second)


def test_cli_formats_and_scenario_selection(capsys):
    assert main(["--scenario", "incomplete", "--scenario", "complete", "--format", "json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert [item["scenario"] for item in result["reports"]] == ["incomplete", "complete"]
    assert main(["--scenario", "expensive", "--format", "csv"]) == 0
    csv_text = capsys.readouterr().out
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert {row["scenario"] for row in rows} == {"expensive"}


@pytest.mark.parametrize(
    "args",
    [
        ["--scenario", "invalid"],
        ["--scenario", "complete", "--scenario", "complete"],
        ["--format", "xml"],
    ],
)
def test_cli_rejects_unknown_options_or_duplicate_scenarios(args):
    with pytest.raises(SystemExit) as error:
        main(args)
    assert error.value.code == 2


def test_actual_python_module_entrypoint_produces_parseable_csv():
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "novera.research_compare",
            "--scenario",
            "complete",
            "--format",
            "csv",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    rows = list(csv.DictReader(io.StringIO(done.stdout)))
    assert rows
    assert {row["scenario"] for row in rows} == {"complete"}
    assert done.stderr == ""
