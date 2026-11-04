"""Synthetic contracts and mock transport; no market data or network."""

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import pytest
from novera.brapi import BrapiInstrument
from novera.brapi_dividends import (
    BrapiDividendsAdapter,
    DividendWindow,
    _parse,
)
from novera.contracts import Asset, Quality
from novera.http import AccessContext, FetchError, RetryPolicy, SecureHttpClient

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)
INSTRUMENT = BrapiInstrument(Asset("fixture-id", "fixture-share"), "TEST3", "BRL")
WINDOW = DividendWindow(date(2026, 1, 1), date(2026, 12, 31))
CONTEXT = AccessContext("tenant-a", "plan-a", "revision-1")


def payload():
    return {
        "results": [
            {
                "requestedSymbol": "TEST3",
                "symbol": "TEST3",
                "changed": False,
                "data": {
                    "cashDividends": [
                        {
                            "rate": Decimal("0.024242"),
                            "paymentDate": "2026-12-01T23:00:00-03:00",
                            "exDate": None,
                            "lastDatePrior": "2026-08-31T03:00:00Z",
                            "label": "JCP",
                        }
                    ],
                    "stockDividends": [{}],
                    "subscriptions": [],
                },
            }
        ],
        "requestedAt": "2026-11-03T12:00:00Z",
    }


def parse(p):
    return _parse(p, INSTRUMENT, WINDOW, NOW)


def test_exact_rate_calendar_future_and_unknown_status():
    event = parse(payload()).events[0]
    assert event.rate == Decimal("0.024242")
    assert event.payment_date == date(2026, 12, 1)
    assert event.ex_date is None
    assert event.payment_status == "unverified"
    assert event.adjustment == "provider_unspecified"


@pytest.mark.parametrize(
    "value,quality",
    [
        (0, Quality.PRESENT),
        (None, Quality.MISSING),
        (-1, Quality.INVALID),
        (True, Quality.INVALID),
        ("1.2", Quality.INVALID),
        (Decimal("NaN"), Quality.INVALID),
        (0.1, Quality.INVALID),
    ],
)
def test_rate_quality(value, quality):
    p = payload()
    p["results"][0]["data"]["cashDividends"][0]["rate"] = value
    event = parse(p).events[0]
    assert event.quality == quality
    assert (event.rate is None) == (quality != Quality.PRESENT)


@pytest.mark.parametrize(
    "field,value", [("symbol", "OTHER3"), ("changed", True), ("requestedSymbol", None)]
)
def test_identity_fail_closed(field, value):
    p = payload()
    p["results"][0][field] = value
    with pytest.raises(ValueError):
        parse(p)


@pytest.mark.parametrize(
    "field,value",
    [
        ("paymentDate", "2027-01-01"),
        ("paymentDate", "invalid"),
        ("exDate", "2026-02-30"),
        ("approvedOn", "2026-01-01T00:00:00"),
        ("label", {}),
    ],
)
def test_invalid_event(field, value):
    p = payload()
    p["results"][0]["data"]["cashDividends"][0][field] = value
    with pytest.raises(ValueError):
        parse(p)


def test_unknown_date_is_preserved_and_duplicates_rejected():
    p = payload()
    cash = p["results"][0]["data"]["cashDividends"]
    cash[0]["paymentDate"] = None
    assert parse(p).events[0].payment_date is None
    cash.append(deepcopy(cash[0]))
    with pytest.raises(ValueError, match="duplicate"):
        parse(p)


@pytest.mark.parametrize("replacement", [None, {}, [None], [{}] * 5001])
def test_bad_arrays(replacement):
    p = payload()
    p["results"][0]["data"]["subscriptions"] = replacement
    with pytest.raises(ValueError):
        parse(p)


@pytest.mark.parametrize(
    "start,end",
    [(date(2026, 2, 1), date(2026, 1, 1)), (date(2000, 1, 1), date(2026, 1, 1)), (NOW, NOW)],
)
def test_window_limits(start, end):
    with pytest.raises(ValueError):
        DividendWindow(start, end)


def test_empty_is_not_certified_coverage():
    p = payload()
    p["results"][0]["data"]["cashDividends"] = []
    assert parse(p).events == ()
    del p["results"][0]["data"]["cashDividends"]
    with pytest.raises(ValueError):
        parse(p)


def test_transport_precision_cache_partition_and_no_secret_in_url():
    requests = []

    def handler(request):
        requests.append(request)
        assert "token" not in str(request.url)
        assert request.url.params["startDate"] == "2026-01-01"
        return httpx.Response(
            200,
            text='{"results":[{"requestedSymbol":"TEST3",'
            '"symbol":"TEST3","changed":false,"data":{"cashDividends":'
            '[{"rate":0.1234567890123456789,"paymentDate":null}],'
            '"stockDividends":[],"subscriptions":[]}}],'
            '"requestedAt":"2026-11-03T12:00:00Z"}',
        )

    with SecureHttpClient(
        "brapi",
        "https://brapi.dev",
        transport=httpx.MockTransport(handler),
        policy=RetryPolicy(min_interval=0),
        now=lambda: NOW,
    ) as client:
        adapter = BrapiDividendsAdapter(client, synthetic=True, now=lambda: NOW)
        result = adapter.dividends(INSTRUMENT, WINDOW, context=CONTEXT).data
        assert result.events[0].rate == Decimal("0.1234567890123456789")
        assert result.historical_coverage == "unknown"
        assert result.bazin_eligible is False
        assert result.currency is None
        assert result.synthetic is True
        adapter.dividends(INSTRUMENT, WINDOW, context=CONTEXT)
        assert len(requests) == 1
        adapter.dividends(INSTRUMENT, WINDOW, context=AccessContext("tenant-b", "plan-a", "r1"))
        assert len(requests) == 2


@pytest.mark.parametrize("status", [401, 403, 429])
def test_http_failures_are_not_empty_data(status):
    with SecureHttpClient(
        "brapi",
        "https://brapi.dev",
        transport=httpx.MockTransport(lambda r: httpx.Response(status)),
        policy=RetryPolicy(min_interval=0, max_retries=0),
        now=lambda: NOW,
    ) as client:
        adapter = BrapiDividendsAdapter(client, synthetic=True, now=lambda: NOW)
        with pytest.raises(FetchError):
            adapter.dividends(INSTRUMENT, WINDOW, context=CONTEXT)


def test_bearer_is_header_only_and_credentials_partition_cache():
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url).find("fixture-key") == -1
        assert request.headers["Authorization"].startswith("Bearer fixture-key-")
        p = payload()
        p["results"][0]["data"]["cashDividends"][0]["rate"] = 1
        return httpx.Response(200, json=p)

    with SecureHttpClient(
        "brapi",
        "https://brapi.dev",
        transport=httpx.MockTransport(handler),
        policy=RetryPolicy(min_interval=0),
        now=lambda: NOW,
    ) as client:
        adapter = BrapiDividendsAdapter(client, synthetic=True, now=lambda: NOW)
        for token in ("fixture-key-a", "fixture-key-a", "fixture-key-b"):
            adapter.dividends(INSTRUMENT, WINDOW, context=CONTEXT, token=token)
        assert len(requests) == 2
        with pytest.raises(ValueError, match="credential"):
            adapter.dividends(INSTRUMENT, WINDOW, context=CONTEXT, token="bad\nheader")
        assert len(requests) == 2


@pytest.mark.parametrize("requested", ["2027-01-01T00:00:00Z", "2026-11-03", None])
def test_bad_request_timestamp(requested):
    p = payload()
    p["requestedAt"] = requested
    with pytest.raises(ValueError):
        parse(p)
