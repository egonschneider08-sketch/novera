"""Synthetic fixtures only: no market values, credentials or external requests."""

from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from novera.contracts import Asset, Observation, Period, Provenance, Quality, RecordKind, Source


def observation(**changes):
    source = Source("synthetic-test", "fixture:contract-v1", "1", True)
    provenance = Provenance(
        source,
        Period(date(2025, 1, 1), date(2025, 12, 31)),
        datetime(2026, 3, 1, tzinfo=timezone.utc),
        datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    fields = dict(
        asset=Asset("test", "asset-1"),
        kind=RecordKind.INDICATOR,
        metric="earnings_per_share",
        value=Decimal("0"),
        quality=Quality.PRESENT,
        unit="currency/share",
        currency="BRL",
        provenance=provenance,
    )
    return Observation(**(fields | changes))


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-2.50"), Decimal("12.345678901")])
def test_indicator_retains_zero_negative_and_decimal_precision(value):
    assert observation(value=value).value == value


@pytest.mark.parametrize("quality", [Quality.MISSING, Quality.INVALID, Quality.NOT_APPLICABLE])
def test_non_present_states_are_explicit(quality):
    result = observation(value=None, quality=quality, reason="synthetic reason")
    assert result.value is None
    assert result.quality is quality
    assert result.quality is not Quality.PRESENT


@pytest.mark.parametrize(
    "changes",
    [
        {"value": None},
        {"value": 0},
        {"value": 1.5},
        {"value": True},
        {"value": Decimal("NaN")},
        {"value": Decimal("Infinity")},
        {"quality": Quality.MISSING},
        {"quality": Quality.INVALID, "value": None},
        {"quality": Quality.NOT_APPLICABLE, "value": None, "reason": " "},
        {"currency": "brl"},
        {"unit": ""},
        {"metric": " "},
        {"quality": "present"},
        {"kind": "indicator"},
        {"asset": "PETR4"},
        {"provenance": None},
        {"reason": "contradictory reason"},
        {"statement_scope": "consolidated"},
        {"payment_date": date(2026, 1, 1)},
    ],
)
def test_reject_invalid_observations(changes):
    with pytest.raises(ValueError):
        observation(**changes)


def test_unknown_publication_requires_reason_and_does_not_infer_availability():
    provenance = replace(
        observation().provenance,
        published_at=None,
        publication_unknown_reason="provider omits publication",
    )
    assert provenance.published_at is None
    with pytest.raises(ValueError):
        replace(provenance, publication_unknown_reason=None)


@pytest.mark.parametrize(
    "changes",
    [
        {"collected_at": datetime(2026, 3, 1)},
        {"published_at": datetime(2026, 2, 1)},
        {"published_at": datetime(2027, 1, 1, tzinfo=timezone.utc)},
        {"publication_unknown_reason": "contradiction"},
        {"source": None},
        {"period": None},
    ],
)
def test_provenance_rejects_invalid_chronology_or_types(changes):
    with pytest.raises(ValueError):
        replace(observation().provenance, **changes)


def test_period_validation():
    with pytest.raises(ValueError):
        Period(date(2026, 1, 1), date(2025, 1, 1))
    with pytest.raises(ValueError):
        Period(datetime(2025, 1, 1), date(2025, 1, 1))


def price(**changes):
    provenance = replace(
        observation().provenance, period=Period(date(2025, 12, 31), date(2025, 12, 31))
    )
    return observation(
        **(
            dict(
                kind=RecordKind.PRICE,
                metric="close",
                provenance=provenance,
                adjustment="unadjusted",
            )
            | changes
        )
    )


def test_price_zero_is_present_but_negative_is_rejected():
    assert price().value == Decimal("0")
    with pytest.raises(ValueError):
        price(value=Decimal("-1"))


@pytest.mark.parametrize(
    "changes",
    [
        {"currency": None},
        {"unit": "ratio"},
        {"adjustment": None},
        {"provenance": observation().provenance},
    ],
)
def test_price_requires_explicit_conventions(changes):
    with pytest.raises(ValueError):
        price(**changes)


def test_statement_retains_negative_values_scope_basis_and_revision():
    result = observation(
        kind=RecordKind.STATEMENT,
        metric="net_income",
        unit="currency",
        value=Decimal("-100"),
        statement_scope="consolidated",
        statement_basis="year_to_date",
        revision="filing-2",
    )
    assert result.value == Decimal("-100")
    assert result.revision == "filing-2"
    for changes in ({"statement_scope": None}, {"statement_basis": "quarter?"}, {"revision": ""}):
        with pytest.raises(ValueError):
            replace(result, **changes)


def test_distribution_missing_is_not_zero_payment():
    result = observation(
        kind=RecordKind.DISTRIBUTION,
        metric="cash_distribution",
        value=None,
        quality=Quality.MISSING,
        reason="coverage unknown",
        distribution_type="dividend",
        tax_basis="unknown",
    )
    assert result.payment_date is None
    assert result.value is None
    with pytest.raises(ValueError):
        replace(result, tax_basis=None)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: Asset("", "id"),
        lambda: Source("p", "", "1", True),
        lambda: Source("p", "ref", "1", "false"),
    ],
)
def test_identity_and_source_validation(factory):
    with pytest.raises(ValueError):
        factory()


def test_monetary_indicator_requires_currency():
    with pytest.raises(ValueError):
        observation(currency=None)


def test_ratio_can_have_no_currency():
    assert observation(metric="ratio", unit="ratio", currency=None).currency is None


def test_instant_statement_requires_single_date():
    with pytest.raises(ValueError):
        observation(
            kind=RecordKind.STATEMENT,
            statement_scope="individual",
            statement_basis="instant",
            revision="1",
        )
