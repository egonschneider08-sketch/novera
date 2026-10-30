"""Bounded SGS 432 adapter. Transport policies remain in SecureHttpClient."""

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlencode

from novera.contracts import Asset, Observation, Period, Provenance, Quality, RecordKind, Source
from novera.http import AccessContext, CachePolicy, JsonEnvelope, SecureHttpClient

ENDPOINT = "/dados/serie/bcdata.sgs.432/dados"
SCHEMA_VERSION = "bcb-sgs-432-v1"
MAX_DAYS = 366  # Local scope limit, deliberately below the provider's ten-year limit.


@dataclass(frozen=True, slots=True)
class SgsWindow:
    requested_period: Period
    observations: tuple[Observation, ...]
    # Calendar dates absent from the response, not a declaration of provider/business-day coverage.
    unreturned_dates: tuple[date, ...]


@dataclass(frozen=True, slots=True)
class _Row:
    day: date
    value: Decimal | None
    quality: Quality
    reason: str | None


def _value(raw: object) -> tuple[Decimal | None, Quality, str | None]:
    if raw is None or raw == "":
        return None, Quality.MISSING, "sgs_value_absent"
    if not isinstance(raw, str) or len(raw) > 64 or not re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", raw):
        return None, Quality.INVALID, "sgs_value_invalid"
    percent = Decimal(raw)
    if percent < 0:
        return None, Quality.INVALID, "sgs_negative_target_unsupported"
    # Exact division by 100 via exponent shift, independent of the caller's Decimal context.
    parts = percent.as_tuple()
    fraction = Decimal((parts.sign, parts.digits, parts.exponent - 2))
    return fraction, Quality.PRESENT, None


def _rows(payload: object, period: Period) -> tuple[_Row, ...]:
    if not isinstance(payload, list) or len(payload) > (period.end - period.start).days + 1:
        raise ValueError("bounded SGS daily array required")
    rows = []
    seen = set()
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("SGS object required")
        raw_day = item.get("data")
        if not isinstance(raw_day, str) or not re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}", raw_day):
            raise ValueError("SGS reference date required")
        day = date(int(raw_day[6:]), int(raw_day[3:5]), int(raw_day[:2]))
        if not period.start <= day <= period.end or day in seen:
            raise ValueError("SGS date outside request or duplicated")
        seen.add(day)
        value, quality, reason = _value(item.get("valor"))
        rows.append(_Row(day, value, quality, reason))
    return tuple(sorted(rows, key=lambda row: row.day))


class BcbAdapter:
    """Borrow one shared BCB client; no credentials, HTTP policy or lifecycle duplication."""

    def __init__(
        self,
        client: SecureHttpClient,
        *,
        synthetic: bool,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        if (
            not isinstance(client, SecureHttpClient)
            or client.provider != "bcb"
            or client.origin.rstrip("/") != "https://api.bcb.gov.br"
        ):
            raise ValueError("shared BCB HTTPS client required")
        if type(synthetic) is not bool or not callable(now):
            raise ValueError("explicit synthetic flag and clock required")
        self._client, self._synthetic, self._now = client, synthetic, now

    def selic_target(
        self,
        period: Period,
        *,
        context: AccessContext,
        cache_policy: CachePolicy = CachePolicy(),
    ) -> JsonEnvelope[SgsWindow]:
        if not isinstance(period, Period) or (period.end - period.start).days >= MAX_DAYS:
            raise ValueError("explicit period of at most 366 inclusive days required")
        now = self._now()
        if not isinstance(now, datetime) or now.utcoffset() is None:
            raise ValueError("timezone-aware collection clock required")
        if period.end > now.astimezone(timezone.utc).date():
            raise ValueError("future request dates unsupported")
        params = {
            "formato": "json",
            "dataInicial": period.start.strftime("%d/%m/%Y"),
            "dataFinal": period.end.strftime("%d/%m/%Y"),
        }
        envelope = self._client.get_json(
            ENDPOINT,
            params=params,
            context=context,
            schema_version=f"{SCHEMA_VERSION}:{self._synthetic}",
            validator=lambda payload: _rows(payload, period),
            cache_policy=cache_policy,
        )
        source = Source(
            provider="bcb",
            reference=f"https://api.bcb.gov.br{ENDPOINT}?{urlencode(params)}",
            rule_version=SCHEMA_VERSION,
            synthetic=self._synthetic,
        )
        observations = tuple(
            Observation(
                asset=Asset("bcb.sgs", "432"),
                kind=RecordKind.INDICATOR,
                metric="selic_target",
                value=row.value,
                quality=row.quality,
                unit="fraction/year",
                currency=None,
                reason=row.reason,
                provenance=Provenance(
                    source=source,
                    period=Period(row.day, row.day),
                    collected_at=envelope.fetched_at,
                    published_at=None,
                    publication_unknown_reason="sgs_publication_time_not_provided",
                ),
            )
            for row in envelope.data
        )
        returned = {row.day for row in envelope.data}
        missing = tuple(
            period.start + timedelta(days=offset)
            for offset in range((period.end - period.start).days + 1)
            if period.start + timedelta(days=offset) not in returned
        )
        return replace(envelope, data=SgsWindow(period, observations, missing))
