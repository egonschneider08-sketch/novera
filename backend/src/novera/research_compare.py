"""Auditable comparison of explicitly synthetic Novera research scenarios.

Comparison is descriptive and intentionally has no ranking, recommendation,
normalized investment score or real-provider data.
"""

import argparse
import csv
import io
import json
from dataclasses import dataclass
from typing import Sequence

from novera.research_demo import (
    DISCLAIMER,
    SCENARIOS,
    ResearchReport,
    report_json,
    run_scenario,
)

SCHEMA_VERSION = "novera-synthetic-comparison-v1"
CSV_COLUMNS = (
    "schema",
    "scenario",
    "asset",
    "as_of",
    "methodology",
    "rule_version",
    "summary_state",
    "row_type",
    "name",
    "value",
    "unit",
    "quality",
    "criterion_state",
    "reason",
    "source",
    "coverage_by_fixture",
    "receipt_ids",
    "synthetic",
    "disclaimer",
)


@dataclass(frozen=True, slots=True)
class ComparisonReport:
    reports: tuple[ResearchReport, ...]


def compare_scenarios(scenarios: Sequence[str] | None = None) -> ComparisonReport:
    """Select known fictional scenarios only; preserve selection order, never rank."""
    selected = tuple(SCENARIOS) if scenarios is None else scenarios
    if not isinstance(selected, (tuple, list)) or not selected:
        raise ValueError("at least one explicit synthetic scenario is required")
    if any(not isinstance(name, str) or name not in SCENARIOS for name in selected):
        raise ValueError("unsupported research scenario; only synthetic fixtures are allowed")
    if len(set(selected)) != len(selected):
        raise ValueError("duplicate research scenarios are not comparable entries")
    return ComparisonReport(tuple(run_scenario(name) for name in selected))


def comparison_json(comparison: ComparisonReport) -> dict:
    """Full provenance comes from the established NV-024 presentation schema."""
    return {
        "schema": SCHEMA_VERSION,
        "synthetic": True,
        "disclaimer": DISCLAIMER,
        "ordering": "user_selection_not_investment_ranking",
        "total_scenarios": len(comparison.reports),
        "reports": [report_json(report) for report in comparison.reports],
    }


def comparison_csv(comparison: ComparisonReport) -> str:
    """RFC-style CSV of metric and criterion rows, without changing Decimal precision."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for report in comparison.reports:
        source = "novera-synthetic-fixture"
        receipts = ";".join(item.receipt_id for item in report.receipts)
        for strategy in report.strategies:
            common = {
                "schema": SCHEMA_VERSION,
                "scenario": report.scenario,
                "asset": report.asset.identifier,
                "as_of": report.as_of.isoformat(),
                "methodology": strategy.methodology,
                "rule_version": strategy.rule_version,
                "summary_state": strategy.state.value,
                "source": source,
                "coverage_by_fixture": str(report.dividend_coverage_certified_by_fixture).lower(),
                "receipt_ids": receipts,
                "synthetic": "true",
                "disclaimer": DISCLAIMER,
            }
            for metric in strategy.metrics:
                writer.writerow(
                    {
                        **common,
                        "row_type": "metric",
                        "name": metric.name,
                        "value": str(metric.value) if metric.value is not None else "",
                        "unit": metric.unit,
                        "quality": metric.quality.value,
                        "reason": metric.reason,
                    }
                )
            for criterion in strategy.criteria:
                writer.writerow(
                    {
                        **common,
                        "row_type": "criterion",
                        "name": criterion.name,
                        "criterion_state": criterion.state.value,
                        "reason": criterion.reason,
                    }
                )
    return output.getvalue()


def render_comparison(comparison: ComparisonReport) -> str:
    """Human-readable comparison, not a financial ranking."""
    lines = [
        "NOVERA | Comparação de cenários inteiramente fictícios",
        "====================================================",
        DISCLAIMER,
        "Ordem exibida: seleção informada, nunca classificação por atratividade.",
        "",
    ]
    for report in comparison.reports:
        price = next(
            item.observation for item in report.receipts if item.observation.metric == "close"
        )
        lines.append(
            f"{report.asset.identifier} — {report.label} | preço fictício "
            f"{price.value} {price.currency} | {report.as_of.date().isoformat()}"
        )
        for strategy in report.strategies:
            available = sum(criterion.state.value != "unknown" for criterion in strategy.criteria)
            lines.append(
                f"  {strategy.methodology}: {strategy.state.value.upper()}"
                f" | {available}/{len(strategy.criteria)} critérios avaliáveis"
            )
            if strategy.state.value == "unknown":
                lines.append("    Parte dos critérios permanece não avaliável; nunca assumir FAIL.")
    lines.extend(
        [
            "",
            "Use --format json para consultar origens, períodos, versões e todos os motivos.",
            "Use --format csv para exportar linhas de métricas e critérios fictícios.",
            "NENHUM resultado constitui ranking de investimento ou sinal de compra/venda.",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare somente casos fictícios de pesquisa do Novera."
    )
    parser.add_argument("--scenario", action="append", choices=tuple(SCENARIOS), default=None)
    parser.add_argument("--format", choices=("text", "json", "csv"), default="text")
    args = parser.parse_args(argv)
    try:
        report = compare_scenarios(args.scenario)
    except ValueError as exc:
        parser.error(str(exc))
    if args.format == "json":
        print(json.dumps(comparison_json(report), ensure_ascii=False, indent=2, allow_nan=False))
    elif args.format == "csv":
        print(comparison_csv(report), end="")
    else:
        print(render_comparison(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
