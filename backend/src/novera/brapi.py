"""Single-instrument brapi v2 quote adapter; transport policy belongs to novera.http."""

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal

from novera.contracts import Asset, Observation, Period, Provenance, Quality, RecordKind, Source
from novera.http import AccessContext, CachePolicy, JsonEnvelope, SecureHttpClient

SCHEMA_VERSION = "brapi-stock-quote-v2-1"
ENDPOINT = "/api/v2/stocks/quote"


@dataclass(frozen=True, slots=True)
class BrapiInstrument:
    """Caller-verified current ticker -> stable asset and expected currency mapping.

    Only share/unit quotations are supported; no indices or ticker history resolution.
    """

    asset: Asset
    symbol: str
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.asset, Asset):
            raise ValueError("validated asset required")
        if not isinstance(self.symbol, str) or not re.fullmatch(
            r"[A-Z0-9]{4}[0-9]{1,2}", self.symbol
        ):
            raise ValueError("one canonical share ticker required")
        if not isinstance(self.currency, str) or not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("verified three-letter currency required")


@dataclass(frozen=True, slots=True)
class BrapiQuote:
    price: Observation
    market_at: datetime
    requested_at: datetime
    symbol: str


@dataclass(frozen=True, slots=True)
class _Snapshot:
    market_at: datetime
    requested_at: datetime
    currency: str
    value: Decimal | None
    quality: Quality
    reason: str | None


def _timestamp(value: object) -> datetime:
    # Require explicit ISO date/time and offset; never guess seconds vs milliseconds.
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?"
        r"(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
        value,
    ):
        raise ValueError("explicit quote timestamp required")
    if value.endswith("-00:00"):
        raise ValueError("unknown local offset unsupported")
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _snapshot(payload: object, instrument: BrapiInstrument, now: datetime) -> _Snapshot:
    if not isinstance(payload, dict) or payload.get("error") or payload.get("errors"):
        raise ValueError("invalid quote envelope")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise ValueError("exactly one quote required")
    result = results[0]
    if (
        not isinstance(result, dict)
        or result.get("requestedSymbol") != instrument.symbol
        or result.get("symbol") != instrument.symbol
        or result.get("changed") is not False
    ):
        raise ValueError("unresolved quote identity")
    data = result.get("data")
    if not isinstance(data, dict) or data.get("currency") != instrument.currency:
        raise ValueError("quote currency missing or inconsistent")
    market_at = _timestamp(data.get("regularMarketTime"))
    requested_at = _timestamp(payload.get("requestedAt"))
    if now.utcoffset() is None or market_at > now or requested_at > now:
        raise ValueError("quote timestamps exceed local collection clock")
    value = data.get("regularMarketPrice")
    quality, reason = Quality.PRESENT, None
    if value is None:
        quality, reason = Quality.MISSING, "provider_price_absent"
    elif type(value) not in (int, Decimal) or not Decimal(value).is_finite() or value < 0:
        value, quality, reason = None, Quality.INVALID, "provider_price_invalid"
    else:
        value = Decimal(value)
    return _Snapshot(market_at, requested_at, data["currency"], value, quality, reason)


class BrapiAdapter:
    """Borrow a shared brapi client. Caller owns its lifetime and account quota policy."""

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
            raise ValueError("shared client for brapi HTTPS origin required")
        if type(synthetic) is not bool or not callable(now):
            raise ValueError("explicit synthetic flag and clock required")
        self._client, self._synthetic, self._now = client, synthetic, now

    @property
    def synthetic(self) -> bool:
        """Public read-only provenance label; not a network-isolation guarantee."""
        return self._synthetic

    def quote(
        self,
        instrument: BrapiInstrument,
        *,
        context: AccessContext,
        token: str | None = None,
        cache_policy: CachePolicy = CachePolicy(),
    ) -> JsonEnvelope[BrapiQuote]:
        if not isinstance(instrument, BrapiInstrument):
            raise ValueError("validated instrument mapping required")
        if token is not None and (
            not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token)
        ):
            raise ValueError("invalid bearer credential format")

        def validate(payload: object) -> _Snapshot:
            return _snapshot(payload, instrument, self._now())

        envelope = self._client.get_json(
            ENDPOINT,
            params={"symbols": instrument.symbol},
            headers={"Authorization": f"Bearer {token}"} if token is not None else None,
            context=context,
            schema_version=f"{SCHEMA_VERSION}:{instrument.currency}:{self._synthetic}",
            validator=validate,
            cache_policy=cache_policy,
        )
        snapshot = envelope.data
        # Snapshot validation precedes HTTP cache storage; cache hits retain original dates.
        day = snapshot.market_at.date()
        provenance = Provenance(
            source=Source(
                provider="brapi",
                reference=f"https://brapi.dev{ENDPOINT}?symbols={instrument.symbol}",
                rule_version=SCHEMA_VERSION,
                synthetic=self._synthetic,
            ),
            period=Period(day, day),
            collected_at=envelope.fetched_at,
            published_at=None,
            publication_unknown_reason="provider_does_not_supply_publication_time",
        )
        price = Observation(
            asset=instrument.asset,
            kind=RecordKind.PRICE,
            metric="regular_market_price",
            value=snapshot.value,
            quality=snapshot.quality,
            unit="currency/share",
            currency=snapshot.currency,
            provenance=provenance,
            reason=snapshot.reason,
            adjustment="provider_unspecified",
        )
        return replace(
            envelope,
            data=BrapiQuote(price, snapshot.market_at, snapshot.requested_at, instrument.symbol),
        )
