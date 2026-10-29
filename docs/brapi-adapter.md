# NV-002: adaptador brapi v2 de cotacao

Recorte: um ativo por chamada, somente regularMarketPrice. Implementacao
independente, sem codigo literal do Winning Investments v2. Base b6551a6 apos
merge PR #12. [ADR-0004](adr/ADR-0004-brapi-quote-adapter.md).

## Contrato oficial consultado em 2026-10-29

- [Cotacao](https://brapi.dev/docs/acoes/cotacao): GET /api/v2/stocks/quote,
  query symbols; results[].data, requestedSymbol, symbol, changed. Tickers antigos
  podem ser resolvidos para outro codigo; adapter rejeita essa substituicao.
- [Versionamento](https://brapi.dev/docs/versioning): novas integracoes em v2;
  legado /api/quote continua disponivel, mas nao e usado aqui.
- [OpenAPI JSON](https://brapi.dev/openapi.json): OpenAPI 3.1.0, info.version 3.0.0,
  operationId getStockQuotes, schemas StockQuoteResponse/Series/Snapshot.
  SHA-256 do documento consultado:
  dae9d382e9b72d095a7499bc1203a928e4f942ff5f7a9db1d46585caa11984fc.
  Documento baixado somente para inspecao em memoria, sem copiar payload real.
- [Autenticacao](https://brapi.dev/docs/authentication): Bearer no header;
  sandbox sem chave para PETR4/MGLU3/VALE3/ITUB4, 20 requisicoes/minuto/IP.
- [Limites](https://brapi.dev/faq/quais-as-limitacoes): Gratuito/Startup/Pro
  informam respectivamente 15.000/150.000/500.000 requisicoes por ciclo,
  1/4/16 simultaneas por conta e 1/10/20 tickers por chamada; delays aproximados
  30/15/5 minutos. Contas autenticadas nao possuem limite por minuto nessa
  documentacao; limites e direitos devem ser reconferidos no plano contratado.
- [Erros](https://brapi.dev/docs/troubleshooting): 401 autenticacao, 403 acesso,
  429 quota/concorrencia; obedecer Retry-After. Nenhum fallback troca credenciais,
  plano, endpoint ou ativo apos negacao de acesso.
- [Dicionario](https://brapi.dev/docs/dicionario): null nao equivale a zero;
  ausencia nao permite inferir motivo de negocio ou NOT_APPLICABLE.

O link oficial de termos https://brapi.dev/terms-of-use retornou 404 na consulta.
Direitos de redistribuicao e uso comercial nao foram confirmados. A licenca
declarada no OpenAPI nao deve ser interpretada como licenca de todos os dados.
Nao houve chamada de cotacao, conta ou dicionario de dados, nem uso de token;
somente paginas de documentacao e o schema publico foram consultados.
Tentativas /docs/quote e /docs/rate-limits nao localizaram paginas validas;
/docs/openapi excedeu limite da ferramenta, resolvido pelo JSON oficial.

## Interface e normalizacao

BrapiAdapter(client, synthetic=..., now=...) recebe SecureHttpClient com provider
brapi e origin https://brapi.dev. Nao cria um segundo pool nem fecha o cliente
emprestado. Chamada quote(BrapiInstrument(asset, symbol, currency), context=...,
token=None, cache_policy=...) retorna JsonEnvelope[BrapiQuote].

O chamador deve confirmar que Asset identifica o instrumento atual e que a moeda
e correta. Validacao local de ticker aceita apenas 4 caracteres alfanumericos
maiusculos seguidos de 1-2 digitos; nao consulta cadastro ou garante existencia.
Moeda esperada e comparada exatamente com a resposta, sem fallback para BRL.
O contrato base valida formato de moeda, nao possui cadastro ISO.

| Campo | Destino / regra |
| --- | --- |
| requestedSymbol, symbol, changed | identidade exata solicitada, changed=false; caso contrario FetchError INVALID_RESPONSE |
| regularMarketPrice | Observation PRICE/regular_market_price, Decimal finito nao negativo |
| moeda currency | Observation.currency, obrigatoria e igual ao mapeamento verificado |
| unidade / ajuste | currency/share; provider_unspecified (nao supor ajuste corporativo) |
| regularMarketTime | BrapiQuote.market_at UTC; Period com a mesma data UTC nas duas pontas |
| requestedAt | BrapiQuote.requested_at UTC; nao vira publicacao ou periodo |
| envelope.fetched_at | Provenance.collected_at original, inclusive cache/stale |
| publicacao nao fornecida | published_at=None e motivo explicito |
| origem | brapi, URL publica sem credencial, versao brapi-stock-quote-v2-1, synthetic explicito |

NULL ou preco ausente => MISSING; zero => PRESENT; negativo, string, bool,
lista/objeto => INVALID. JSON NaN/Infinity e rejeitado pelo cliente HTTP.
Campo de preco ausente e tolerado para expressar qualidade; a projecao local
nao valida o OpenAPI inteiro. Moeda, datas, envelope e identidade incoerentes
falham antes do armazenamento no cache; nao ha Observation com metadados inventados.
Nomes, logos, volume, market cap, maximas/minimas, historicos e fundamentos nao
sao consumidos nem retidos. Nao se deriva LPA, VPA, multiplos ou dividendos.

Datas aceitam ISO com T, segundos, ate 6 casas fracionarias e offset/Z explicito;
epoch numerico, data sem horario/fuso, offset invalido ou desconhecido (-00:00),
calendario invalido e futuro sao rejeitados.
Usar clocks UTC coerentes para adapter/cliente. requestedAt pode preceder a
cotacao: nao e uma promessa de publicacao nem limite superior do snapshot.
Sem calendario de pregao, idade maxima financeira ou garantia point-in-time.

## Politicas reutilizadas e limites operacionais

Timeout, retry/backoff/jitter, Retry-After, limiter e cache pertencem exclusivamente
ao SecureHttpClient. Compartilhar uma instancia por conta/provedor. Para sandbox,
configurar RetryPolicy(min_interval=3) ou intervalo mais conservador e coordenar
outros processos no mesmo IP externamente; uma instancia serial nao garante
quota global. O adapter nao mede saldo mensal nem aumenta concorrencia por plano.
RateLimit-* e headers de descontinuacao nao sao expostos pelo envelope HTTP atual;
observabilidade proativa desses headers e acompanhamento de sunset ficam pendentes.
429/Retry-After continua sendo respeitado pelo transporte.

Contexto de tenant/entitlement/revisao vem da camada autenticada. Token opcional
vai somente no header, nunca na URL, Source, repr ou logs do adapter. Nao le .env,
nao cria credencial e nao faz fallback de permissao. Cache usa a segregacao HTTP;
schema inclui moeda esperada e synthetic para evitar reutilizacao com semantica
diferente. A identidade Asset e aplicada ao snapshot validado apos o cache,
sempre conforme o mapeamento explicito fornecido naquela chamada.

Envelope e preservado integralmente: freshness, age_seconds, fetched_at, attempts,
stale_reason e failure_status. Stale exige opt-in e nao recebe uma nova coleta.
401/403/schema invalido nao servem stale. Cotacao antiga pode vir por NETWORK;
idade financeira deve ser avaliada por market_at, nao por freshness.

## Exemplo sintetico, sem rede e sem token

```python
from datetime import datetime, timezone
import httpx
from novera.brapi import BrapiAdapter, BrapiInstrument
from novera.contracts import Asset
from novera.http import AccessContext, RetryPolicy, SecureHttpClient

body = {
    "results": [{
        "requestedSymbol": "TEST3", "symbol": "TEST3", "changed": False,
        "data": {"currency": "BRL", "regularMarketPrice": 0,
                 "regularMarketTime": "2026-10-29T17:00:00Z"},
    }],
    "requestedAt": "2026-10-29T17:01:00Z", "took": 1,
}
def now():
    return datetime(2026, 10, 29, 18, tzinfo=timezone.utc)

with SecureHttpClient(
    "brapi", "https://brapi.dev", policy=RetryPolicy(min_interval=3),
    transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)), now=now,
) as client:
    result = BrapiAdapter(client, synthetic=True, now=now).quote(
        BrapiInstrument(Asset("synthetic-security-id", "share-a"), "TEST3", "BRL"),
        context=AccessContext("demo-user", "demo-plan", "revision-1"),
    )
    assert result.data.price.value == 0
    assert result.data.price.quality == "present"
    assert result.data.price.provenance.source.synthetic
```

## Validacao e proximos passos

Executar uv run --offline --locked pytest -q, ruff check ., ruff format --check .,
python scripts/check_secrets.py e --self-test, sempre pelo uv run locked.
Auditoria: uv export --locked --all-groups --no-emit-project --no-hashes para
temporario, seguido de pip-audit --no-deps --disable-pip -r desse arquivo.
Testes usam MockTransport, relogios/sleeps falsos e guard Python DNS/connect;
guard nao constitui isolamento universal do SO. Nenhum endpoint real na CI.
Auditoria de dependencias e instalacao CI exigem rede para indices/advisories.
Comandos, resultados finais, falhas e CI ficam no PR, com handoff de documentacao.

Pendencias: revisao humana; validar termos/plano antes de uso real; resolucao de
identidade/corporate actions e periodos antes de fundamentos/proventos.
NV-002 permanece aberta. BCB, armazenamento e pipeline nao integram este PR.
