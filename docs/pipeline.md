# NV-023 — Pipeline financeiro transacional e explícito

Referências: [issue #17](https://github.com/egonschneider08-sketch/novera/issues/17),
[ADR-0007](adr/ADR-0007-opt-in-financial-pipeline.md),
[contratos](financial-contracts.md), [storage](storage.md),
[brapi](brapi-adapter.md), [BCB](bcb-adapter.md).

## O que existe

`FinancialPipeline` integra adaptadores brapi v2 e SGS 432 ao
`ObservationStore` local; não é um serviço de coleta contínua.
É necessário construir cliente HTTP, adaptador, storage e contexto
separadamente e injetá-los. Sem import side effects, scheduler, frontend
ou chamadas reais nos testes.

### Restrições deliberadas

- `enabled=False` é default e impede que `run` faça requisições. Mesmo com
  `enabled=True`, o programa chamador deve fornecer transporte isolado,
  assegurar autorização, quotas, direitos de dados e política de rede.
- `synthetic=True` é etiqueta de procedência e **não bloqueia rede**
  por si mesma. O pipeline inicial recusa storage/adapters `synthetic=False`.
- `StorageScope` deve ser exatamente equivalente aos três identificadores
  de `AccessContext`; origem dos contextos deve ser autenticação confiável.
- `Freshness.STALE` nunca é escrita. Padrão `CachePolicy(enabled=False)`;
  se cache fresco for habilitado, o relatório continua diferenciando
  FRESH de NETWORK e a idempotência do storage evita duplicar recibos.
- No máximo 16 tarefas por chamada e até 366 dias inclusivos por tarefa BCB;
  qualquer erro em uma tarefa não permite gravar resultados das anteriores.
- Não converter a cotação da brapi em `close` ajustado nem a Selic meta
  em rendimento diário. Publicação desconhecida bloqueia uso point-in-time.

## Exemplo totalmente sintético e offline

```python
from datetime import date, datetime, timezone

import httpx
from novera.bcb import BcbAdapter
from novera.brapi import BrapiAdapter, BrapiInstrument
from novera.contracts import Asset, Period
from novera.http import AccessContext, RetryPolicy, SecureHttpClient
from novera.pipeline import FinancialPipeline, QuoteRequest, SgsRequest
from novera.storage import ObservationStore, StorageScope

now = lambda: datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
context = AccessContext("demo-user", "lab", "r1")
scope = StorageScope("demo-user", "lab", "r1")
quote = {
    "results": [{"requestedSymbol": "TEST3", "symbol": "TEST3",
                 "changed": False,
                 "data": {"currency": "BRL", "regularMarketPrice": 0,
                          "regularMarketTime": "2026-10-28T13:00:00-03:00"}}],
    "requestedAt": "2026-10-28T16:01:00Z",
}
sgs = [{"data": "28/10/2026", "valor": "15.00"}]

with (
    SecureHttpClient(
        "brapi", "https://brapi.dev", now=now,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=quote)),
        policy=RetryPolicy(max_retries=0, min_interval=0),
    ) as brapi_http,
    SecureHttpClient(
        "bcb", "https://api.bcb.gov.br", now=now,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=sgs)),
        policy=RetryPolicy(max_retries=0, min_interval=0),
    ) as bcb_http,
    ObservationStore.memory(scope=scope, synthetic=True) as storage,
):
    pipeline = FinancialPipeline(
        storage,
        context=context,
        brapi=BrapiAdapter(brapi_http, synthetic=True, now=now),
        bcb=BcbAdapter(bcb_http, synthetic=True, now=now),
        enabled=True,  # somente com MockTransport aqui
    )
    run = pipeline.run((
        QuoteRequest(BrapiInstrument(Asset("fixture", "asset-a"), "TEST3", "BRL")),
        SgsRequest(Period(date(2026, 10, 28), date(2026, 10, 28))),
    ))
    assert len(run.records) == 2
    assert run.records[0].observation.value == 0
    assert run.records[1].observation.unit == "fraction/year"
```

Exemplo em memória com `MockTransport`: nenhuma consulta ao mercado.
`enabled=True` jamais deve ser ativado em aplicativo de produção com
clientes reais antes da verificação de direitos, rede e governança.

## Identidade, retorno e falhas

- `QuoteRequest` corresponde a um instrumento/ticker atual explicitamente
  validado. Chave: ticker + horário UTC do snapshot e identidade Asset
  preservada no StorageScope lógico.
- `SgsRequest` corresponde a uma janela com datas explícitas. Cada data
  retornada gera um evento econômico independente. Datas não retornadas
  aparecem em `TaskReport.unreturned_dates`, **sem** criar registros.
- `PipelineRun.records` contém `StoredObservation` na ordem das entradas,
  com version, content_id e receipt_id; `tasks` contém Freshness por fonte,
  quantidade, coleta e lacunas. Resultado não descreve universo completo.
- Erros HTTP mantêm `FetchError` original, com tipo/status/tentativas e sem
  payload ou token. Erros da camada de persistência são `StorageError`.
  `PipelineError` refere-se a políticas, contexto ou identidade.
- Nenhuma gravação é feita antes da última consulta bem-sucedida; não há
  rollback de requisições HTTP já executadas, só transação SQLite.

## Limites operacionais e direitos de uso

A ausência de prova de horário de publicação e revisões/cobertura históricas
não permite afirmativa de point-in-time. As chamadas SGS de um único dia
anteriormente devolveram HTTP 400 em verificações externas, apesar de uma
amostra oficial de intervalo maior confirmar o formato JSON. Não ativar
coleta real sem investigar operacionalmente. A brapi limita redistribuição
de dados; o BCB publica SGS sob ODbL. O pipeline não confere licenciamento.

## Testes e continuidade

Executar `uv run --locked pytest -q`,
`uv run --locked ruff check .`,
`uv run --locked ruff format --check .`,
scanner e auditoria do workflow existente. As execuções reais devem ser
registradas no PR #18 ou no PR associado à issue NV-023.
Não adicionar agendamento, coleta real, exportação ou estratégias nesta entrega.
