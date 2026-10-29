"""Synthetic v2 payloads only; no provider credentials or real transport."""

import json
import socket
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from novera.brapi import BrapiAdapter, BrapiInstrument
from novera.contracts import Asset, Quality, RecordKind
from novera.http import (
    AccessContext,
    CachePolicy,
    FailureKind,
    FetchError,
    Freshness,
    RetryPolicy,
    SecureHttpClient,
)

INSTRUMENT = BrapiInstrument(Asset("synthetic-security-id", "issuer-a-share-b"), "TEST3", "BRL")
CONTEXT = AccessContext("synthetic-user", "synthetic-plan", "revision-1")


class Clock:
    def __init__(self):
        self.tick = 0.0
        self.sleeps = []

    def now(self):
        return datetime(2026, 10, 29, 18, tzinfo=timezone.utc) + timedelta(seconds=self.tick)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.tick += seconds


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("real network forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)


@pytest.fixture
def setup_client():
    clients = []

    def build(handler, **policy):
        clock = Clock()
        client = SecureHttpClient(
            "brapi",
            "https://brapi.dev",
            transport=httpx.MockTransport(handler),
            policy=RetryPolicy(**({"min_interval": 3, "max_retries": 2} | policy)),
            now=clock.now,
            monotonic=lambda: clock.tick,
            sleep=clock.sleep,
            jitter=lambda: 0.5,
        )
        clients.append(client)
        return BrapiAdapter(client, synthetic=True, now=clock.now), client, clock

    yield build
    for client in clients:
        client.close()


def payload():
    return {
        "results": [
            {
                "requestedSymbol": "TEST3",
                "symbol": "TEST3",
                "changed": False,
                "data": {
                    "currency": "BRL",
                    "regularMarketTime": "2026-10-29T14:30:00-03:00",
                    "regularMarketPrice": 12,
                },
            }
        ],
        "requestedAt": "2026-10-29T17:31:00Z",
        "took": 10,
    }


def quote(adapter, **kwargs):
    return adapter.quote(INSTRUMENT, **({"context": CONTEXT} | kwargs))


def test_quote_contract_precision_source_and_http_reuse(setup_client):
    calls = []

    def handler(request):
        calls.append(request)
        assert str(request.url) == "https://brapi.dev/api/v2/stocks/quote?symbols=TEST3"
        assert request.method == "GET"
        assert "authorization" not in request.headers
        content = json.dumps(payload()).replace(
            '"regularMarketPrice": 12', '"regularMarketPrice": 12.1234567890123456789'
        )
        return httpx.Response(200, content=content)

    adapter, client, clock = setup_client(handler)
    result = quote(adapter)
    price = result.data.price
    assert price.asset == INSTRUMENT.asset
    assert price.kind is RecordKind.PRICE
    assert price.value == Decimal("12.1234567890123456789")
    assert price.quality is Quality.PRESENT
    assert (price.unit, price.currency, price.adjustment) == (
        "currency/share",
        "BRL",
        "provider_unspecified",
    )
    assert price.provenance.collected_at == result.fetched_at == clock.now()
    assert (
        price.provenance.period.start == price.provenance.period.end == result.data.market_at.date()
    )
    assert result.data.market_at.hour == 17
    assert result.data.requested_at.minute == 31
    assert price.provenance.published_at is None
    assert price.provenance.publication_unknown_reason
    assert price.provenance.source.synthetic is True
    assert price.provenance.source.provider == "brapi"
    assert price.provenance.source.reference.endswith("?symbols=TEST3")
    assert result.freshness is Freshness.NETWORK
    clock.tick += 5
    cached = quote(adapter)
    assert cached.freshness is Freshness.FRESH
    assert cached.data == result.data
    assert cached.fetched_at == result.fetched_at
    assert cached.age_seconds == 5
    assert len(calls) == 1
    assert client.provider == "brapi" and client.origin == "https://brapi.dev"


@pytest.mark.parametrize(
    "value,quality",
    [
        (0, Quality.PRESENT),
        (None, Quality.MISSING),
        (-1, Quality.INVALID),
        (True, Quality.INVALID),
        ("12.34", Quality.INVALID),
        ({}, Quality.INVALID),
        ([], Quality.INVALID),
    ],
)
def test_price_quality_never_uses_truthiness(setup_client, value, quality):
    body = payload()
    body["results"][0]["data"]["regularMarketPrice"] = value
    adapter, _, _ = setup_client(lambda r: httpx.Response(200, json=body))
    result = quote(adapter).data.price
    assert result.quality is quality
    assert result.value == (Decimal(0) if quality is Quality.PRESENT else None)
    assert bool(result.reason) is (quality is not Quality.PRESENT)


def test_absent_price_is_missing_and_unused_fields_not_required(setup_client):
    body = payload()
    del body["results"][0]["data"]["regularMarketPrice"]
    adapter, _, _ = setup_client(lambda r: httpx.Response(200, json=body))
    assert quote(adapter).data.price.quality is Quality.MISSING


@pytest.mark.parametrize(
    "field,value",
    [
        ("currency", None),
        ("currency", "USD"),
        ("currency", "brl"),
        ("regularMarketTime", None),
        ("regularMarketTime", "2026-10-29T17:30:00+00:99"),
        ("regularMarketTime", "2026-10-29T17:30:00-00:00"),
        ("regularMarketTime", 1793295000),
        ("regularMarketTime", "2026-10-29"),
        ("regularMarketTime", "2026-10-29T17:30:00"),
        ("regularMarketTime", "2026-02-30T00:00:00Z"),
        ("regularMarketTime", "2026-10-30T00:00:00Z"),
    ],
)
def test_invalid_required_metadata_is_not_cached_or_invented(setup_client, field, value):
    body = payload()
    body["results"][0]["data"][field] = value
    adapter, client, _ = setup_client(lambda r: httpx.Response(200, json=body))
    with pytest.raises(FetchError) as error:
        quote(adapter)
    assert error.value.kind is FailureKind.INVALID_RESPONSE
    assert error.value.attempts == 1
    assert not client._cache._entries


@pytest.mark.parametrize("field", ["currency", "regularMarketTime"])
def test_missing_required_metadata(setup_client, field):
    body = payload()
    del body["results"][0]["data"][field]
    adapter, _, _ = setup_client(lambda r: httpx.Response(200, json=body))
    with pytest.raises(FetchError):
        quote(adapter)


@pytest.mark.parametrize(
    "field,value",
    [
        ("symbol", "ELSE4"),
        ("requestedSymbol", "ELSE4"),
        ("changed", True),
        ("changed", 0),
        ("symbol", None),
        ("data", None),
    ],
)
def test_identity_and_shape_rejected(setup_client, field, value):
    body = payload()
    body["results"][0][field] = value
    adapter, _, _ = setup_client(lambda r: httpx.Response(200, json=body))
    with pytest.raises(FetchError) as error:
        quote(adapter)
    assert error.value.kind is FailureKind.INVALID_RESPONSE


@pytest.mark.parametrize(
    "case",
    ["empty", "duplicate", "missing", "error", "partial", "requested_future", "requested_missing"],
)
def test_bad_envelopes(setup_client, case):
    body = payload()
    if case == "empty":
        body["results"] = []
    elif case == "duplicate":
        body["results"] *= 2
    elif case == "missing":
        del body["results"]
    elif case == "error":
        body["error"] = True
    elif case == "partial":
        body["errors"] = [{"symbol": "TEST3", "code": "UNAVAILABLE"}]
    elif case == "requested_future":
        body["requestedAt"] = "2026-10-30T00:00:00Z"
    else:
        del body["requestedAt"]
    adapter, _, _ = setup_client(lambda r: httpx.Response(200, json=body))
    with pytest.raises(FetchError):
        quote(adapter)


@pytest.mark.parametrize("status", [401, 403, 404])
def test_terminal_http_failures_never_fallback_or_retry(setup_client, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payload()) if len(calls) == 1 else httpx.Response(status)

    adapter, client, clock = setup_client(handler)
    policy = CachePolicy(ttl=1, allow_stale=True, max_stale=60)
    quote(adapter, cache_policy=policy)
    clock.tick += 2
    with pytest.raises(FetchError) as error:
        quote(adapter, cache_policy=policy)
    assert (error.value.status, error.value.attempts) == (status, 1)
    assert len(calls) == 2
    assert not client._cache._entries


def test_retry_after_and_rate_limit_are_delegated_once(setup_client):
    calls = []

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(429, headers={"Retry-After": "7"})
            if len(calls) == 1
            else httpx.Response(200, json=payload())
        )

    adapter, _, clock = setup_client(handler)
    result = quote(adapter)
    assert result.attempts == len(calls) == 2
    assert clock.sleeps == [7]
    quote(adapter, context=replace(CONTEXT, tenant="other"))
    assert clock.sleeps == [7, 3]


@pytest.mark.parametrize("failure", ["timeout", "429"])
def test_transient_failures_bounded_and_stale_explicit(setup_client, failure):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=payload())
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        return httpx.Response(429, headers={"Retry-After": "3"})

    adapter, _, clock = setup_client(handler)
    policy = CachePolicy(ttl=1, allow_stale=True, max_stale=60)
    first = quote(adapter, cache_policy=policy)
    clock.tick += 2
    stale = quote(adapter, cache_policy=policy)
    assert stale.freshness is Freshness.STALE
    assert stale.stale_reason is (
        FailureKind.TIMEOUT if failure == "timeout" else FailureKind.RATE_LIMITED
    )
    assert stale.attempts == 3
    assert len(calls) == 4
    assert stale.data == first.data
    assert stale.fetched_at == stale.data.price.provenance.collected_at == first.fetched_at
    assert stale.age_seconds > 2
    with pytest.raises(FetchError):
        quote(adapter, cache_policy=replace(policy, allow_stale=False))
    with pytest.raises(FetchError):
        quote(adapter, context=replace(CONTEXT, entitlement="other"), cache_policy=policy)


def test_invalid_schema_cannot_fallback_to_previous_valid_quote(setup_client):
    body = payload()
    adapter, client, clock = setup_client(lambda r: httpx.Response(200, json=deepcopy(body)))
    policy = CachePolicy(ttl=1, allow_stale=True, max_stale=60)
    quote(adapter, cache_policy=policy)
    clock.tick += 2
    body["results"][0]["symbol"] = "ELSE4"
    with pytest.raises(FetchError) as error:
        quote(adapter, cache_policy=policy)
    assert error.value.kind is FailureKind.INVALID_RESPONSE
    assert not client._cache._entries


@pytest.mark.parametrize("field", ["tenant", "entitlement", "credential_revision"])
def test_access_partitions_are_not_shared(setup_client, field):
    calls = []

    def handler(request):
        calls.append(request)
        body = payload()
        body["results"][0]["data"]["regularMarketPrice"] = len(calls)
        return httpx.Response(200, json=body)

    adapter, _, _ = setup_client(handler)
    first = quote(adapter)
    other = quote(adapter, context=replace(CONTEXT, **{field: "different"}))
    assert first.data.price.value == 1 and other.data.price.value == 2
    assert quote(adapter).data == first.data
    assert len(calls) == 2


def test_mapping_currency_checked_even_after_cache_hit(setup_client):
    adapter, _, _ = setup_client(lambda r: httpx.Response(200, json=payload()))
    quote(adapter)
    with pytest.raises(FetchError):
        adapter.quote(replace(INSTRUMENT, currency="USD"), context=CONTEXT)
    other = adapter.quote(
        replace(INSTRUMENT, asset=Asset("synthetic", "other-id")), context=CONTEXT
    )
    assert other.data.price.asset.identifier == "other-id"


def test_utc_date_old_quote_and_unknown_publication_remain_explicit(setup_client):
    body = payload()
    body["results"][0]["data"]["regularMarketTime"] = "2026-10-20T23:30:00-03:00"
    adapter, _, _ = setup_client(lambda r: httpx.Response(200, json=body))
    result = quote(adapter)
    assert result.freshness is Freshness.NETWORK
    assert result.data.price.provenance.period.start.isoformat() == "2026-10-21"
    assert result.data.market_at.day == 21
    assert result.data.price.provenance.published_at is None


@pytest.mark.parametrize("symbol", ["TEST3,ELSE4", "TEST3?token=x", "test3", "^BVSP", "", "../x"])
def test_instrument_input_validation(symbol):
    with pytest.raises(ValueError):
        replace(INSTRUMENT, symbol=symbol)


def test_wrong_origin_rejected_before_credentials_can_be_forwarded():
    with SecureHttpClient(
        "brapi", "https://other.invalid", transport=httpx.MockTransport(lambda r: None)
    ) as client:
        with pytest.raises(ValueError):
            BrapiAdapter(client, synthetic=True)


def test_import_has_no_network(tmp_path):
    code = (
        "import socket; "
        "deny=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network forbidden')); "
        "socket.getaddrinfo=deny; socket.create_connection=deny; socket.socket.connect=deny; "
        "import novera.brapi; print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_is_rejected_before_normalization(setup_client, number):
    content = json.dumps(payload()).replace(
        '"regularMarketPrice": 12', f'"regularMarketPrice": {number}'
    )
    adapter, client, _ = setup_client(lambda r: httpx.Response(200, content=content))
    with pytest.raises(FetchError) as error:
        quote(adapter)
    assert error.value.kind is FailureKind.INVALID_RESPONSE
    assert not client._cache._entries


def test_unmodeled_fields_are_not_retained_or_logged(setup_client, caplog):
    body = payload()
    body["results"][0]["data"]["longName"] = "synthetic-private-extra"
    adapter, client, _ = setup_client(lambda r: httpx.Response(200, json=body))
    result = quote(adapter)
    assert "synthetic-private-extra" not in repr(result.data)
    assert "synthetic-private-extra" not in repr(
        [entry.data for entry in client._cache._entries.values()]
    )
    assert "synthetic-private-extra" not in caplog.text


def test_partial_failure_does_not_poison_other_ticker(setup_client):
    def handler(request):
        symbol = request.url.params["symbols"]
        body = payload()
        body["results"][0]["requestedSymbol"] = symbol
        body["results"][0]["symbol"] = symbol
        if symbol == "BADX4":
            del body["results"][0]["data"]["currency"]
        return httpx.Response(200, json=body)

    adapter, _, _ = setup_client(handler)
    good = quote(adapter)
    with pytest.raises(FetchError):
        adapter.quote(replace(INSTRUMENT, symbol="BADX4"), context=CONTEXT)
    cached = quote(adapter)
    assert cached.freshness is Freshness.FRESH
    assert cached.data == good.data


def test_synthetic_and_live_namespaces_do_not_share_cache(setup_client):
    adapter, client, clock = setup_client(lambda r: httpx.Response(200, json=payload()))
    quote(adapter)
    # Still a mock, but verifies the explicit source label cannot reuse synthetic cache entries.
    live_label = BrapiAdapter(client, synthetic=False, now=clock.now)
    result = quote(live_label)
    assert result.freshness is Freshness.NETWORK
    assert result.data.price.provenance.source.synthetic is False
