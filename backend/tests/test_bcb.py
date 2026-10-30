"""Synthetic SGS payloads; no external calls, tokens or wall-clock sleeps."""

import socket
import subprocess
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext

import httpx
import pytest
from novera.bcb import BcbAdapter
from novera.contracts import Asset, Period, Quality, RecordKind
from novera.http import (
    AccessContext,
    CachePolicy,
    FailureKind,
    FetchError,
    Freshness,
    RetryPolicy,
    SecureHttpClient,
)

PERIOD = Period(date(2026, 10, 26), date(2026, 10, 28))
CONTEXT = AccessContext("synthetic-user", "public-sgs", "revision-1")


class Clock:
    tick = 0.0

    def __init__(self):
        self.sleeps = []

    def now(self):
        return datetime(2026, 10, 30, 12, tzinfo=timezone.utc) + timedelta(seconds=self.tick)

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.tick += delay


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("real network forbidden")

    monkeypatch.setattr(socket, "getaddrinfo", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket.socket, "connect", deny)


@pytest.fixture
def build():
    clients = []

    def create(handler, **policy):
        clock = Clock()
        client = SecureHttpClient(
            "bcb",
            "https://api.bcb.gov.br",
            transport=httpx.MockTransport(handler),
            policy=RetryPolicy(**({"max_retries": 2, "min_interval": 1} | policy)),
            now=clock.now,
            monotonic=lambda: clock.tick,
            sleep=clock.sleep,
            jitter=lambda: 0.5,
        )
        clients.append(client)
        return BcbAdapter(client, synthetic=True, now=clock.now), client, clock

    yield create
    for client in clients:
        client.close()


def get(adapter, **kwargs):
    return adapter.selic_target(PERIOD, **({"context": CONTEXT} | kwargs))


def test_contract_dates_units_origin_and_exact_conversion(build):
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.host == "api.bcb.gov.br"
        assert request.url.path == "/dados/serie/bcdata.sgs.432/dados"
        assert dict(request.url.params) == {
            "formato": "json",
            "dataInicial": "26/10/2026",
            "dataFinal": "28/10/2026",
        }
        assert "authorization" not in request.headers
        assert request.extensions["timeout"]["read"] == 10
        return httpx.Response(
            200,
            json=[
                {"data": "28/10/2026", "valor": "12.34567890123456789"},
                {"data": "26/10/2026", "valor": "0"},
            ],
        )

    adapter, _, clock = build(handler)
    with localcontext() as ctx:
        ctx.prec = 2
        result = get(adapter)
        assert ctx.prec == 2
    zero, rate = result.data.observations
    assert zero.value == Decimal(0) and zero.quality is Quality.PRESENT
    assert rate.value == Decimal("0.1234567890123456789")
    assert rate.asset == Asset("bcb.sgs", "432")
    assert rate.kind is RecordKind.INDICATOR
    assert (rate.metric, rate.unit, rate.currency) == ("selic_target", "fraction/year", None)
    assert rate.provenance.period == Period(date(2026, 10, 28), date(2026, 10, 28))
    assert rate.provenance.published_at is None and rate.provenance.publication_unknown_reason
    assert rate.provenance.collected_at == result.fetched_at == clock.now()
    assert rate.provenance.source.provider == "bcb" and rate.provenance.source.synthetic
    assert "bcdata.sgs.432" in rate.provenance.source.reference
    assert result.data.requested_period == PERIOD
    assert result.data.unreturned_dates == (date(2026, 10, 27),)
    clock.tick += 5
    cached = get(adapter)
    assert cached.freshness is Freshness.FRESH
    assert cached.data == result.data and cached.fetched_at == result.fetched_at
    assert cached.age_seconds == 5 and len(calls) == 1


@pytest.mark.parametrize(
    "raw,quality,expected",
    [
        ("12.50", Quality.PRESENT, Decimal("0.1250")),
        ("0.00", Quality.PRESENT, Decimal("0.0000")),
        ("150.0", Quality.PRESENT, Decimal("1.50")),
        (None, Quality.MISSING, None),
        ("", Quality.MISSING, None),
        (" ", Quality.INVALID, None),
        ("12,50", Quality.INVALID, None),
        ("1e2", Quality.INVALID, None),
        ("NaN", Quality.INVALID, None),
        ("Infinity", Quality.INVALID, None),
        ("-1", Quality.INVALID, None),
        ("1_000", Quality.INVALID, None),
        ("١٢", Quality.INVALID, None),
        (0, Quality.INVALID, None),
        (12.5, Quality.INVALID, None),
        (False, Quality.INVALID, None),
        ({}, Quality.INVALID, None),
        ([], Quality.INVALID, None),
        ("1" * 65, Quality.INVALID, None),
    ],
)
def test_value_quality_and_no_float_or_locale_coercion(build, raw, quality, expected):
    adapter, _, _ = build(
        lambda r: httpx.Response(200, json=[{"data": "26/10/2026", "valor": raw}])
    )
    result = get(adapter).data.observations[0]
    assert result.quality is quality and result.value == expected
    assert bool(result.reason) is (quality is not Quality.PRESENT)


def test_absent_value_and_empty_response_do_not_become_zero(build):
    adapter, _, _ = build(lambda r: httpx.Response(200, json=[{"data": "26/10/2026"}]))
    result = get(adapter).data
    assert result.observations[0].quality is Quality.MISSING
    assert len(result.unreturned_dates) == 2
    empty, _, _ = build(lambda r: httpx.Response(200, json=[]))
    result = get(empty).data
    assert result.observations == () and len(result.unreturned_dates) == 3


@pytest.mark.parametrize(
    "body",
    [
        {},
        None,
        {"error": "synthetic"},
        [None],
        [{}],
        [{"data": "2026-10-26", "valor": "1"}],
        [{"data": "26/10/2026T00:00:00Z", "valor": "1"}],
        [{"data": "1/10/2026", "valor": "1"}],
        [{"data": "31/02/2026", "valor": "1"}],
        [{"data": "25/10/2026", "valor": "1"}],
        [{"data": "29/10/2026", "valor": "1"}],
        [{"data": "26/10/2026", "valor": "1"}] * 2,
        [{"data": "26/10/2026", "valor": "1"}] * 4,
        [{"data": "26/10/2026", "valor": "1"}, {"data": "bad", "valor": "2"}],
    ],
)
def test_schema_errors_are_atomic_and_not_cached(build, body):
    adapter, client, _ = build(lambda r: httpx.Response(200, json=body))
    with pytest.raises(FetchError) as error:
        get(adapter)
    assert error.value.kind is FailureKind.INVALID_RESPONSE
    assert error.value.attempts == 1
    assert not client._cache._entries


def test_request_bounds_and_future_dates_checked_before_transport(build):
    def fail(request):
        pytest.fail("transport must not run")

    adapter, _, _ = build(fail)
    for period in (
        None,
        Period(date(2025, 1, 1), date(2026, 1, 2)),
        Period(date(2026, 10, 30), date(2026, 10, 31)),
    ):
        with pytest.raises(ValueError):
            adapter.selic_target(period, context=CONTEXT)


def test_leap_date_and_inclusive_366_day_bound(build):
    adapter, _, _ = build(
        lambda r: httpx.Response(200, json=[{"data": "29/02/2024", "valor": "10"}])
    )
    period = Period(date(2024, 1, 1), date(2024, 12, 31))
    result = adapter.selic_target(period, context=CONTEXT).data
    assert result.observations[0].provenance.period.start == date(2024, 2, 29)
    assert len(result.unreturned_dates) == 365


@pytest.mark.parametrize("failure", ["429", "timeout"])
def test_retries_stale_and_original_provenance(build, failure):
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=[{"data": "26/10/2026", "valor": "10"}])
        if failure == "429":
            return httpx.Response(429, headers={"Retry-After": "3"})
        raise httpx.ReadTimeout("synthetic failure")

    adapter, _, clock = build(handler)
    policy = CachePolicy(ttl=1, allow_stale=True, max_stale=60)
    first = get(adapter, cache_policy=policy)
    clock.tick += 2
    stale = get(adapter, cache_policy=policy)
    assert stale.freshness is Freshness.STALE and stale.attempts == 3
    assert len(calls) == 4
    assert stale.data == first.data and stale.fetched_at == first.fetched_at
    assert stale.data.observations[0].provenance.collected_at == first.fetched_at
    assert stale.stale_reason is (
        FailureKind.RATE_LIMITED if failure == "429" else FailureKind.TIMEOUT
    )
    if failure == "429":
        assert clock.sleeps == [3, 3]
    with pytest.raises(FetchError):
        get(adapter, cache_policy=replace(policy, allow_stale=False))
    with pytest.raises(FetchError):
        get(adapter, context=replace(CONTEXT, tenant="other"), cache_policy=policy)


def test_retry_after_success_and_rate_limiter_delegated(build):
    calls = []

    def handler(request):
        calls.append(request)
        return (
            httpx.Response(429, headers={"Retry-After": "7"})
            if len(calls) == 1
            else httpx.Response(200, json=[])
        )

    adapter, _, clock = build(handler)
    assert get(adapter).attempts == 2
    get(adapter, cache_policy=CachePolicy(enabled=False))
    assert clock.sleeps == [7, 1]
    assert len(calls) == 3


@pytest.mark.parametrize("status", [400, 401, 403, 404, 204])
def test_non_200_never_invent_missing_data_or_stale(build, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[]) if len(calls) == 1 else httpx.Response(status)

    adapter, client, clock = build(handler)
    policy = CachePolicy(ttl=1, allow_stale=True, max_stale=60)
    get(adapter, cache_policy=policy)
    clock.tick += 2
    with pytest.raises(FetchError) as error:
        get(adapter, cache_policy=policy)
    assert error.value.status == status and error.value.attempts == 1
    assert len(calls) == 2 and not client._cache._entries


def test_bad_schema_cannot_serve_stale_and_error_does_not_echo_payload(build):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json=[] if len(calls) == 1 else [{"data": "private-synthetic-text"}]
        )

    adapter, client, clock = build(handler)
    policy = CachePolicy(ttl=1, allow_stale=True, max_stale=60)
    get(adapter, cache_policy=policy)
    clock.tick += 2
    with pytest.raises(FetchError) as error:
        get(adapter, cache_policy=policy)
    assert error.value.kind is FailureKind.INVALID_RESPONSE
    assert "private-synthetic-text" not in str(error.value)
    assert not client._cache._entries


@pytest.mark.parametrize("field", ["tenant", "entitlement", "credential_revision"])
def test_context_isolation(build, field):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[{"data": "26/10/2026", "valor": str(len(calls))}])

    adapter, _, _ = build(handler)
    first = get(adapter)
    second = get(adapter, context=replace(CONTEXT, **{field: "other"}))
    assert first.data.observations[0].value == Decimal("0.01")
    assert second.data.observations[0].value == Decimal("0.02")
    assert get(adapter).data == first.data


def test_synthetic_namespace_and_range_are_separate(build):
    adapter, client, clock = build(lambda r: httpx.Response(200, json=[]))
    get(adapter)
    assert get(BcbAdapter(client, synthetic=False, now=clock.now)).freshness is Freshness.NETWORK
    assert (
        adapter.selic_target(Period(PERIOD.start, PERIOD.start), context=CONTEXT).freshness
        is Freshness.NETWORK
    )


def test_client_origin_and_flags_validated():
    with SecureHttpClient(
        "bcb", "https://wrong.invalid", transport=httpx.MockTransport(lambda r: None)
    ) as client:
        with pytest.raises(ValueError):
            BcbAdapter(client, synthetic=True)


def test_import_without_network(tmp_path):
    code = (
        "import socket; "
        "deny=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network forbidden')); "
        "socket.getaddrinfo=deny; socket.create_connection=deny; socket.socket.connect=deny; "
        "import novera.bcb; print('ok')"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code], cwd=tmp_path, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
