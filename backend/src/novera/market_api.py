"""Explicit provider reads for the single-user loopback application."""

import os
import ssl
from contextlib import ExitStack, asynccontextmanager
from datetime import date

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from novera.bcb import BcbAdapter
from novera.brapi import BrapiAdapter, BrapiInstrument
from novera.contracts import Asset, Period
from novera.http import AccessContext, FetchError, RetryPolicy, SecureHttpClient

router = APIRouter(prefix="/api/v1/market", tags=["market"])
PUBLIC = AccessContext("local", "public", "no-credential")
PETR4 = BrapiInstrument(Asset("isin", "BRPETRACNPR6"), "PETR4", "BRL")
END = date(2025, 6, 30)


@asynccontextmanager
async def market_lifespan(app):
    policy = RetryPolicy(timeout=6, max_retries=1, max_wait=10)
    with ExitStack() as stack:
        for name, origin in (("brapi", "https://brapi.dev"), ("bcb", "https://api.bcb.gov.br")):
            transport = httpx.HTTPTransport(
                verify=ssl.create_default_context(),
                proxy=os.getenv("NOVERA_MARKET_PROXY"),
                trust_env=False,
                retries=0,
            )
            client = stack.enter_context(
                SecureHttpClient(name, origin, policy=policy, transport=transport)
            )
            setattr(app.state, name, client)
        yield


@router.get("/{series}")
def market_read(series: str, request: Request, x_novera_read: str = Header(default="")):
    # Browser subresources and ordinary cross-origin forms cannot set this header.
    if x_novera_read != "interactive":
        raise HTTPException(403, "Consulta requer uma ação no Novera.")
    try:
        if series == "petr4":
            quote = BrapiAdapter(request.app.state.brapi, synthetic=False).quote(
                PETR4, context=PUBLIC
            )
            obs = quote.data.price
            reference = quote.data.market_at.isoformat()
            value = obs.value
        elif series == "selic-2t25":
            result = BcbAdapter(request.app.state.bcb, synthetic=False).selic_target(
                Period(END, END), context=PUBLIC
            )
            if not result.data.observations:
                raise HTTPException(404, "Sem observação no período.")
            obs = result.data.observations[0]
            reference = END.isoformat()
            value = obs.value * 100 if obs.value is not None else None
        else:
            raise HTTPException(404, "Série desconhecida.")
    except FetchError as exc:
        raise HTTPException(502, "O provedor não retornou uma resposta válida.") from exc
    if value is None:
        raise HTTPException(422, "Valor ausente ou inválido na fonte.")
    return {
        "series": series,
        "value": str(value),
        "reference": reference,
        "collected": obs.provenance.collected_at.isoformat(),
        "provider": obs.provenance.source.provider,
    }
