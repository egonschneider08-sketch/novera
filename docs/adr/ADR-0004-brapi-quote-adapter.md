# ADR-0004: primeiro adaptador brapi, cotacao v2 de um ativo

Status: proposto para revisao NV-002. Data: 2026-10-29. Base main: b6551a6.

## Contexto

PR #12 fornece transporte, retries, cache segregado e freshness. A auditoria da
referencia identificou ticker nao conferido, perda de datas e uso de truthiness
para valores financeiros. O primeiro adaptador precisa tornar essas falhas
observaveis sem criar armazenamento, pipeline ou novas politicas HTTP.

## Decisao

Implementacao independente em novera.brapi, somente GET /api/v2/stocks/quote com
um symbols por chamada. A documentacao atual recomenda v2 para novas integracoes;
o formato legado plano nao e aceito. Nao adicionar SDK/dependencia nem copiar
trechos da referencia. O chamador injeta um SecureHttpClient compartilhado e
possui seu ciclo de vida. As propriedades somente leitura provider/origin permitem
validar o destino antes de encaminhar credenciais; nenhuma politica HTTP muda.

BrapiInstrument associa explicitamente Asset estavel, ticker atual e moeda
esperada, sob responsabilidade do chamador. Rejeitar changed=true, divergencia
em symbol/requestedSymbol, multiplos resultados e erros parciais no envelope.
Nao inferir identidade historica ou conversao de acoes. Este recorte exige que
o chamador selecione instrumentos cotados por acao/unidade; indices estao fora.

Normalizar somente regularMarketPrice como Observation PRICE, currency/share,
Decimal, com adjustment=provider_unspecified. O horario regularMarketTime e
preservado em UTC no resultado e define Period de uma data UTC, nao calendario
de pregao. requestedAt e horario da consulta do provedor, nao publicacao.
published_at=None com motivo; collected_at vem do envelope HTTP original.
Cache FRESH/STALE preserva todas essas datas e a falha HTTP explicita.

Null/ausente no preco vira MISSING; zero e PRESENT; negativo, bool ou tipo
incorreto vira INVALID com None e motivo fixo. Sem moeda/data/identidade valida,
falhar antes do cache: o contrato exige metadados que nao podem ser inventados.
O schema local e uma projecao conservadora do OpenAPI, nao sua reproducao
integral. Campos nao consumidos nao sao exigidos nem persistidos; preco ausente
e uma tolerancia explicita, embora o OpenAPI o declare obrigatorio.

## Alternativas

Copiar o adapter legado perpetuaria perda de metadados e depende de permissao de
relicenciamento. SDK duplicaria transporte/resiliencia. Mapear fundamentos e
dividendos agora exigiria periodos contabeis, datas de eventos e cobertura que
nao pertencem ao snapshot de cotacao. Usar ticker como Asset seria uma identidade
historica nao comprovada. Preencher data da coleta ou BRL por padrao inventaria
metadados. A rejeicao explicita e preferida nesses casos.

## Consequencias e limites

Sem resolucao de ticker, ajustes corporativos, calendario, fechamento anterior,
fundamentos, proventos ou inferencia de valor justo. Publicacao desconhecida
bloqueia uso point-in-time nas estrategias conservadoras existentes. Snapshot
NETWORK pode conter uma cotacao antiga; freshness HTTP nao e idade financeira.
Valores MISSING/INVALID podem ser cacheados como estados explicitos, nunca como
preco numerico. Falhas estruturais nao sao cacheadas nem autorizam stale.

Clock do adapter e do cliente devem ser coerentes; timestamps futuros frente ao
clock local sao rejeitados sem tolerancia implicita. Nao exigir market_at <=
requested_at: consulta pode iniciar antes da cotacao e o exemplo oficial tambem
apresenta essa ordem. Ambos devem anteceder a validacao local.

Limites de conta, concorrencia, termos e autenticacao: [guia brapi](../brapi-adapter.md).
Nenhuma comprovacao de plano, licenca comercial ou contrato ao vivo neste PR.

## Evidencias

Documentacao/OpenAPI oficiais consultados em 2026-10-29; URLs, hash e limites no
guia. Testes sinteticos com MockTransport e guard DNS/connect em test_brapi.py.
Baseline: 216 passed in 0.64s. Resultados finais e CI anexados ao PR, sem merge.

## Rollback

Reverter o incremento do adapter e as propriedades HTTP adicionadas se nao houver
outros consumidores. Sem dependencia nova, migracao persistente ou dados gravados.
