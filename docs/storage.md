# NV-009 — Armazenamento local idempotente

**Escopo:** repositório SQLite local, sem dados reais, rede, API, frontend ou pipeline.
Ver [ADR-0006](adr/ADR-0006-sqlite-observation-storage.md) para decisão e riscos.

## Interface

- `StorageScope(tenant, entitlement, credential_revision)` é um contexto
  **opaco, não secreto**, fornecido pela autenticação. `synthetic` é explícito.
- `ObservationStore.memory(scope=..., synthetic=...)` fornece DB em memória.
- `ObservationStore.local(path, scope=..., synthetic=..., create=True)` cria
  exclusivamente um arquivo que ainda não existe, sem criar diretórios.
  Sem `create=True`, só abre banco já conhecido e validado. Caminho absoluto.
- `ingest(record_key, observation)` e `ingest_many([(key, observation), ...])`
  são transacionais. Chave estável por evento; a aplicação deve defini-la.
- `query(asset=..., kind=..., metric=..., period=..., version=None, provider=None)`
  retorna tupla de `StoredObservation` com `version`, `logical_id`, `content_id`,
  `receipt_id`, `record_key` e `observation`. Consulta sempre respeita escopo.
- `close()` ou context manager fecha a conexão. Sem compartilhamento entre threads.

### Exemplo offline

```python
from datetime import date, datetime, timezone
from decimal import Decimal
from novera.contracts import Asset, Observation, Period, Provenance, Quality, RecordKind, Source
from novera.storage import ObservationStore, StorageScope

period = Period(date(2026, 10, 28), date(2026, 10, 28))
item = Observation(
    asset=Asset("bcb.sgs", "432"), kind=RecordKind.INDICATOR,
    metric="selic_target", value=Decimal("0.15"), quality=Quality.PRESENT,
    unit="fraction/year", currency=None,
    provenance=Provenance(
        source=Source("bcb", "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados", "v1", True),
        period=period, collected_at=datetime(2026, 10, 30, tzinfo=timezone.utc),
        published_at=None, publication_unknown_reason="not_provided",
    ),
)
with ObservationStore.memory(
    scope=StorageScope("demo-tenant", "public", "revision-1"), synthetic=True
) as store:
    original = store.ingest("SGS432:2026-10-28", item)
    assert store.ingest("SGS432:2026-10-28", item) == original
    assert store.query(asset=item.asset, kind=item.kind, metric=item.metric, period=period)[0] == original
```

## Política de identidade e versões

`logical_id` identifica uma família de registros no escopo de acesso:
namespace + identidade do ativo + classe + métrica + provedor + chave estável.
`content_id` é o hash da projeção econômica validada. Novas coletas com
mesmo valor econômico e alteração somente da data de coleta/URL de fonte
mantêm a mesma versão numérica mas ganham `receipt_id` distinto; reingestão
idêntica não cria outro recibo. Correções de valor/período/qualidade tornam-se
novas versões. A consulta não seleciona a mais recente automaticamente.

## Limites e cuidados

- Sem criptografia de DB em repouso, serviços multi-tenant ou defesa contra
  usuário que possa abrir/copiar o arquivo diretamente.
- Referência de fonte HTTPS deve usar parâmetros de consulta estritamente
  conhecidos (`symbols`, `formato`, `dataInicial`, `dataFinal`), sem credenciais.
- Logs e mensagens de erro não incluem corpo/payload ou segredos; IDs de escopo
  não devem conter credenciais. SQL é parametrizado.
- Identidade da série BCB não é ticker nem instrumento B3.
- Não converte `regular_market_price` brapi em `close` ajustado automaticamente.
- Arquivos *.sqlite3 já estão no `.gitignore`. Banco e dados reais não entram
  no GitHub.
- Testes offline: `uv run --locked pytest -q`, Ruff, scanner de segredos,
  auditoria e GitHub Actions.

## Futura integração

NV-002 ainda precisa de orquestração/pipeline; apenas depois de avaliar direitos
de provedores, política de coleta real, agendamento e identidade de eventos.
Análises técnicas e TechnicalAnalysis ficam para um ciclo posterior.
