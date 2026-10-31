# Documentacao Novera

- [Protocolo de engenharia](engineering-workflow.md): branches, commits, PRs e evidencias.
- [Fundacao do backend](../backend/README.md): limites modulares e layout.
- [Preparacao local](../README.md): instalacao e validacao reproduziveis.

Decisoes significativas futuras devem usar `docs/adr/ADR-XXXX-short-title.md`
conforme o protocolo. Evidencias de aceitacao ficam nos PRs do GitHub.

- [Contratos financeiros](financial-contracts.md): estados e proveniencia (NV-004).

- [Migracao Winning Investments v2](migrations/winning-investments-v2.md): inventario, direitos, heuristicas e proximas etapas.

- [Heuristicas puras](strategies.md): interfaces e exemplo sintetico NV-002.

- [Cliente HTTP seguro](http-client.md): GET, cache por acesso, freshness e limites.

- [Adaptador brapi v2](brapi-adapter.md): cotacao de um ativo, metadados e limites oficiais.

- [Adaptador BCB SGS 432](bcb-adapter.md): meta Selic, unidade anual, datas e lacunas.

- [Armazenamento financeiro local](storage.md): idempotencia, versoes, segregacao e limites (NV-009).

- [Pipeline financeiro](pipeline.md): execução opt-in, lote atômico de brapi/BCB e limites de acesso.

- [Pesquisa sintética demonstrável](research-demo.md): casos PASS/FAIL/UNKNOWN, CLI, JSON e limites da experiência (NV-024).

- [Comparação e exportação sintéticas](research-compare.md): estados por metodologia e JSON/CSV auditáveis, sem ranking (NV-010 fase inicial).

- [Interface web sintética React](../frontend/README.md): UX LAB-A/B/C, metodologia, proveniência, estados vazio/erro/stale e exportações (NV-011).

- [ADR-0008](adr/ADR-0008-react-synthetic-research-ui.md): fronteira de dados, build reproduzível e justificativa da primeira interface.

- [API FastAPI de laboratório](demo-api.md): endpoints v1 de cenários fictícios, contratos e controles locais (NV-014).
- [ADR-0009](adr/ADR-0009-versioned-synthetic-demo-api.md): decisão de FastAPI, validações e limites de segurança.

- [Política RBAC por tenant](authorization.md): Viewer, Analyst, Owner e autorização fail-closed, ainda sem login (NV-016 recorte 1).
- [ADR-0010](adr/ADR-0010-tenant-rbac-policy.md): matrizes de permissões, fronteiras e direitos de dados.

- [Laboratório full stack local](local-lab.md): um único servidor React + FastAPI com dados fictícios, execução PowerShell e modos API/snapshot (NV-025).
