"""Research events only: a provider payment date is not proof of cash received."""

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from novera.brapi import BrapiInstrument, _timestamp
from novera.contracts import Quality
from novera.http import AccessContext, CachePolicy, JsonEnvelope, SecureHttpClient

ENDPOINT = "/api/v2/stocks/dividends"
SCHEMA_VERSION = "brapi-cash-events-v2-1"
MAX_EVENTS = 5000


@dataclass(frozen=True, slots=True)
class DividendWindow:
    start: date
    end: date

    def __post_init__(self):
        if type(self.start) is not date or type(self.end) is not date:
            raise ValueError("explicit calendar dates required")
        if not 0 <= (self.end - self.start).days <= 366 * 5:
            raise ValueError("ordered window of at most five years required")


@dataclass(frozen=True, slots=True)
class CashEvent:
    rate: Decimal | None
    quality: Quality
    reason: str | None
    payment_date: date | None
    last_date_prior: date | None
    ex_date: date | None
    approved_on: date | None
    label: str | None
    # Dates preserve the provider calendar component, not a UTC conversion.
    payment_status: Literal["unverified"] = "unverified"
    adjustment: Literal["provider_unspecified"] = "provider_unspecified"


@dataclass(frozen=True, slots=True)
class DividendResearch:
    instrument: BrapiInstrument
    window: DividendWindow
    events: tuple[CashEvent, ...]
    stock_events: int
    subscription_events: int
    requested_at: datetime
    collected_at: datetime
    synthetic: bool
    provider: Literal["brapi"] = "brapi"
    rule_version: Literal["brapi-cash-events-v2-1"] = SCHEMA_VERSION
    historical_coverage: Literal["unknown"] = "unknown"
    publication_time: None = None
    publication_unknown_reason: str = "provider_does_not_certify_availability"
    currency: None = None  # Endpoint does not declare currency; mapping is not evidence.
    bazin_eligible: Literal[False] = False


@dataclass(frozen=True, slots=True)
class _Snapshot:
    events: tuple[CashEvent, ...]
    stock_events: int
    subscription_events: int
    requested_at: datetime


def _day(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value)
    _timestamp(value)  # Validate offset/date before preserving the provider calendar date.
    return date.fromisoformat(value[:10])


def _parse(
    payload: object, instrument: BrapiInstrument, window: DividendWindow, now: datetime
) -> _Snapshot:
    if not isinstance(payload, dict) or payload.get("error") or payload.get("errors"):
        raise ValueError("invalid dividends envelope")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise ValueError("exactly one dividends result required")
    result = results[0]
    if (
        not isinstance(result, dict)
        or result.get("requestedSymbol") != instrument.symbol
        or result.get("symbol") != instrument.symbol
        or result.get("changed") is not False
    ):
        raise ValueError("unresolved dividends identity")
    requested_at = _timestamp(payload.get("requestedAt"))
    if now.utcoffset() is None or requested_at > now:
        raise ValueError("invalid collection clock")
    data = result.get("data")
    if not isinstance(data, dict):
        raise ValueError("dividends data required")
    arrays = [data.get(key) for key in ("cashDividends", "stockDividends", "subscriptions")]
    if any(not isinstance(items, list) for items in arrays):
        raise ValueError("explicit event arrays required; missing is not empty")
    if sum(map(len, arrays)) > MAX_EVENTS:
        raise ValueError("event limit exceeded")
    if any(not isinstance(item, dict) for items in arrays for item in items):
        raise ValueError("event object required")
    events, seen = [], set()
    for item in arrays[0]:
        payment = _day(item.get("paymentDate"))
        if payment is not None and not window.start <= payment <= window.end:
            raise ValueError("payment outside requested window")
        value = item.get("rate")
        quality, reason = Quality.PRESENT, None
        if value is None:
            quality, reason = Quality.MISSING, "provider_rate_absent"
        elif type(value) not in (int, Decimal) or not Decimal(value).is_finite() or value < 0:
            value, quality, reason = None, Quality.INVALID, "provider_rate_invalid"
        else:
            value = Decimal(value)
        label = item.get("label")
        if label is not None and (not isinstance(label, str) or len(label) > 120):
            raise ValueError("invalid event label")
        event = CashEvent(
            value,
            quality,
            reason,
            payment,
            _day(item.get("lastDatePrior")),
            _day(item.get("exDate")),
            _day(item.get("approvedOn")),
            label,
        )
        # No stable provider event ID: reject ambiguity instead of summing or deduplicating.
        if event in seen:
            raise ValueError("ambiguous duplicate cash event")
        seen.add(event)
        events.append(event)
    return _Snapshot(tuple(events), len(arrays[1]), len(arrays[2]), requested_at)


class BrapiDividendsAdapter:
    def __init__(
        self,
        client: SecureHttpClient,
        *,
        synthetic: bool,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        if (
            not isinstance(client, SecureHttpClient)
            or client.provider != "brapi"
            or client.origin.rstrip("/") != "https://brapi.dev"
        ):
            raise ValueError("shared brapi HTTPS client required")
        if type(synthetic) is not bool or not callable(now):
            raise ValueError("explicit provenance and clock required")
        self._client, self._synthetic, self._now = client, synthetic, now

    def dividends(
        self,
        instrument: BrapiInstrument,
        window: DividendWindow,
        *,
        context: AccessContext,
        token: str | None = None,
        cache_policy: CachePolicy = CachePolicy(),
    ) -> JsonEnvelope[DividendResearch]:
        if not isinstance(instrument, BrapiInstrument) or not isinstance(window, DividendWindow):
            raise ValueError("validated instrument and window required")
        if token is not None and (
            not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token)
        ):
            raise ValueError("invalid bearer credential format")
        envelope = self._client.get_json(
            ENDPOINT,
            params={
                "symbols": instrument.symbol,
                "startDate": window.start.isoformat(),
                "endDate": window.end.isoformat(),
                "sortBy": "paymentDate",
                "sortOrder": "asc",
            },
            headers={"Authorization": f"Bearer {token}"} if token is not None else None,
            context=context,
            schema_version=f"{SCHEMA_VERSION}:{self._synthetic}",
            validator=lambda payload: _parse(payload, instrument, window, self._now()),
            cache_policy=cache_policy,
        )
        snapshot = envelope.data
        return replace(
            envelope,
            data=DividendResearch(
                instrument,
                window,
                snapshot.events,
                snapshot.stock_events,
                snapshot.subscription_events,
                snapshot.requested_at,
                envelope.fetched_at,
                self._synthetic,
            ),
        )
