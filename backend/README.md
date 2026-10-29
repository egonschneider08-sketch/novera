# Backend

Monolito modular Python com layout `src`: pacote instalavel em `src/novera/`
e testes em `tests/`. Execute os comandos do README da raiz a partir da raiz.

Limites logicos previstos: `market_data`, `fundamentals`, `analytics`,
`strategies`, `storage` e `api`. Os pacotes fisicos serao criados quando houver
codigo que justifique cada limite. Calculos de dominio nao devem ficar
restritos a notebooks ou handlers HTTP.

O backend nao oferece API, integracao de dados, banco ou estrategia financeira
completa. `novera.strategies` oferece somente as heuristicas puras documentadas
na [auditoria NV-002](../docs/migrations/winning-investments-v2.md), alinhadas
aos contratos da NV-004.
