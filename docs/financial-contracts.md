# Contratos financeiros (NV-004)

Implementacao: `backend/src/novera/contracts.py`. ADR: [ADR-0001](adr/ADR-0001-financial-observations.md).
Somente contratos internos validados; sem calculo de preco justo ou integracao.

- Asset: identificador estavel em namespace; ticker isolado nao identifica historico.
- Source: fornecedor, referencia do documento/requisicao, versao da regra e rotulo sintetico.
- Period: inicio/fim inclusivos; precos usam uma data unica.
- Provenance: fonte, periodo, publicacao conhecida ou motivo de desconhecimento,
  coleta com fuso horario; publicacao nao pode ocorrer depois da coleta.
- Observation: tipo, metrica, valor Decimal, qualidade, unidade e moeda.
- Demonstrativos: escopo consolidado/individual, base instant/duration/year_to_date
  e revisao explicita. Valores normalizados em unidade base, sem escala implicita.
- Proventos: tipo e base gross/net/unknown, datas ex/pagamento quando conhecidas.
- Precos: unidade currency/share, moeda e convencao de ajuste explicitas.

## Estados e exemplos

| Entrada | Representacao | Interpretacao |
|---|---|---|
| zero conhecido | Decimal("0"), PRESENT | valor numerico zero |
| indisponivel | None, MISSING, motivo | nao avaliavel |
| dado rejeitado | None, INVALID, motivo | nao avaliavel; sem substituir por zero |
| nao aplicavel | None, NOT_APPLICABLE, motivo | nao avaliavel |
| float, NaN, infinito | rejeitado | usar Decimal finito |
| None com PRESENT | rejeitado | estado contraditorio |

Fixtures sinteticas executaveis em `backend/tests/test_contracts.py` mostram
indicadores negativos, precos, demonstrativos e proventos validos/invalidos.
Nenhum valor destes exemplos representa cotacao ou recomendacao.
Nao ha serializacao, cadastro de moedas, taxonomia CVM, conversao de unidades,
reconciliacao de revisoes, ajuste corporativo ou calendario implementados.
A ausencia de data ex/pagamento em provento exige investigacao pelo consumidor;
nao autoriza inferir que nao houve pagamento. Nenhum registro aprova estrategia.

## Validacao

```sh
uv sync --locked --group dev
uv run --offline --locked pytest -q
```
