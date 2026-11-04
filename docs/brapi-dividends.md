# NV-027 — eventos de proventos brapi

Implementação interna de pesquisa, sem rota pública, coleta automática ou integração
com estratégias. `BrapiDividendsAdapter.dividends` recebe `BrapiInstrument`,
`DividendWindow`, `AccessContext` e, opcionalmente, token Bearer. O operador continua
responsável por verificar identidade do ativo, contrato e direitos de uso.

## Contrato

- GET `/api/v2/stocks/dividends`, um ticker sem conversão silenciosa, janela inclusiva
  explícita de até 1830 dias, no máximo 5000 eventos no conjunto da resposta.
- `rate` é Decimal exato pelo decoder do cliente HTTP. Zero é PRESENT; ausente é
  MISSING; negativo, booleano, string ou não finito é INVALID, nunca zero.
- Datas preservam o componente de calendário informado pelo provedor. Offset deve
  ser explícito quando houver hora; datas nulas permanecem desconhecidas.
- `payment_status=unverified`, `historical_coverage=unknown`,
  `adjustment=provider_unspecified`, `bazin_eligible=False`. Sem certificação de
  publicação ou moeda pelo endpoint. A moeda do mapeamento não é prova externa.
- Eventos em ações e subscrições são apenas contados separadamente. Não entram nos
  valores monetários. Não há soma, yield, registro de caixa ou cálculo de Bazin.
- Duplicações monetárias normalizadas são rejeitadas por ambiguidade. Esse critério
  pode rejeitar eventos distintos sem identificador; não adivinhar qual é correto.
- Payload sem as três listas explícitas, identidade divergente ou evento monetário
  fora da janela falha antes do cache. Eventos sem data ficam visíveis como incertos.
- Collection/request timestamps, versão, origem sintética e mapeamento são preservados.
  O envelope HTTP mantém freshness/cache e a data original da coleta.

## Segurança e execução

Reutiliza `SecureHttpClient`: timeouts, retries GET, status de erro, quotas e cache
por contexto/credencial. Token somente em header Authorization e nunca em query.
Não persiste payload bruto ou credenciais; não expõe dados ao frontend.
O cache é em memória; este incremento não adiciona banco nem muda o pipeline.

```sh
uv run --offline --locked pytest -q backend/tests/test_brapi_dividends.py
```

Testes usam payloads inventados e MockTransport. Não validam disponibilidade,
completude, pagamentos, direitos contratuais ou respostas de conta real.

## Fontes consultadas em 2026-11-04

- https://brapi.dev/docs/acoes/dividendos — envelope, identidade, datas, filtros,
  autenticação e eventos não monetários.

## Próximas etapas / handoff Notion

NV-027 permanece em revisão até aceite e merge. Registrar link do PR e resultado da
CI; não marcar coleta de mercado como validada. Próximas fatias: identidade histórica
de tickers, moeda/base dos valores, cobertura certificada e persistência própria de
eventos. Login HTTP permanece no trabalho NV-026, separado desta entrega.
