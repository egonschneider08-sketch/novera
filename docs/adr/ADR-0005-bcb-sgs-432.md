# ADR-0005: adaptador BCB para meta Selic SGS 432

Status: proposto para revisao NV-002. Data: 2026-10-30. Base: main 29963c0.

## Contexto

Contratos NV-004 e SecureHttpClient ja estao integrados. A referencia perdia a
data/unidade da serie BCB e convertia falhas em None. O catalogo oficial identifica
432 como meta Selic do Copom, diaria e expressa em percentual ao ano.

## Decisao

Criar novera.bcb com BcbAdapter.selic_target(Period, context, cache_policy).
Cliente compartilhado injetado: provider=bcb, origin=https://api.bcb.gov.br.
Endpoint fixo /dados/serie/bcdata.sgs.432/dados, formato=json, datas explicitas
dd/MM/aaaa. Limite local de 366 dias inclusivos, menor que os dez anos informados
pelo BCB. Nao dividir consultas automaticamente nem implementar ultimos/N.

Resultado JsonEnvelope[SgsWindow]: observacoes ordenadas e datas do intervalo
nao retornadas, sem preencher finais de semana, feriados ou supor completude.
Lista vazia significa nenhuma observacao retornada; nao significa taxa zero.
Cada linha vira Observation INDICATOR com Asset(bcb.sgs, 432), selic_target,
unit=fraction/year e currency=None. A identidade e da serie, nao de um titulo.
Period representa a data nominal informada pelo SGS, sem conversao de fuso,
sem transformar taxa anual em retorno diario. Publicacao desconhecida; coleta
original do envelope HTTP, inclusive fresh/stale. Fonte BCB, URL da consulta,
versao de regra e flag synthetic explicita em todas as observacoes.

Valores decimais textuais com ponto sao convertidos sem float. Dividir por 100
e implementado por deslocamento exato do expoente Decimal, independente da
precisao global. Zero e PRESENT; ausencia/null/string vazia e MISSING. Negativo
(politica conservadora especifica desta meta), tipos incorretos, virgula,
expoente textual ou string acima de 64 caracteres sao INVALID. Nao ha teto de
100% inventado. Nao generalizar essa regra para outras taxas ou series.

Envelope nao-array, linha nao-objeto, data ausente/invalida, duplicada ou fora
do periodo invalidam a resposta inteira antes do cache. Nao descartar linhas
silenciosamente. Campos extras nao sao retidos. Datas futuras na consulta sao
rejeitadas pelo dia UTC do clock local; o clock deve ser coerente com o cliente.

## Alternativas

Retornar apenas ultimo valor descartaria periodo e evidencia. Interpolar ou
carregar taxa anterior inventaria dados e cobertura. Conversao float afetaria
precisao. Cliente/SDK paralelo duplicaria resiliencia. Copia literal da referencia
depende de autorizacao de licenciamento e nao e necessaria.

## Consequencias e limites

Sem dependencias novas ou mudancas nos contratos/HTTP/brapi. Reuso de retry,
429/Retry-After, limiter e cache existente; sem quota oficial numerica presumida.
Cache segregado por acesso e synthetic; MISSING/INVALID sao valores de qualidade
cacheaveis, falhas estruturais nao. HTTP nao-200 permanece FetchError, inclusive
204/404; nao converte indisponibilidade em ausencia economica.

Sem prova de publicacao, revisao historica, cobertura/calendario ou disponibilidade
ao vivo. O catalogo publica ODbL para os dados; licenca do software e distinta.
Sem redistribuicao de datasets neste incremento. Referencias, falhas de consulta
e handoff: [guia BCB](../bcb-adapter.md).

## Evidencias

Baseline main: 277 testes aprovados. Novos testes usam MockTransport, clocks/sleeps
falsos e guard Python DNS/connect. Resultados finais e CI no PR e handoff Notion.
Leitura da documentacao oficial concluida; verificacoes pontuais de dados fora
da suite retornaram HTTP 400, portanto nao confirmam o wire schema ao vivo.

## Rollback

Reverter o incremento BCB; nenhuma migracao persistente, dependencia ou coleta
agendada foi introduzida. NV-002 permanece em desenvolvimento ate revisao/aceite.
