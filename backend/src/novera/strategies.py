"""Independent, educational valuation heuristics. No I/O, ranking or advice."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Context, Decimal, DecimalException, Underflow, localcontext
from enum import StrEnum

from novera.contracts import Asset, Observation, Period, Provenance, Quality, RecordKind


class EvaluationState(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PerShareInput:
    observation: Observation
    share_basis: str

    def __post_init__(self) -> None:
        if not isinstance(self.observation, Observation):
            raise ValueError("observation must be an Observation")
        if not isinstance(self.share_basis, str) or not self.share_basis.strip():
            raise ValueError("share_basis must explicitly identify adjustment convention")


@dataclass(frozen=True, slots=True)
class CashPayment:
    event_id: str
    data: PerShareInput

    def __post_init__(self) -> None:
        if not isinstance(self.event_id, str) or not self.event_id.strip():
            raise ValueError("event_id must identify the provider event for deduplication")
        if not isinstance(self.data, PerShareInput):
            raise ValueError("payment must contain PerShareInput")


@dataclass(frozen=True, slots=True)
class DividendHistory:
    asset: Asset
    payments: tuple[CashPayment, ...]
    coverage: Provenance
    complete: bool
    currency: str
    share_basis: str
    tax_basis: str

    def __post_init__(self) -> None:
        if not isinstance(self.asset, Asset) or not isinstance(self.coverage, Provenance):
            raise ValueError("history requires asset and coverage provenance")
        if type(self.complete) is not bool or type(self.payments) is not tuple:
            raise ValueError("complete must be bool and payments an immutable tuple")
        if not all(isinstance(item, CashPayment) for item in self.payments):
            raise ValueError("payments must contain CashPayment")
        for value in (self.currency, self.share_basis, self.tax_basis):
            if not isinstance(value, str) or not value.strip():
                raise ValueError("history conventions must be explicit")


@dataclass(frozen=True, slots=True)
class Criterion:
    name: str
    state: EvaluationState
    reason: str


@dataclass(frozen=True, slots=True)
class DerivedMetric:
    name: str
    value: Decimal | None
    unit: str
    currency: str | None
    period: Period
    reason: str

    @property
    def quality(self) -> Quality:
        return Quality.PRESENT if self.value is not None else Quality.MISSING


@dataclass(frozen=True, slots=True)
class StrategyResult:
    asset: Asset
    methodology: str
    rule_version: str
    as_of: datetime
    synthetic: bool
    metrics: tuple[DerivedMetric, ...]
    criteria: tuple[Criterion, ...]
    evidence: tuple[Observation, ...]
    coverage: Provenance | None = None
    parameters: tuple[tuple[str, str], ...] = ()

    @property
    def state(self) -> EvaluationState:
        if any(item.state is EvaluationState.UNKNOWN for item in self.criteria):
            return EvaluationState.UNKNOWN
        if any(item.state is EvaluationState.FAIL for item in self.criteria):
            return EvaluationState.FAIL
        return EvaluationState.PASS


def _decimal_context() -> Context:
    context = Context(prec=34, rounding=ROUND_HALF_EVEN)
    context.traps[Underflow] = True
    return context


def _as_of(value: datetime) -> date:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("as_of must be an explicit timezone-aware datetime")
    return value.astimezone(timezone.utc).date()


def _available(provenance: Provenance, as_of: datetime) -> str | None:
    if provenance.published_at is None:
        return "publication/availability time unknown"
    if provenance.published_at > as_of or provenance.collected_at > as_of:
        return "information not available at as_of (publication or collection)"
    return None


def _input_problem(
    data: PerShareInput, reference: PerShareInput, as_of: datetime, kind: RecordKind, metric: str
) -> str | None:
    item, anchor = data.observation, reference.observation
    if item.kind is not kind or item.metric != metric or item.unit != "currency/share":
        return "incompatible record kind, metric or unit"
    if item.asset != anchor.asset or item.currency != anchor.currency:
        return "asset or currency mismatch"
    if data.share_basis != reference.share_basis:
        return "incompatible per-share adjustment basis"
    if item.provenance.source.synthetic != anchor.provenance.source.synthetic:
        return "mixed synthetic and real evidence"
    if item.quality is not Quality.PRESENT:
        return f"input {item.quality}: {item.reason}"
    if item.provenance.period.end > _as_of(as_of):
        return "reference period is in the future"
    return _available(item.provenance, as_of)


def _criterion(name: str, passed: bool | None, reason: str) -> Criterion:
    state = (
        EvaluationState.UNKNOWN
        if passed is None
        else (EvaluationState.PASS if passed else EvaluationState.FAIL)
    )
    return Criterion(name, state, reason)


def graham(
    price: PerShareInput, eps: PerShareInput, bvps: PerShareInput, *, as_of: datetime
) -> StrategyResult:
    """Graham number and partial filters, not the full historical methodology."""
    day = _as_of(as_of)
    p, e, b = (item.observation for item in (price, eps, bvps))
    inputs = (price, eps, bvps)
    problems = [
        _input_problem(item, price, as_of, kind, metric)
        for item, kind, metric in (
            (price, RecordKind.PRICE, "close"),
            (eps, RecordKind.INDICATOR, "earnings_per_share"),
            (bvps, RecordKind.INDICATOR, "book_value_per_share"),
        )
    ]
    if p.adjustment != price.share_basis:
        problems[0] = "price adjustment metadata disagrees with share basis"
    if p.provenance.period.end != day:
        problems[0] = "price must reference the evaluation date"
    if (e.provenance.period.end - e.provenance.period.start).days + 1 not in (365, 366):
        problems[1] = "EPS must cover a full 365/366-day annual period"
    # An EPS duration ending on the same date as the BVPS balance is required.
    for index, observation in ((1, e), (2, b)):
        publication = observation.provenance.published_at
        if (
            publication is not None
            and publication.astimezone(timezone.utc).date() < observation.provenance.period.end
        ):
            problems[index] = "final fundamental published before reference period ended"
    if e.provenance.period.end != b.provenance.period.end:
        problems[1] = problems[2] = "EPS and BVPS reference dates differ"
    if b.provenance.period.start != b.provenance.period.end:
        problems[2] = "BVPS must reference a balance-sheet date"
    values = [
        None if problem else item.observation.value for problem, item in zip(problems, inputs)
    ]
    pv, ev, bv = values
    valid_price = pv is not None and pv > 0
    positive_fundamentals = ev is not None and bv is not None and ev > 0 and bv > 0
    reason = "; ".join(problem for problem in problems if problem)
    heuristic = pe = pb = margin = None
    arithmetic_problem = ""
    # Bound arithmetic independently of caller Decimal precision and traps.
    try:
        with localcontext(_decimal_context()):
            if positive_fundamentals:
                heuristic = (Decimal("22.5") * ev * bv).sqrt()
            if valid_price and ev is not None and ev > 0:
                pe = pv / ev
            if valid_price and bv is not None and bv > 0:
                pb = pv / bv
            if valid_price and heuristic is not None:
                margin = heuristic / pv - 1
            product_ok = pe * pb <= Decimal("22.5") if pe is not None and pb is not None else None
    except DecimalException:
        heuristic = pe = pb = margin = None
        product_ok = None
        arithmetic_problem = "decimal arithmetic outside supported range"
    unknown = reason or arithmetic_problem or "missing positive inputs or valid positive price"
    criteria = (
        _criterion(
            "positive_earnings",
            ev > 0 if ev is not None else None,
            problems[1] or "EPS must be positive",
        ),
        _criterion(
            "pe_at_most_15",
            pe <= 15 if pe is not None else None,
            "derived price/EPS <= 15" if pe is not None else unknown,
        ),
        _criterion(
            "pb_at_most_1_5",
            pb <= Decimal("1.5") if pb is not None else None,
            "derived price/BVPS <= 1.5" if pb is not None else unknown,
        ),
        _criterion(
            "pe_times_pb_at_most_22_5",
            product_ok,
            "derived multiple product <= 22.5" if product_ok is not None else unknown,
        ),
        _criterion(
            "price_at_most_graham_number",
            pv <= heuristic if valid_price and heuristic is not None else None,
            "price compared with educational heuristic" if margin is not None else unknown,
        ),
    )
    period = Period(day, day)
    metrics = tuple(
        DerivedMetric(
            name,
            value,
            unit,
            p.currency if unit == "currency/share" else None,
            period,
            "calculated from traced inputs" if value is not None else unknown,
        )
        for name, value, unit in (
            ("graham_number", heuristic, "currency/share"),
            ("pe", pe, "ratio"),
            ("pb", pb, "ratio"),
            ("margin", margin, "ratio"),
        )
    )
    return StrategyResult(
        p.asset,
        "graham-number-partial",
        "graham-number-v1",
        as_of,
        any(item.observation.provenance.source.synthetic for item in inputs),
        metrics,
        criteria,
        (p, e, b),
    )


def bazin(
    price: PerShareInput,
    history: DividendHistory,
    *,
    as_of: datetime,
    target_yield: Decimal = Decimal("0.06"),
) -> StrategyResult:
    """Five fixed 365-day cash-payment windows with explicit full coverage."""
    day = _as_of(as_of)
    if (
        not isinstance(target_yield, Decimal)
        or not target_yield.is_finite()
        or not 0 < target_yield <= 1
    ):
        raise ValueError("target_yield must be finite Decimal in (0, 1]")
    p = price.observation
    required = Period(day - timedelta(days=1824), day)
    issue = _input_problem(price, price, as_of, RecordKind.PRICE, "close")
    if p.adjustment != price.share_basis:
        issue = "price adjustment metadata disagrees with share basis"
    if p.provenance.period.end != day:
        issue = "price must reference the evaluation date"
    history_issue = _available(history.coverage, as_of)
    if (
        not history.complete
        or history.coverage.period.start > required.start
        or history.coverage.period.end < day
    ):
        history_issue = "full five-window history coverage is not certified"
    if (
        history.asset != p.asset
        or history.currency != p.currency
        or history.share_basis != price.share_basis
    ):
        history_issue = "history asset, currency or share basis mismatch"
    if history.tax_basis not in ("gross", "net"):
        history_issue = "dividend tax basis unknown"
    if history.coverage.source.synthetic != p.provenance.source.synthetic:
        history_issue = "mixed synthetic and real history"
    if history.coverage.period.end > day:
        history_issue = "coverage contains a future reference date"
    totals = [Decimal("0") for _ in range(5)]
    seen = set()
    future_events = 0
    try:
        with localcontext(_decimal_context()):
            for payment in history.payments:
                item = payment.data.observation
                if payment.event_id in seen:
                    history_issue = "duplicate payment event identifier"
                seen.add(payment.event_id)
                when = item.payment_date
                # Future payments are deliberately excluded, never treated as realized cash.
                if when is not None and when > day:
                    future_events += 1
                    continue
                error = _input_problem(
                    payment.data, price, as_of, RecordKind.DISTRIBUTION, "cash_distribution"
                )
                if when is None:
                    error = "payment date unknown"
                if item.tax_basis != history.tax_basis:
                    error = "inconsistent gross/net dividend basis"
                if item.value is not None and item.value < 0:
                    error = "negative distribution requires corporate-action reconciliation"
                if (
                    when is not None
                    and not history.coverage.period.start <= when <= history.coverage.period.end
                ):
                    error = "payment outside declared coverage"
                if error:
                    history_issue = error
                    continue
                age = (day - when).days
                if age < 1825:
                    totals[age // 365] += item.value
            average = sum(totals) / 5 if not history_issue else None
            ceiling = average / target_yield if average is not None else None
            valid_price = not issue and p.value is not None and p.value > 0
            yield_365d = totals[0] / p.value if not history_issue and valid_price else None
            margin = ceiling / p.value - 1 if ceiling is not None and valid_price else None
    except DecimalException:
        history_issue = "decimal arithmetic outside supported range"
        average = ceiling = yield_365d = margin = None
    reason = history_issue or issue or "positive price required"
    criteria = (
        _criterion(
            "price_at_most_ceiling",
            p.value <= ceiling if margin is not None else None,
            "price compared with educational ceiling" if margin is not None else reason,
        ),
        _criterion(
            "yield_at_least_target",
            yield_365d >= target_yield if yield_365d is not None else None,
            f"target yield {target_yield}" if yield_365d is not None else reason,
        ),
        _criterion(
            "paid_in_all_five_windows",
            all(value > 0 for value in totals) if not history_issue else None,
            history_issue or "certified coverage distinguishes zero from missing payments",
        ),
        _criterion(
            "latest_window_not_below_oldest",
            totals[0] >= totals[-1] > 0 if not history_issue else None,
            history_issue or "endpoint comparison only, not monotonic growth",
        ),
    )
    metric_values = (
        ("annual_average", average, "currency/share"),
        ("bazin_ceiling", ceiling, "currency/share"),
        ("yield_365d", yield_365d, "ratio"),
        ("margin", margin, "ratio"),
    )
    metrics = tuple(
        DerivedMetric(
            name,
            value,
            unit,
            p.currency if unit == "currency/share" else None,
            required,
            "calculated from certified coverage" if value is not None else reason,
        )
        for name, value, unit in metric_values
    )
    # Window totals are exposed only with adequate evidence, never fabricated as zeros.
    metrics += tuple(
        DerivedMetric(
            f"window_{i}",
            value if not history_issue else None,
            "currency/share",
            p.currency,
            Period(day - timedelta(days=365 * i + 364), day - timedelta(days=365 * i)),
            history_issue or f"realized cash; excluded future events: {future_events}",
        )
        for i, value in enumerate(totals)
    )
    evidence = (p,) + tuple(payment.data.observation for payment in history.payments)
    return StrategyResult(
        p.asset,
        "bazin-five-365-day-windows",
        "bazin-cash-v1",
        as_of,
        p.provenance.source.synthetic
        or history.coverage.source.synthetic
        or any(item.provenance.source.synthetic for item in evidence),
        metrics,
        criteria,
        evidence,
        history.coverage,
        (("target_yield", str(target_yield)), ("window_days", "365"), ("window_count", "5")),
    )
