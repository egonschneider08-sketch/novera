# Heuristicas puras NV-002

Implementacao independente: `novera.strategies`. Sem HTTP, banco, relogio global
ou dependencia adicional. Auditoria: [migracao](migrations/winning-investments-v2.md).
Politicas e divergencias: [ADR-0002](adr/ADR-0002-pure-valuation-heuristics.md).

## Interfaces

- graham(price, eps, bvps, *, as_of): cada input e PerShareInput de Observation.
- bazin(price, history, *, as_of, target_yield=Decimal("0.06")): historico e
  DividendHistory, pagamentos CashPayment(event_id, PerShareInput).
- PerShareInput.share_basis: convencao de ajuste certificada pelo chamador;
  deve coincidir em todos os inputs e com adjustment da observacao de preco.
- Metricas obrigatorias: close, earnings_per_share, book_value_per_share,
  cash_distribution, com unit currency/share e moeda comum.
- Historico: complete explicito, cobertura com Provenance, Asset, moeda,
  base por acao e tax_basis gross/net. Sem inferencia a partir de lista vazia.
- StrategyResult: versao, as_of, rotulo sintetico, evidencia, cobertura,
  parametros, DerivedMetric e Criterion com justificativa. Nao e uma cotacao.

## Exemplo sintetico Graham (nao representa empresa real)

```python
from datetime import date, datetime, timezone
from decimal import Decimal
from novera.contracts import Asset, Source, Period, Provenance, Observation, Quality, RecordKind
from novera.strategies import PerShareInput, graham

as_of = datetime(2026, 10, 28, 23, tzinfo=timezone.utc)
asset = Asset("synthetic", "example")
source = Source("synthetic-example", "fixture:example", "1", True)

def input_value(metric, value, period, kind=RecordKind.INDICATOR):
    observation = Observation(
        asset=asset, kind=kind, metric=metric, value=Decimal(value),
        quality=Quality.PRESENT, unit="currency/share", currency="BRL",
        provenance=Provenance(source, period, as_of, as_of),
        adjustment="unadjusted" if kind is RecordKind.PRICE else None,
    )
    return PerShareInput(observation, "unadjusted")

price = input_value("close", "20", Period(date(2026, 10, 28), date(2026, 10, 28)), RecordKind.PRICE)
eps = input_value("earnings_per_share", "2", Period(date(2025, 1, 1), date(2025, 12, 31)))
bvps = input_value("book_value_per_share", "20", Period(date(2025, 12, 31), date(2025, 12, 31)))
result = graham(price, eps, bvps, as_of=as_of)
number = next(metric.value for metric in result.metrics if metric.name == "graham_number")
assert number == Decimal("30")
assert result.synthetic
```

Exemplos executaveis de Bazin, cobertura incompleta e desconhecimento estao em
`backend/tests/test_strategies.py`. Fixtures sao criadas em memoria, sem provedores.

## Interpretacao

pass/fail valem somente para um criterio didatico especificado; unknown significa
que a evidencia nao permite avalia-lo. Estado global unknown se qualquer criterio
for unknown, preservando criterios conhecidos na lista. Metricas ausentes usam
None e qualidade MISSING com motivo; qualidade original permanece na evidencia.
Teto/numero heuristico nao sao valor intrinseco definitivo nem recomendacao.
Nao usar estes resultados como backtest, ranking ou validacao historica.
Datas sao UTC para referencia de avaliacao; nao existe calendario de pregao.
Informar uma base por acao nao executa nem valida ajustes corporativos: adapters
precisam evidencia verificavel antes de chamar o dominio.
