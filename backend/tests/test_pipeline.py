"""End-to-end pipeline checks use only mock HTTP transports and synthetic records."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from novera.bcb import BcbAdapter
from novera.brapi import BrapiAdapter, BrapiInstrument
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
from novera.pipeline import (
    FinancialPipeline,
    PipelineError,
    QuoteRequest,
    SgsRequest,
)
from novera.storage import ObservationStore, StorageScope

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
CONTEXT = AccessContext("synthetic-tenant", "test-plan", "revision-1")
SCOPE = StorageScope("synthetic-tenant", "test-plan", "revision-1")
INSTRUMENT = BrapiInstrument(Asset("fixture", "stable-share-a"), "TEST3", "BRL")
DAY = date(2026, 10, 28)
PERIOD = Period(DAY, DAY)


def brapi_payload(price=0):
    return {
        "results": [{
            "requestedSymbol": "TEST3",
            "symbol": "TEST3",
            "changed": False,
            "data": {
                "currency": "BRL",
                "regularMarketTime": "2026-10-28T13:00:00-03:00",
                "regularMarketPrice": price,
            },
        }],
        "requestedAt": "2026-10-28T16:01:00Z",
    }


def bcb_payload():
    return [{"data": "28/10/2026", "valor": "15.00"}]


@pytest.fixture
def services():
    clients = []

    class LabClock:
        now = NOW

        def advance(self):
            self.now += timedelta(minutes=2)

    clock = LabClock()

    def build(store, *, brapi_handler=None, bcb_handler=None, brapi_synthetic=True,
              bcb_synthetic=True, enabled=True, context=CONTEXT):
        adapters = {}
        policy = RetryPolicy(min_interval=0, max_retries=0)
        if brapi_handler is not None:
            client = SecureHttpClient(
                "brapi", "https://brapi.dev",
                transport=httpx.MockTransport(brapi_handler),
                policy=policy, now=lambda: clock.now,
            )
            clients.append(client)
            adapters["brapi"] = BrapiAdapter(
                client, synthetic=brapi_synthetic, now=lambda: clock.now
            )
        if bcb_handler is not None:
            client = SecureHttpClient(
                "bcb", "https://api.bcb.gov.br",
                transport=httpx.MockTransport(bcb_handler),
                policy=policy, now=lambda: clock.now,
            )
            clients.append(client)
            adapters["bcb"] = BcbAdapter(client, synthetic=bcb_synthetic, now=lambda: clock.now)
        return FinancialPipeline(
            store, context=context, enabled=enabled, **adapters
        ), clock, adapters

    yield build
    for client in clients:
        client.close()


@pytest.fixture
def store():
    with ObservationStore.memory(scope=SCOPE, synthetic=True) as repository:
        yield repository


def query(store, observation):
    return store.query(
        asset=observation.asset,
        kind=observation.kind,
        metric=observation.metric,
        period=observation.provenance.period,
    )


def test_mixed_provider_batch_preserves_financial_contracts(store, services):
    calls = []
    pipeline, _, _ = services(
        store,
        brapi_handler=lambda r: (calls.append(r.url.host), httpx.Response(200, json=brapi_payload()))[1],
        bcb_handler=lambda r: (calls.append(r.url.host), httpx.Response(200, json=bcb_payload()))[1],
    )
    result = pipeline.run((QuoteRequest(INSTRUMENT), SgsRequest(PERIOD)))
    assert calls == ["brapi.dev", "api.bcb.gov.br"]
    assert len(result.records) == 2
    price, selic = (row.observation for row in result.records)
    assert price.kind is RecordKind.PRICE
    assert price.metric == "regular_market_price"
    assert price.value == Decimal(0) and price.quality is Quality.PRESENT
    assert price.adjustment == "provider_unspecified"
    assert selic.kind is RecordKind.INDICATOR
    assert selic.metric == "selic_target"
    assert selic.value == Decimal("0.1500") and selic.unit == "fraction/year"
    assert selic.currency is None
    assert all(x.observation.provenance.published_at is None for x in result.records)
    assert all(row.version == 1 for row in result.records)
    assert [x.provider for x in result.tasks] == ["brapi", "bcb"]
    assert all(x.freshness is Freshness.NETWORK for x in result.tasks)
    assert result.tasks[1].unreturned_dates == ()
    assert query(store, price)[0] == result.records[0]
    assert query(store, selic)[0] == result.records[1]
    assert result.records[0].record_key.startswith("brapi:quote:TEST3:2026-10-28T16:00:00+00:00")
    assert result.records[1].record_key == "bcb:sgs:432:2026-10-28"


def test_repeated_run_is_idempotent_and_new_collection_is_not_revision(store, services):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=bcb_payload())

    pipeline, clock, _ = services(store, bcb_handler=handler)
    first = pipeline.run((SgsRequest(PERIOD),))
    second = pipeline.run((SgsRequest(PERIOD),))
    assert len(calls) == 2
    assert first.records == second.records
    clock.advance()
    third = pipeline.run((SgsRequest(PERIOD),))
    assert third.records[0].version == 1
    assert third.records[0].content_id == first.records[0].content_id
    assert third.records[0].receipt_id != first.records[0].receipt_id
    assert len(query(store, first.records[0].observation)) == 2


def test_price_change_for_same_market_timestamp_becomes_new_version(store, services):
    values = iter([10, 12])
    pipeline, _, _ = services(
        store,
        brapi_handler=lambda _: httpx.Response(200, json=brapi_payload(next(values))),
    )
    first = pipeline.run((QuoteRequest(INSTRUMENT),))
    second = pipeline.run((QuoteRequest(INSTRUMENT),))
    assert (first.records[0].version, second.records[0].version) == (1, 2)
    assert first.records[0].record_key == second.records[0].record_key
    assert first.records[0].content_id != second.records[0].content_id
    assert len(query(store, first.records[0].observation)) == 2


@pytest.mark.parametrize("which", ["brapi", "bcb"])
def test_any_provider_failure_leaves_zero_records(store, services, which):
    def brapi_handler(_):
        return httpx.Response(503 if which == "brapi" else 200, json=brapi_payload())

    def bcb_handler(_):
        return httpx.Response(503 if which == "bcb" else 200, json=bcb_payload())

    pipeline, _, _ = services(
        store, brapi_handler=brapi_handler, bcb_handler=bcb_handler
    )
    tasks = (SgsRequest(PERIOD), QuoteRequest(INSTRUMENT)) if which == "brapi" else (
        QuoteRequest(INSTRUMENT), SgsRequest(PERIOD)
    )
    with pytest.raises(FetchError):
        pipeline.run(tasks)
    assert store.query(
        asset=INSTRUMENT.asset, kind=RecordKind.PRICE,
        metric="regular_market_price", period=PERIOD,
    ) == ()
    assert store.query(
        asset=Asset("bcb.sgs", "432"), kind=RecordKind.INDICATOR,
        metric="selic_target", period=PERIOD,
    ) == ()


@pytest.mark.parametrize("provider", ["brapi", "bcb"])
def test_bad_schema_fails_atomically_without_stale_or_partial_data(store, services, provider):
    invalid = brapi_payload()
    invalid["results"][0]["symbol"] = "WRONG3"
    pipeline, _, _ = services(
        store,
        brapi_handler=lambda _: httpx.Response(200, json=invalid)
        if provider == "brapi" else httpx.Response(200, json=brapi_payload()),
        bcb_handler=lambda _: httpx.Response(200, json=[{"data": "bad", "valor": "10"}])
        if provider == "bcb" else httpx.Response(200, json=bcb_payload()),
    )
    with pytest.raises(FetchError) as error:
        pipeline.run((QuoteRequest(INSTRUMENT), SgsRequest(PERIOD)))
    assert error.value.kind is FailureKind.INVALID_RESPONSE
    assert store.query(
        asset=INSTRUMENT.asset, kind=RecordKind.PRICE,
        metric="regular_market_price", period=PERIOD,
    ) == ()


def test_default_execution_disabled_even_with_mock_transport(store, services):
    seen = []
    pipeline, _, _ = services(
        store, bcb_handler=lambda r: (seen.append(r), httpx.Response(200, json=[]))[1],
        enabled=False,
    )
    with pytest.raises(PipelineError, match="disabled"):
        pipeline.run((SgsRequest(PERIOD),))
    assert seen == []


def test_scope_mismatch_blocks_before_any_transport(store, services):
    calls = []
    with pytest.raises(PipelineError, match="scope"):
        services(
            store,
            bcb_handler=lambda r: (calls.append(r), httpx.Response(200, json=[]))[1],
            context=replace(CONTEXT, tenant="another-tenant"),
        )
    assert calls == []


def test_non_synthetic_store_disallowed(services):
    with ObservationStore.memory(scope=SCOPE, synthetic=False) as live_store:
        with pytest.raises(PipelineError, match="real-data"):
            services(live_store, bcb_handler=lambda r: httpx.Response(200, json=[]))


@pytest.mark.parametrize("provider", ["brapi", "bcb"])
def test_non_synthetic_adapter_disallowed(store, services, provider):
    with pytest.raises(PipelineError, match="synthetic"):
        services(
            store,
            brapi_handler=(lambda r: httpx.Response(200, json=brapi_payload()))
            if provider == "brapi" else None,
            bcb_handler=(lambda r: httpx.Response(200, json=bcb_payload()))
            if provider == "bcb" else None,
            brapi_synthetic=(provider != "brapi"),
            bcb_synthetic=(provider != "bcb"),
        )


@pytest.mark.parametrize("requests", [(), ("unknown",), (SgsRequest(PERIOD), "bad")])
def test_invalid_batch_rejected_before_fetch(store, services, requests):
    seen = []
    pipeline, _, _ = services(
        store, bcb_handler=lambda r: (seen.append(r), httpx.Response(200, json=[]))[1]
    )
    with pytest.raises(PipelineError):
        pipeline.run(requests)
    assert seen == []


def test_batch_limit_preflight_prevents_network_calls(store, services):
    seen = []
    pipeline, _, _ = services(
        store, bcb_handler=lambda r: (seen.append(r), httpx.Response(200, json=[]))[1]
    )
    with pytest.raises(PipelineError, match="bounded"):
        pipeline.run(tuple(SgsRequest(PERIOD) for _ in range(17)))
    assert not seen


def test_sgs_window_bound_preflight_prevents_prior_quote_fetch(store, services):
    seen = []
    pipeline, _, _ = services(
        store, brapi_handler=lambda r: (seen.append(r), httpx.Response(200, json=brapi_payload()))[1],
        bcb_handler=lambda _: httpx.Response(200, json=[]),
    )
    bad_period = Period(date(2024, 1, 1), date(2025, 1, 2))
    with pytest.raises(PipelineError, match="exceeds"):
        pipeline.run((QuoteRequest(INSTRUMENT), SgsRequest(bad_period)))
    assert not seen


def test_missing_adapter_preflight_prevents_other_provider_fetch(store, services):
    seen = []
    pipeline, _, _ = services(
        store, bcb_handler=lambda r: (seen.append(r), httpx.Response(200, json=[]))[1]
    )
    with pytest.raises(PipelineError, match="unavailable"):
        pipeline.run((SgsRequest(PERIOD), QuoteRequest(INSTRUMENT)))
    assert not seen


def test_stale_policy_rejected_without_fetch(store, services):
    seen = []
    pipeline, _, _ = services(
        store, bcb_handler=lambda r: (seen.append(r), httpx.Response(200, json=[]))[1]
    )
    with pytest.raises(PipelineError, match="stale"):
        pipeline.run(
            (SgsRequest(PERIOD),),
            cache_policy=CachePolicy(enabled=True, ttl=0, allow_stale=True, max_stale=60),
        )
    assert not seen


def test_stale_envelope_rejected_without_persisting(store, services, monkeypatch):
    pipeline, _, adapters = services(
        store, bcb_handler=lambda _: httpx.Response(200, json=bcb_payload())
    )
    original = adapters["bcb"].selic_target
    def stale(*args, **kwargs):
        return replace(original(*args, **kwargs), freshness=Freshness.STALE)
    monkeypatch.setattr(adapters["bcb"], "selic_target", stale)
    with pytest.raises(PipelineError, match="stale"):
        pipeline.run((SgsRequest(PERIOD),))
    assert store.query(
        asset=Asset("bcb.sgs", "432"), kind=RecordKind.INDICATOR,
        metric="selic_target", period=PERIOD,
    ) == ()


def test_empty_sgs_window_is_not_claimed_to_be_zero_or_complete(store, services):
    period = Period(date(2026, 10, 26), DAY)
    pipeline, _, _ = services(store, bcb_handler=lambda _: httpx.Response(200, json=[]))
    result = pipeline.run((SgsRequest(period),))
    assert result.records == ()
    assert result.tasks[0].received == 0
    assert result.tasks[0].unreturned_dates == (
        date(2026, 10, 26), date(2026, 10, 27), DAY
    )


def test_sgs_missing_zero_and_invalid_qualities_preserved(store, services):
    period = Period(date(2026, 10, 26), DAY)
    body = [
        {"data": "26/10/2026", "valor": "0"},
        {"data": "27/10/2026", "valor": None},
        {"data": "28/10/2026", "valor": "NaN"},
    ]
    pipeline, _, _ = services(store, bcb_handler=lambda _: httpx.Response(200, json=body))
    result = pipeline.run((SgsRequest(period),))
    assert [x.observation.quality for x in result.records] == [
        Quality.PRESENT, Quality.MISSING, Quality.INVALID
    ]
    assert [x.observation.value for x in result.records] == [Decimal(0), None, None]
    assert all(r.version == 1 for r in result.records)


def test_cache_freshness_preserved_and_no_new_collection_claim(store, services):
    seen = []
    pipeline, _, _ = services(
        store, bcb_handler=lambda r: (seen.append(r), httpx.Response(200, json=bcb_payload()))[1]
    )
    cache = CachePolicy(enabled=True, ttl=60)
    first = pipeline.run((SgsRequest(PERIOD),), cache_policy=cache)
    second = pipeline.run((SgsRequest(PERIOD),), cache_policy=cache)
    assert len(seen) == 1
    assert first.tasks[0].freshness is Freshness.NETWORK
    assert second.tasks[0].freshness is Freshness.FRESH
    assert first.records == second.records


def test_no_token_in_request_repr_or_report():
    task = QuoteRequest(INSTRUMENT, token="synthetic-placeholder")
    assert "synthetic-placeholder" not in repr(task)
    assert "synthetic-placeholder" not in repr(PipelineRunDummy())


def PipelineRunDummy():
    return {"provider": "brapi", "freshness": Freshness.NETWORK}
