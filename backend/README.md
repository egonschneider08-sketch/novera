# Backend

Monolito modular Python com layout `src`: pacote instalavel em `src/novera/`
e testes em `tests/`. Execute os comandos do README da raiz a partir da raiz.

Limites logicos previstos: `market_data`, `fundamentals`, `analytics`,
`strategies`, `storage` e `api`. Os pacotes fisicos serao criados quando houver
codigo que justifique cada limite. Calculos de dominio nao devem ficar
restritos a notebooks ou handlers HTTP.

Esta fundacao nao oferece API, integracao de dados, banco ou regras financeiras.
A extracao do Winning Investments v2 pertence a NV-002, alinhada a NV-004.
