# NV-014 — API FastAPI v1 (somente laboratório fictício)

**Escopo:** implementação de uma primeira API de demonstração; os endpoints
servem **apenas** LAB-A, LAB-B e LAB-C com dados inventados de `novera.research_demo`.
**Não** consultar empresas reais, brapi, Banco Central, preços ao vivo,
autenticação, carteiras de usuários ou sinais de investimento.

## Execução local, somente loopback

Requisitos: Python 3.12 e `uv`. Da raiz do repositório:

```sh
uv sync --locked --group dev
uv run --offline --locked python -m novera.demo_api
```

O processo local escuta em **http://127.0.0.1:8765**. Ele não é um serviço
hospedado nem deve ser colocado em um servidor público. Para interromper,
use Ctrl+C. Não utilize `uvicorn ... --host 0.0.0.0`: o controle de host da
aplicação não substitui uma configuração segura de rede, autenticação e TLS.

### Rotas aceitas

| Método e rota | Contrato | Natureza |
|---|---|---|
| `GET /api/v1/demo/health` | `HealthOut` | Só informa estado da aplicação local |
| `GET /api/v1/demo/scenarios` | `CatalogOut` | Catálogo LAB-A/B/C |
| `GET /api/v1/demo/scenarios/complete` | `ReportOut` | Exemplo PASS |
| `GET /api/v1/demo/scenarios/expensive` | `ReportOut` | Exemplo FAIL |
| `GET /api/v1/demo/scenarios/incomplete` | `ReportOut` | Exemplo UNKNOWN/missing |
| `GET /api/v1/demo/comparison` | `ComparisonOut` | Três cenários, sem ranking |
| `GET /api/v1/demo/comparison.csv` | CSV | Exportação fictícia |
| `GET /api/v1/openapi.json` | OpenAPI | Modelo HTTP dos endpoints de laboratório |

As páginas `/docs` e `/redoc` não são expostas. JSON e CSV devem
corresponder aos produzidos pelo backend Python sem conversão de dinheiro
para floats. O JSON mantém `Decimal` como texto (ex.: `"1E+1"`),
`quality`, `reason`, `provenance`, versão de regra, datas e hashes de recibo.

Exemplos de consulta local (em outro terminal):

```sh
curl http://127.0.0.1:8765/api/v1/demo/health
curl http://127.0.0.1:8765/api/v1/demo/scenarios/complete
curl http://127.0.0.1:8765/api/v1/demo/comparison
```

## Política de segurança do recorte

- Respostas HTTP apenas para métodos GET e hosts `127.0.0.1`,
  `localhost` e `testserver` de testes. Isso **não** é autenticação.
- Identificadores fora de `complete/expensive/incomplete` retornam 404.
  Nenhum parâmetro de query é aceito, mesmo se aparentemente inofensivo.
- A API não ativa CORS para sites de terceiros e não disponibiliza
  dados reais, tokens, perfis ou gravações.
- `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `X-Robots-Tag: noindex`,
  `Referrer-Policy: no-referrer` também devem cobrir erros.
- Dados vêm de fixtures rígidas e passam por validação Pydantic
  `extra=forbid`; quality `present` requer string Decimal, e
  valores ausentes continuam `null`, jamais `0` ou `FAIL`.
- A camada interna usa SQLite em memória para cada relatório.
  Sem banco multiusuário, sem armazenamento permanente e sem senhas.
- Os dados não são disponibilizados para uso comercial, negociação,
  análise de portfólio real ou redistribuição de provedores.

## Testes e evolução

```sh
uv run --offline --locked pytest -q
uv run --offline --locked ruff check .
uv run --offline --locked ruff format --check .
```

Os testes `backend/tests/test_demo_api.py` usam `TestClient` in-process,
sem rede externa e sem servidor público; verificam contratos, status,
OpenAPI, coerência de qualidade, horários, hash de proveniência,
405/404, hosts rejeitados, CORS, cabeçalhos e exportação fiel.

A API **ainda não está ligada** à UI do PR #24. Essa integração deve
ser separada após revisão da interface, incluindo política explícita de
origens CORS se existir frontend em host/porta diferente. Para
API com contas de verdade: primeiro NV-016 login/autorização por usuário e
tenant, permissões de dados, segredos e TLS/infra apropriados.

Consulte [ADR-0009](adr/ADR-0009-versioned-synthetic-demo-api.md) e
[issue GitHub NV-014 #25](https://github.com/egonschneider08-sketch/novera/issues/25).
