# NV-003: cobertura incremental e bloqueios

Base dependente: NV-004, que depende do PR #7/NV-001. Nao integrar fora de ordem.

```sh
uv sync --locked --group dev
uv run --offline --locked pytest -q
```

Cobertura: estados de dados, zero/negativos, Decimal nao finito, tipos invalidos,
cronologia com fusos distintos, ausencia de data de publicacao, imutabilidade,
identidade de ativos e revisoes. Fixtures sinteticas; sem tokens ou dados reais.
Mocks de socket/getaddrinfo verificam que construir os contratos nao usa essas
entradas Python. Nao garantem ausencia de todo I/O de rede.

## Itens bloqueados

NV-002 nao pode ser executada sem o codigo Winning Investments v2 e evidencia
de licenca/permissao de reutilizacao. A busca local cobriu a pasta de projetos
ChatGPT, anexos de codigo/notebooks e a arvore Git. A pagina de contexto Notion
04 Motor Financeiro e Dados descreve formulas, mas nao fornece codigo/licenca.
Nao se presume inexistencia fora desses locais.

Sem implementacao financeira ou adapter HTTP, nao existem alvos reais para testar
calculos, timeout, HTTP 429 ou falhas parciais. Nao foram criadas implementacoes
ficticias nem testes que validam mocks sem exercitar codigo de producao.
NV-003 permanece parcial e bloqueada nesses criterios. NV-012 pode iniciar a
infraestrutura de CI sobre os testes existentes, sem declarar Sprint 0 concluida.


## Atualizacao NV-002 (29/10/2026)

O bloqueio de disponibilidade descrito acima registra o estado anterior.
A referencia agora foi recebida e auditada com hash verificado; autoria declarada,
mas republicacao literal ainda depende de autorizacao especifica de licenciamento.
A NV-002 implementa independentemente heuristicas puras com testes sinteticos,
sem copiar fonte. Veja docs/migrations/winning-investments-v2.md e docs/strategies.md.
Testes de calculo/contratos foram ampliados; timeout, HTTP 429 e falhas parciais
continuam pendentes do futuro cliente/adapters, depois de revisao do dominio.
