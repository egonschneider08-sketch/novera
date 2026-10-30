# ADR-0009 — API versionada FastAPI somente para pesquisa sintética

**Status:** proposta em revisão, NV-014 recorte 1 — 30/10/2026. Dependências: NV-004, NV-009, NV-024, NV-010 (fase sintética).

## Contexto

O Novera possui um domínio financeiro Python com Bazin/Graham, contratos
Observation/Provenance, armazenamento SQLite e relatórios fictícios. Uma
interface React também está preparada no [PR #24](https://github.com/egonschneider08-sketch/novera/pull/24),
mas não integrada à main: ela consome snapshots JSON/CSV gerados pelo Python.

A próxima fronteira técnica é uma API HTTP versionada, verificável e previsível
para a jornada de laboratório. Ainda faltam autenticação e autorização
multiusuário (NV-016), governança de dados de provedores, CORS de produção,
segurança de deploy, observabilidade e calendário/point-in-time.

## Decisão

Adotar FastAPI e Uvicorn com versões fixas em `pyproject.toml` e `uv.lock`.
Criar `novera.demo_api` expondo **somente GET** sob `/api/v1/demo/`:

| Rota | Resposta |
|---|---|
| GET `/api/v1/demo/health` | Saúde do laboratório local; não saúde de provedores |
| GET `/api/v1/demo/scenarios` | Allowlist LAB-A/B/C, sem cotação |
| GET `/api/v1/demo/scenarios/{scenario}` | Objeto `report_json(run_scenario(...))` |
| GET `/api/v1/demo/comparison` | `comparison_json(compare_scenarios())` |
| GET `/api/v1/demo/comparison.csv` | CSV Python sintético |
| GET `/api/v1/openapi.json` | Contratos versionados; documentação Swagger/ReDoc desativada |

Respostas JSON são validadas contra modelos Pydantic estritos com schema
`extra=forbid`, flags `synthetic=true`, origem
`novera-synthetic-fixture`, recibos hex SHA256 e campo financeiro como texto
Decimal (incluindo expoentes). Qualidade `present` exige valor; qualquer
outro estado exige `null`. Contratos são formatadores de domínio, não
algoritmos de análise duplicados: todas as fórmulas continuam no Python
existente. Não há leitura direta do arquivo SQLite de clientes nem do
FinancialPipeline em nenhuma rota HTTP.

### Controle operacional

- O comando local `python -m novera.demo_api` inicia Uvicorn em
  **127.0.0.1:8765** sem permitir parâmetro host. Isso não impede que
  outra aplicação importe `app` e o exponha incorretamente; operar
  exclusivamente como laboratório.
- Host HTTP admitido: `localhost`, `127.0.0.1` ou `testserver` de teste.
  Sem CORS liberado; clientes de origem diferente não ganham permissão por
  esta API. Header Host não é autenticação.
- Dados retornam com `Cache-Control: no-store`,
  `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer` e `X-Robots-Tag: noindex`.
- Parâmetros de query não previstos são rejeitados em vez de ignorados.
  Identificadores fora da allowlist devolvem 404 sem consultar provedores.
  Escritas HTTP devolvem 405.
- A presença de OpenAPI não é uma garantia de proteção de API. A UI do PR #24
  permanece independente, sem ligação automática a essa API.

## Alternativas consideradas

- Flask: era uma opção para outro MVP, mas o backlog Novera definiu
  NV-014 **FastAPI versionada** e sua tipagem automática OpenAPI é útil aqui.
- Serviço WSGI próprio em `http.server`: sem dependência nova, mas
  acrescentaria trabalho manual de contratos/segurança e possível adoção
  indevida em produção.
- Interligar imediatamente frontend e API: elevaria a complexidade de CORS,
  endereçamento, versão e estados antes de finalizar o PR de UX.
- Endpoints brapi e BCB reais: bloqueados por direitos e validação
  operacional; nunca expor o adaptador interno como proxy público.

## Testes e invariantes

ASGI TestClient com transporte in-process e sem sockets. Cobertura de
cenários PASS/FAIL/UNKNOWN, identidade e proveniência, Decimal textual,
zero ≠ missing, consistência Pydantic (incluindo falhas de schema),
OpenAPI, 404, 405, rejeição de query, proteção de host e cabeçalhos.
Os payloads HTTP devem ser idênticos aos resultados do Python existente;
as rotas jamais criam usuários, bancos persistentes, tokens ou chamadas de rede.

## Limitações, aceitação e rollback

**Não é um servidor de produção**. Falta proteção por usuário, autenticação,
autorização por tenant/entitlement, limite distribuído de requisições,
CSRF quando houver cookies, CORS confiável da UI, observabilidade,
rate-limiting de ingresso, TLS externo, política de dados ao vivo e
segredos gerenciados. NV-016 e a integração da UI com a API são futuros PRs.

Rollback: remover `demo_api.py`, seus testes, pins FastAPI/Uvicorn,
recriar o lockfile e reverter documentação, sem migração de banco.
Esse incremento não modifica os adaptadores, nem o schema SQLite, nem o
frontend e não libera uso comercial de dados de terceiros.

[GitHub issue NV-014 #25](https://github.com/egonschneider08-sketch/novera/issues/25).
