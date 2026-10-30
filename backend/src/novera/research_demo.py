"""Offline research journey built exclusively from fictional, traceable observations.

The fixture's coverage certification is a *synthetic scenario assertion*, not
proof that real-world dividends, share adjustments or publication dates exist.
Provider adapters cannot supply the certified close/EPS/BVPS needed here yet.
"""

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Sequence

from novera.contracts import Asset, Observation, Period, Provenance, Quality, RecordKind, Source
from novera.storage import ObservationStore, StorageScope, StoredObservation
from novera.strategies import (
    CashPayment,
    DividendHistory,
    PerShareInput,
    StrategyResult,
    bazin,
    graham,
)

AS_OF = datetime(2026, 10, 28, 23, tzinfo=timezone.utc)
REFERENCE_DAY = AS_OF.date()
SHARE_BASIS = "unadjusted"
SCHEMA_VERSION = "novera-synthetic-research-v1"
SCENARIOS = {
    "complete": ("LAB-A", "Laboratório Aurora — exemplo favorável"),
    "expensive": ("LAB-B", "Laboratório Horizonte — preço elevado"),
    "incomplete": ("LAB-C", "Laboratório Lacuna — dados insuficientes"),
}
SCOPE = StorageScope("novera-demo", "synthetic-only", "fixture-v1")
SOURCE = Source(
    "novera-synthetic-fixture",
    "https://example.invalid/novera/research/demo-v1",
    SCHEMA_VERSION,
    True,
)
DISCLAIMER = (
    "DADOS 100% FICTÍCIOS. Não representam ativos, empresas, cotações ou "
    "rendimentos reais. Resultados didáticos não são recomendação de investimento."
)


@dataclass(frozen=True, slots=True)
class ResearchReport:
    scenario: str
    label: str
    asset: Asset
    as_of: datetime
    receipts: tuple[StoredObservation, ...]
    strategies: tuple[StrategyResult, StrategyResult]
    dividend_coverage_certified_by_fixture: bool

    @property
    def synthetic(self) -> bool:
        return True


def _provenance(period: Period, *, published_at: datetime) -> Provenance:
    return Provenance(
        SOURCE,
        period,
        AS_OF - timedelta(minutes=10),
        published_at,
    )


def _observation(
    asset: Asset,
    metric: str,
    raw_value: str | None,
    period: Period,
    *,
    kind: RecordKind = RecordKind.INDICATOR,
    published_at: datetime,
    **metadata: object,
) -> Observation:
    return Observation(
        asset=asset,
        kind=kind,
        metric=metric,
        value=Decimal(raw_value) if raw_value is not None else None,
        quality=Quality.PRESENT if raw_value is not None else Quality.MISSING,
        unit="currency/share",
        currency="BRL",
        provenance=_provenance(period, published_at=published_at),
        reason=None if raw_value is not None else "fixture deliberately lacks annual EPS",
        **metadata,
    )


def _seed_demo(store: ObservationStore, scenario: str) -> tuple[StoredObservation, ...]:
    """Write only reviewed, deterministic synthetic fixtures to the approved scope."""
    if scenario not in SCENARIOS:
        raise ValueError("unknown synthetic research scenario")
    if store.scope != SCOPE or store.synthetic is not True:
        raise ValueError("demo fixtures require a matching synthetic storage scope")

    asset = Asset("novera.demo", SCENARIOS[scenario][0])
    day = REFERENCE_DAY
    balance_day = date(2025, 12, 31)
    publication = datetime(2026, 3, 15, 16, tzinfo=timezone.utc)
    records: list[tuple[str, Observation]] = [
        (
            "close:" + day.isoformat(),
            _observation(
                asset,
                "close",
                "35" if scenario == "expensive" else "8",
                Period(day, day),
                kind=RecordKind.PRICE,
                published_at=AS_OF - timedelta(minutes=20),
                adjustment=SHARE_BASIS,
            ),
        ),
        (
            "eps:2025",
            _observation(
                asset,
                "earnings_per_share",
                None if scenario == "incomplete" else "2",
                Period(date(2025, 1, 1), balance_day),
                published_at=publication,
            ),
        ),
        (
            "bvps:2025",
            _observation(
                asset,
                "book_value_per_share",
                "20",
                Period(balance_day, balance_day),
                published_at=publication,
            ),
        ),
    ]

    for index in range(1 if scenario == "incomplete" else 5):
        payment_day = day - timedelta(days=180 + index * 365)
        payment_publication = datetime.combine(
            payment_day, time(12, tzinfo=timezone.utc)
        )
        records.append(
            (
                f"cash-payment-{index}",
                _observation(
                    asset,
                    "cash_distribution",
                    "0.6",
                    Period(payment_day, payment_day),
                    kind=RecordKind.DISTRIBUTION,
                    published_at=payment_publication,
                    distribution_type="dividend",
                    tax_basis="gross",
                    ex_date=payment_day,
                    payment_date=payment_day,
                ),
            )
        )
    return store.ingest_many(records)


def _read_one(
    store: ObservationStore, asset: Asset, kind: RecordKind, metric: str, period: Period
) -> StoredObservation:
    rows = store.query(asset=asset, kind=kind, metric=metric, period=period)
    if len(rows) != 1:
        raise ValueError("synthetic fixture is ambiguous or incomplete")
    return rows[0]


def _build_report(store: ObservationStore, scenario: str) -> ResearchReport:
    """Read persisted values before evaluating; no calculation from raw seed objects."""
    asset = Asset("novera.demo", SCENARIOS[scenario][0])
    day = REFERENCE_DAY
    balance_day = date(2025, 12, 31)
    price = _read_one(store, asset, RecordKind.PRICE, "close", Period(day, day))
    eps = _read_one(
        store,
        asset,
        RecordKind.INDICATOR,
        "earnings_per_share",
        Period(date(2025, 1, 1), balance_day),
    )
    bvps = _read_one(
        store, asset, RecordKind.INDICATOR, "book_value_per_share", Period(balance_day, balance_day)
    )
    dividends = store.query(
        asset=asset,
        kind=RecordKind.DISTRIBUTION,
        metric="cash_distribution",
        period=Period(day - timedelta(days=1824), day),
    )
    complete = scenario != "incomplete"
    if len(dividends) != (5 if complete else 1):
        raise ValueError("synthetic dividend fixture differs from its declared manifest")
    if any(row.observation.provenance.source != SOURCE for row in (price, eps, bvps, *dividends)):
        raise ValueError("unrecognized source in synthetic research fixture")
    input_price = PerShareInput(price.observation, SHARE_BASIS)
    input_eps = PerShareInput(eps.observation, SHARE_BASIS)
    input_bvps = PerShareInput(bvps.observation, SHARE_BASIS)
    cash = tuple(
        CashPayment(receipt.record_key, PerShareInput(receipt.observation, SHARE_BASIS))
        for receipt in dividends
    )
    coverage_period = Period(
        day - timedelta(days=1824 if complete else 364), day
    )
    coverage = _provenance(
        coverage_period, published_at=AS_OF - timedelta(minutes=20)
    )
    history = DividendHistory(
        asset=asset,
        payments=cash,
        coverage=coverage,
        complete=complete,
        currency="BRL",
        share_basis=SHARE_BASIS,
        tax_basis="gross",
    )
    graham_result = graham(input_price, input_eps, input_bvps, as_of=AS_OF)
    bazin_result = bazin(input_price, history, as_of=AS_OF)
    return ResearchReport(
        scenario,
        SCENARIOS[scenario][1],
        asset,
        AS_OF,
        (price, eps, bvps, *dividends),
        (graham_result, bazin_result),
        complete,
    )


def run_scenario(scenario: str = "complete") -> ResearchReport:
    """Always uses disposable SQLite memory, known fictional data and no transport."""
    if scenario not in SCENARIOS:
        raise ValueError("unknown synthetic research scenario")
    with ObservationStore.memory(scope=SCOPE, synthetic=True) as store:
        _seed_demo(store, scenario)
        return _build_report(store, scenario)


def _observation_json(receipt: StoredObservation) -> dict:
    obs = receipt.observation
    prov = obs.provenance
    return {
        "record_key": receipt.record_key,
        "logical_id": receipt.logical_id,
        "version": receipt.version,
        "content_id": receipt.content_id,
        "receipt_id": receipt.receipt_id,
        "kind": obs.kind.value,
        "metric": obs.metric,
        "value": str(obs.value) if obs.value is not None else None,
        "quality": obs.quality.value,
        "reason": obs.reason,
        "unit": obs.unit,
        "currency": obs.currency,
        "reference_period": {
            "start": prov.period.start.isoformat(),
            "end": prov.period.end.isoformat(),
        },
        "source": {
            "provider": prov.source.provider,
            "reference": prov.source.reference,
            "rule_version": prov.source.rule_version,
            "synthetic": prov.source.synthetic,
        },
        "collected_at": prov.collected_at.isoformat(),
        "published_at": prov.published_at.isoformat() if prov.published_at else None,
        "publication_unknown_reason": prov.publication_unknown_reason,
    }


def report_json(report: ResearchReport) -> dict:
    """Stable, readable presentation format; Decimal never becomes a JSON float."""
    return {
        "schema": SCHEMA_VERSION,
        "scenario": report.scenario,
        "label": report.label,
        "asset": {
            "namespace": report.asset.namespace,
            "identifier": report.asset.identifier,
        },
        "as_of": report.as_of.isoformat(),
        "synthetic": True,
        "disclaimer": DISCLAIMER,
        "share_basis": SHARE_BASIS,
        "dividend_coverage_certified_by_fixture": report.dividend_coverage_certified_by_fixture,
        "observations": [_observation_json(item) for item in report.receipts],
        "strategies": [
            {
                "methodology": strategy.methodology,
                "rule_version": strategy.rule_version,
                "state": strategy.state.value,
                "as_of": strategy.as_of.isoformat(),
                "synthetic": strategy.synthetic,
                "metrics": [
                    {
                        "name": metric.name,
                        "value": str(metric.value) if metric.value is not None else None,
                        "unit": metric.unit,
                        "currency": metric.currency,
                        "period": {
                            "start": metric.period.start.isoformat(),
                            "end": metric.period.end.isoformat(),
                        },
                        "reason": metric.reason,
                    }
                    for metric in strategy.metrics
                ],
                "criteria": [
                    {
                        "name": criterion.name,
                        "state": criterion.state.value,
                        "reason": criterion.reason,
                    }
                    for criterion in strategy.criteria
                ],
            }
            for strategy in report.strategies
        ],
    }


def render_text(report: ResearchReport) -> str:
    """Compact research journey intended for a human reading a terminal."""
    lines = [
        "NOVERA | Laboratório de pesquisa financeira",
        "================================================",
        DISCLAIMER,
        f"Cenário: {report.scenario} | {report.label}",
        f"Ativo fictício: {report.asset.identifier}",
        f"Referência: {report.as_of.isoformat()} | Moeda: BRL",
        f"Base por ação: {SHARE_BASIS}",
        f"Observações recuperadas do SQLite: {len(report.receipts)}",
        (
            "Cobertura dos proventos (somente fixture): "
            + ("declarada completa" if report.dividend_coverage_certified_by_fixture
               else "não certificada")
        ),
    ]
    for strategy in report.strategies:
        lines.extend(
            [
                "",
                f"{strategy.methodology} [{strategy.state.value.upper()}]",
                f"Regra: {strategy.rule_version}",
                "Métricas calculadas:",
            ]
        )
        for metric in strategy.metrics:
            value = str(metric.value) if metric.value is not None else "não avaliável"
            lines.append(f"  {metric.name}: {value} {metric.unit} — {metric.reason}")
        lines.append("Critérios e justificativas:")
        for criterion in strategy.criteria:
            lines.append(
                f"  [{criterion.state.value.upper()}] {criterion.name}: {criterion.reason}"
            )
    lines.extend(
        [
            "",
            "Proveniência e qualidade (recibos SQLite):",
        ]
    )
    for receipt in report.receipts:
        observation = receipt.observation
        lines.append(
            f"  {receipt.record_key} | {observation.metric}: "
            f"{observation.value if observation.value is not None else 'ausente'} "
            f"({observation.quality.value}) | versão {receipt.version} | "
            f"fonte {observation.provenance.source.provider} | "
            f"publicado {observation.provenance.published_at.isoformat() if observation.provenance.published_at else 'desconhecido'}"
        )
    lines.extend(
        [
            "",
            "Limites: cobertura de dividendos é uma premissa inventada e explícita "
            "deste cenário; não verificada por provedores reais.",
            "A brapi não fornece um fechamento ajustado certificado neste produto, "
            "e o SGS não fornece EPS/BVPS/proventos.",
            "Nenhum calendário B3, ajuste corporativo, backtest ou "
            "garantia de disponibilidade histórica foi validado.",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pesquisa demonstrável Novera: cenários financeiros inteiramente fictícios."
    )
    parser.add_argument(
        "--scenario", choices=tuple(SCENARIOS), default="complete"
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    report = run_scenario(args.scenario)
    if args.format == "json":
        print(json.dumps(report_json(report), ensure_ascii=False, indent=2, allow_nan=False))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
