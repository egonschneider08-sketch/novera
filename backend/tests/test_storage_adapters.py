"""Integration of the existing provider projections with offline, scoped persistence."""

from datetime import date, datetime, timezone
from decimal import Decimal

import httpx
import pytest
from novera.bcb import BcbAdapter
from novera.brapi import BrapiAdapter, BrapiInstrument
from novera.contracts import Asset, Period
from novera.http import AccessContext, SecureHttpClient
from novera.storage import ObservationStore, StorageScope

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
DAY = date(2026, 10, 28)


@pytest.mark.parametrize("provider", ["bcb", "brapi"])
def test_existing_adapter_contract_roundtrip(provider):
    context = AccessContext("synthetic-user", "public", "v1")
    payload = (
        [{"data": "28/10/2026", "valor": "15.00"}]
        if provider == "bcb"
        else {
            "results": [
                {
                    "requestedSymbol": "TEST3",
                    "symbol": "TEST3",
                    "changed": False,
                    "data": {
                        "currency": "BRL",
                        "regularMarketTime": "2026-10-28T14:30:00-03:00",
                        "regularMarketPrice": 0,
                    },
                }
            ],
            "requestedAt": "2026-10-28T17:31:00Z",
            "took": 1,
        }
    )
    origin = "https://api.bcb.gov.br" if provider == "bcb" else "https://brapi.dev"
    with (
        SecureHttpClient(
            provider,
            origin,
            now=lambda: NOW,
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
        ) as client,
        ObservationStore.memory(
            scope=StorageScope("synthetic-user", "public", "v1"), synthetic=True
        ) as store,
    ):
        if provider == "bcb":
            envelope = BcbAdapter(client, synthetic=True, now=lambda: NOW).selic_target(
                Period(DAY, DAY), context=context
            )
            value = envelope.data.observations[0]
            key = DAY.isoformat()
        else:
            envelope = BrapiAdapter(client, synthetic=True, now=lambda: NOW).quote(
                BrapiInstrument(Asset("synthetic", "security-a"), "TEST3", "BRL"),
                context=context,
            )
            value = envelope.data.price
            key = envelope.data.market_at.isoformat()
        store.ingest(key, value)
        (recovered,) = store.query(
            asset=value.asset,
            kind=value.kind,
            metric=value.metric,
            period=value.provenance.period,
        )
        assert recovered.observation == value
        assert recovered.observation.provenance.collected_at == envelope.fetched_at
        assert recovered.observation.value == (Decimal("0.15") if provider == "bcb" else Decimal(0))
