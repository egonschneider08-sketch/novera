"""Synthetic finance fixtures; no provider data or copied reference implementation."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, Inexact, localcontext

import pytest
from novera.contracts import Asset, Observation, Period, Provenance, Quality, RecordKind, Source
from novera.strategies import (
    CashPayment,
    DividendHistory,
    EvaluationState,
    PerShareInput,
    bazin,
    graham,
)

DAY = date(2026, 10, 28)
AS_OF = datetime(2026, 10, 28, 23, tzinfo=timezone.utc)
ASSET = Asset("synthetic", "asset-1")
BASIS = "unadjusted"


def provenance(period, ref="fixture"):
    return Provenance(
        Source("synthetic-tests", ref, "fixture-v1", True),
        period,
        AS_OF - timedelta(minutes=1),
        AS_OF - timedelta(hours=1),
    )


def data(metric, value, *, kind=RecordKind.INDICATOR, period=None, **changes):
    period = period or Period(DAY, DAY)
    fields = dict(
        asset=ASSET,
        kind=kind,
        metric=metric,
        value=Decimal(value) if value is not None else None,
        quality=Quality.PRESENT if value is not None else Quality.MISSING,
        unit="currency/share",
        currency="BRL",
        provenance=provenance(period),
        reason=None if value is not None else "synthetic missing input",
    )
    fields.update(changes)
    return PerShareInput(Observation(**fields), BASIS)


def price(value="20"):
    return data("close", value, kind=RecordKind.PRICE, adjustment=BASIS)


def fundamentals(eps="2", bvps="20"):
    return (
        data("earnings_per_share", eps, period=Period(date(2025, 1, 1), date(2025, 12, 31))),
        data("book_value_per_share", bvps, period=Period(date(2025, 12, 31), date(2025, 12, 31))),
    )


def payment(age, value="0.6", event_id=None, **changes):
    when = DAY - timedelta(days=age)
    item = data(
        "cash_distribution",
        value,
        kind=RecordKind.DISTRIBUTION,
        period=Period(when, when),
        payment_date=when,
        distribution_type="dividend",
        tax_basis="gross",
        **changes,
    )
    return CashPayment(event_id or f"synthetic-event-{age}", item)


def history(payments=None, **changes):
    period = Period(DAY - timedelta(days=1824), DAY)
    fields = dict(
        asset=ASSET,
        payments=tuple(payment(180 + 365 * i) for i in range(5))
        if payments is None
        else tuple(payments),
        coverage=provenance(period, "coverage"),
        complete=True,
        currency="BRL",
        share_basis=BASIS,
        tax_basis="gross",
    )
    return DividendHistory(**(fields | changes))


def metric(result, name):
    return next(item for item in result.metrics if item.name == name)


def check(result, name):
    return next(item for item in result.criteria if item.name == name)


def changed(item, **kwargs):
    return replace(item, observation=replace(item.observation, **kwargs))


def test_graham_known_fixture_matches_documented_reference_number_only():
    result = graham(price(), *fundamentals(), as_of=AS_OF)
    assert metric(result, "graham_number").value == Decimal("30")
    assert metric(result, "margin").value == Decimal("0.5")
    assert result.state is EvaluationState.PASS
    assert result.rule_version == "graham-number-v1"
    assert result.synthetic is True
    assert len(result.evidence) == 3


def test_bazin_known_complete_fixture_matches_reference_ceiling_only():
    result = bazin(price("8"), history(), as_of=AS_OF)
    assert metric(result, "bazin_ceiling").value == Decimal("10")
    assert metric(result, "annual_average").value == Decimal("0.6")
    assert metric(result, "yield_365d").value == Decimal("0.075")
    assert result.state is EvaluationState.PASS
    assert result.coverage is not None


@pytest.mark.parametrize("quality", [Quality.MISSING, Quality.INVALID, Quality.NOT_APPLICABLE])
def test_graham_unavailable_eps_does_not_become_failed_check(quality):
    eps, bvps = fundamentals()
    eps = changed(eps, value=None, quality=quality, reason="not evaluable")
    result = graham(price(), eps, bvps, as_of=AS_OF)
    assert check(result, "positive_earnings").state is EvaluationState.UNKNOWN
    assert metric(result, "graham_number").value is None
    assert result.state is EvaluationState.UNKNOWN


@pytest.mark.parametrize("eps_value", ["0", "-1"])
def test_known_nonpositive_eps_fails_positive_rule_but_heuristic_is_undefined(eps_value):
    result = graham(price(), *fundamentals(eps=eps_value), as_of=AS_OF)
    assert check(result, "positive_earnings").state is EvaluationState.FAIL
    assert metric(result, "graham_number").value is None
    assert check(result, "pe_at_most_15").state is EvaluationState.UNKNOWN


@pytest.mark.parametrize("bvps", ["0", "-20", None])
def test_nonpositive_or_missing_book_value_has_no_number(bvps):
    assert (
        metric(graham(price(), *fundamentals(bvps=bvps), as_of=AS_OF), "graham_number").value
        is None
    )


@pytest.mark.parametrize("value", ["0", None])
def test_nonpositive_or_missing_price_does_not_prevent_fundamental_number(value):
    result = graham(price(value), *fundamentals(), as_of=AS_OF)
    assert metric(result, "graham_number").value == Decimal("30")
    assert metric(result, "margin").value is None
    assert check(result, "price_at_most_graham_number").state is EvaluationState.UNKNOWN


@pytest.mark.parametrize(
    "field,value",
    [
        ("asset", Asset("synthetic", "other")),
        ("currency", "USD"),
        ("unit", "ratio"),
        ("metric", "quarter_eps"),
    ],
)
def test_graham_rejects_incompatible_metadata_as_unknown(field, value):
    eps, bvps = fundamentals()
    result = graham(price(), changed(eps, **{field: value}), bvps, as_of=AS_OF)
    assert metric(result, "graham_number").value is None
    assert result.state is EvaluationState.UNKNOWN


def test_adjustment_basis_must_match():
    eps, bvps = fundamentals()
    result = graham(price(), replace(eps, share_basis="split-adjusted:other"), bvps, as_of=AS_OF)
    assert metric(result, "graham_number").value is None


def test_eps_and_book_balance_reference_dates_must_align():
    eps, bvps = fundamentals()
    bvps = changed(bvps, provenance=provenance(Period(date(2024, 12, 31), date(2024, 12, 31))))
    assert metric(graham(price(), eps, bvps, as_of=AS_OF), "graham_number").value is None


def test_quarter_eps_is_not_annualized_silently():
    eps, bvps = fundamentals()
    eps = changed(eps, provenance=provenance(Period(date(2025, 10, 1), date(2025, 12, 31))))
    assert metric(graham(price(), eps, bvps, as_of=AS_OF), "graham_number").value is None


@pytest.mark.parametrize("field", ["collected_at", "published_at"])
def test_future_knowledge_is_not_used(field):
    eps, bvps = fundamentals()
    prov = eps.observation.provenance
    future = AS_OF + timedelta(days=1)
    updates = {"collected_at": future}
    if field == "published_at":
        updates["published_at"] = future
    eps = changed(eps, provenance=replace(prov, **updates))
    assert metric(graham(price(), eps, bvps, as_of=AS_OF), "graham_number").value is None


def test_unknown_publication_is_not_assumed_available():
    eps, bvps = fundamentals()
    eps = changed(
        eps,
        provenance=replace(
            eps.observation.provenance, published_at=None, publication_unknown_reason="unknown"
        ),
    )
    assert metric(graham(price(), eps, bvps, as_of=AS_OF), "graham_number").value is None


def test_mixed_synthetic_and_real_inputs_are_not_combined():
    eps, bvps = fundamentals()
    prov = eps.observation.provenance
    eps = changed(eps, provenance=replace(prov, source=replace(prov.source, synthetic=False)))
    assert metric(graham(price(), eps, bvps, as_of=AS_OF), "graham_number").value is None


def test_decimal_result_does_not_depend_on_callers_precision_or_traps():
    eps, bvps = fundamentals(eps="2.123456789", bvps="20.123456789")
    expected = metric(graham(price(), eps, bvps, as_of=AS_OF), "graham_number").value
    with localcontext() as context:
        context.prec = 4
        context.traps[Inexact] = True
        result = graham(price(), eps, bvps, as_of=AS_OF)
    assert metric(result, "graham_number").value == expected


@pytest.mark.parametrize("payments,complete", [([], False), ([payment(10)], False)])
def test_incomplete_history_is_unknown_not_zero_or_failed(payments, complete):
    result = bazin(price(), history(payments, complete=complete), as_of=AS_OF)
    assert all(item.state is EvaluationState.UNKNOWN for item in result.criteria)
    assert all(item.value is None for item in result.metrics)


def test_certified_empty_history_is_known_zero_and_can_fail_a_rule():
    result = bazin(price(), history([]), as_of=AS_OF)
    assert metric(result, "annual_average").value == Decimal("0")
    assert metric(result, "bazin_ceiling").value == Decimal("0")
    assert check(result, "paid_in_all_five_windows").state is EvaluationState.FAIL
    assert result.state is EvaluationState.FAIL


def test_fixed_window_boundaries_and_future_cash_exclusion():
    payments = [payment(age, "1") for age in (0, 364, 365, 1824, -1)]
    result = bazin(price(), history(payments), as_of=AS_OF)
    assert metric(result, "window_0").value == Decimal("2")
    assert metric(result, "window_1").value == Decimal("1")
    assert metric(result, "window_4").value == Decimal("1")
    assert metric(result, "annual_average").value == Decimal("0.8")


@pytest.mark.parametrize(
    "changes",
    [
        dict(complete=False),
        dict(currency="USD"),
        dict(share_basis="other"),
        dict(tax_basis="unknown"),
        dict(coverage=provenance(Period(DAY - timedelta(days=100), DAY))),
    ],
)
def test_bazin_requires_coverage_and_conventions(changes):
    result = bazin(price(), history(**changes), as_of=AS_OF)
    assert metric(result, "bazin_ceiling").value is None


@pytest.mark.parametrize(
    "payment_change", [dict(payment_date=None), dict(tax_basis="net"), dict(value=Decimal("-1"))]
)
def test_bad_payment_makes_history_unevaluable(payment_change):
    pay = payment(10)
    pay = replace(pay, data=changed(pay.data, **payment_change))
    result = bazin(price(), history([pay]), as_of=AS_OF)
    assert result.state is EvaluationState.UNKNOWN
    assert metric(result, "bazin_ceiling").value is None


def test_duplicate_event_not_double_counted():
    pay = payment(10)
    result = bazin(price(), history([pay, pay]), as_of=AS_OF)
    assert metric(result, "bazin_ceiling").value is None


def test_partial_payment_value_is_not_implicitly_zero():
    result = bazin(price(), history([payment(10, None)]), as_of=AS_OF)
    assert metric(result, "annual_average").value is None


def test_custom_target_is_used_and_is_versioned_in_reason():
    result = bazin(price("8"), history(), as_of=AS_OF, target_yield=Decimal("0.1"))
    assert metric(result, "bazin_ceiling").value == Decimal("6")
    assert check(result, "yield_at_least_target").state is EvaluationState.FAIL
    assert "0.1" in check(result, "yield_at_least_target").reason


@pytest.mark.parametrize(
    "target",
    [Decimal("0"), Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), Decimal("1.1"), 0.06],
)
def test_bad_target_yield_is_configuration_error(target):
    with pytest.raises(ValueError):
        bazin(price(), history(), as_of=AS_OF, target_yield=target)


def test_invalid_price_does_not_hide_independent_cash_history():
    result = bazin(price(None), history(), as_of=AS_OF)
    assert metric(result, "bazin_ceiling").value == Decimal("10")
    assert metric(result, "margin").value is None
    assert check(result, "paid_in_all_five_windows").state is EvaluationState.PASS


def test_inputs_are_not_mutated():
    p, h = price(), history()
    first = bazin(p, h, as_of=AS_OF)
    assert bazin(p, h, as_of=AS_OF) == first
    assert p.observation.value == Decimal("20")


def test_as_of_must_be_explicit_and_aware():
    with pytest.raises(ValueError):
        graham(price(), *fundamentals(), as_of=datetime(2026, 10, 28))


def test_stale_price_is_not_used_for_comparison():
    p = price()
    yesterday = DAY - timedelta(days=1)
    p = changed(p, provenance=provenance(Period(yesterday, yesterday)))
    result = graham(p, *fundamentals(), as_of=AS_OF)
    assert metric(result, "margin").value is None
    assert metric(result, "graham_number").value == Decimal("30")
    assert metric(bazin(p, history(), as_of=AS_OF), "margin").value is None


def test_bazin_unknown_coverage_publication_is_not_available():
    h = history()
    h = replace(
        h, coverage=replace(h.coverage, published_at=None, publication_unknown_reason="not known")
    )
    assert metric(bazin(price(), h, as_of=AS_OF), "annual_average").value is None


def test_bazin_future_collected_payment_is_not_used():
    pay = payment(10)
    pay = replace(
        pay,
        data=changed(
            pay.data,
            provenance=replace(
                pay.data.observation.provenance, collected_at=AS_OF + timedelta(days=1)
            ),
        ),
    )
    assert metric(bazin(price(), history([pay]), as_of=AS_OF), "annual_average").value is None


def test_bazin_only_counts_five_windows_from_longer_certified_history():
    h = history([payment(1824, "1"), payment(1825, "99")])
    h = replace(h, coverage=replace(h.coverage, period=Period(DAY - timedelta(days=1825), DAY)))
    assert metric(bazin(price(), h, as_of=AS_OF), "annual_average").value == Decimal("0.2")


def test_bazin_decimal_arithmetic_is_independent_of_caller_context():
    expected = bazin(price("8"), history(), as_of=AS_OF)
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        assert bazin(price("8"), history(), as_of=AS_OF) == expected


def test_bazin_leap_day_is_a_fixed_day_window_not_calendar_year():
    day = date(2028, 2, 29)
    timestamp = datetime(2028, 2, 29, 23, tzinfo=timezone.utc)
    p = changed(price(), provenance=provenance(Period(day, day)))
    when = day - timedelta(days=365)
    pay = payment(0, "1")
    pay = replace(
        pay, data=changed(pay.data, payment_date=when, provenance=provenance(Period(when, when)))
    )
    h = history([pay], coverage=provenance(Period(day - timedelta(days=1824), day)))
    result = bazin(p, h, as_of=timestamp)
    assert metric(result, "window_0").value == Decimal("0")
    assert metric(result, "window_1").value == Decimal("1")


def test_extreme_decimal_range_returns_unknown_without_crashing():
    result = graham(price(), *fundamentals(eps="1e999999", bvps="1e999999"), as_of=AS_OF)
    assert metric(result, "graham_number").value is None
    assert result.state is EvaluationState.UNKNOWN


def test_result_carries_parameters_and_original_provenance():
    p, h = price("8"), history()
    result = bazin(p, h, as_of=AS_OF, target_yield=Decimal("0.1"))
    assert dict(result.parameters) == {
        "target_yield": "0.1",
        "window_days": "365",
        "window_count": "5",
    }
    assert result.evidence[0] is p.observation
    assert result.coverage is h.coverage
    assert metric(result, "bazin_ceiling").currency == "BRL"
    assert metric(result, "margin").currency is None


def test_domain_execution_does_not_use_python_network_entries(monkeypatch):
    import socket

    def forbidden(*args, **kwargs):
        raise AssertionError("network entry called")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    assert graham(price(), *fundamentals(), as_of=AS_OF).state is EvaluationState.PASS
    assert bazin(price("8"), history(), as_of=AS_OF).state is EvaluationState.PASS


def test_underflow_is_unknown_instead_of_silent_zero():
    result = graham(price(), *fundamentals(eps="1e-999999", bvps="1e-999999"), as_of=AS_OF)
    assert metric(result, "graham_number").value is None


def test_final_earnings_cannot_be_published_before_period_end():
    eps, bvps = fundamentals()
    eps = changed(
        eps,
        provenance=replace(
            eps.observation.provenance, published_at=datetime(2025, 1, 1, tzinfo=timezone.utc)
        ),
    )
    assert metric(graham(price(), eps, bvps, as_of=AS_OF), "graham_number").value is None
