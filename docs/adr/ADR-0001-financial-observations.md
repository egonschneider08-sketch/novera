# ADR-0001: Observacoes financeiras tipadas

Status: proposto para revisao no PR da NV-004
Data: 2026-10-29

## Contexto
NV-004 exige contratos rastreaveis sem transformar ausencia em zero ou falha.
A referencia Winning Investments v2 nao esta disponivel como codigo/licenca
no ambiente inspecionado. Nenhuma formula ou equivalencia e afirmada.

## Decisao
Usar dataclasses imutaveis da biblioteca padrao, com validacao na construcao,
Decimal finito para valores presentes e enums para tipo e qualidade.
Um contrato Observation contem ativo, indicador/conta, unidade, moeda e
proveniencia. RecordKind distingue indicador, preco, demonstrativo e provento;
metadados especificos sao validados por tipo. Evita dependencia de framework.

## Alternativas
Pydantic facilitaria parsing/JSON, mas adicionaria dependencia antes dos adapters.
Classes separadas por registro podem substituir o discriminador quando houver
mais comportamento; hoje duplicariam regras comuns de proveniencia.

## Consequencias
O contrato e interno Python, nao e um schema HTTP/JSON. Nao aceita floats nem
converte tipos silenciosamente. Missing, invalid e not_applicable exigem None
mais motivo; zero e PRESENT. Valores negativos podem ser validos em indicadores
e demonstrativos; preco negativo e rejeitado. Zero de preco nao implica negociabilidade.
Moeda valida somente formato de tres letras; cadastro ISO nao esta implementado.
Unidades, ajustes e versoes de regras precisam de convencoes por adapter.
Datas de publicacao desconhecidas ficam explicitas: nao habilitam backtest point-in-time.
Fonte pode ser sintetica e deve rotular a observacao. Nao ha dados reais neste PR.

## Evidencias
`backend/tests/test_contracts.py` valida estados, cronologia, precisao e tipos.
Resultados de execucao e SHA estao no PR NV-004.
Contexto de produto consultado: Notion, 04 Motor Financeiro e Dados,
https://app.notion.com/p/407f69f1ed0681eea788dd6a733da59d (nao verificado).

## Rollback
Reverter o commit NV-004 antes de adapters ou persistencia dependerem dele;
nao existem migracoes nem dados persistidos.
