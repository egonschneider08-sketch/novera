# NV-024 — Primeira jornada de pesquisa sintética

**Estado:** proposta de produto implementada em Python offline; não é uma interface web
nem uma consulta de mercado. [Issue #19](https://github.com/egonschneider08-sketch/novera/issues/19).

## O usuário consegue fazer

1. Escolher um cenário fictício (complete, expensive ou incomplete).
2. Visualizar um ativo de laboratório, referência temporal fixa e base por ação.
3. Recuperar de um SQLite em memória observações com Decimal, fonte, datas, valores,
   qualidade, versões e recibos.
4. Ver Graham (número didático) e Bazin (teto didático), com todos os critérios,
   razões, métricas, dados ausentes e estado agregado PASS, FAIL ou UNKNOWN.
5. Exportar **somente dados sintéticos** em JSON legível e determinístico, sem
   conversões financeiras em float, ou usar a visualização textual em português.

### Execute sem rede (depois de instalar o ambiente)

```sh
uv run --offline --locked python -m novera.research_demo --scenario complete --format text
uv run --offline --locked python -m novera.research_demo --scenario expensive --format text
uv run --offline --locked python -m novera.research_demo --scenario incomplete --format json
```

Não há necessidade de token, SQLite persistente ou credenciais. São usados
somente valores codificados como *fixtures fictícias*; nenhum dado oficial da B3
ou de provedores comerciais entra na jornada. O cenário é fixado no dia
**28/10/2026**, com datas de publicação sintéticas anteriores à data de avaliação.

## Como o exemplo é construído

```text
Cenário (fonte novera-synthetic-fixture)
    ↓ Observations imutáveis: preço, EPS, BVPS, pagamentos
SQLite memory — ObservationStore (escopo novera-demo/synthetic-only)
    ↓ Leitura por queries financeiras, verificação de registros
PerShareInput + DividendHistory (convenções manuais declaradas)
    ↓ Funções puras novera.strategies
Graham + Bazin → StrategyResult
    ↓ Renderizadores offline
Texto PT-BR ou JSON de demonstração
```

No cenário completo, a fixture declara **expressamente** que os cinco
intervalos de 365 dias de proventos estão cobertos; isso é uma premissa
fabricada para testes, **não uma certificação de dados de mercado**.
No cenário incompleto, o EPS está marcado como MISSING e a cobertura dos
proventos é incompleta: os critérios dependentes devem ficar UNKNOWN, nunca
ser interpretados como reprovação ou zero. O cenário de preço elevado possui
evidências sintéticas suficientes para apontar critérios FAIL.

### Contratos e metodologia

- Ativos são IDs do laboratório (LAB-A/LAB-B/LAB-C), sem ticker B3 real.
- Preço é `close` fictício com `adjustment=unadjusted`. Isso não efetua
  ajuste de ações, dividendos ou desdobramentos reais.
- EPS é anual (2025), BVPS refere-se ao fechamento do exercício (2025).
  A publicação e a coleta são datas **artificiais** e explícitas; não
  representam demonstrações CVM ou liquidez real.
- Proventos são cinco pagamentos inventados com basis `gross`; ID e data
  de cada pagamento são rastreáveis no SQLite e no JSON.
- Data/base e fonte são documentadas no resultado; todas as operações usam
  Decimal. O JSON serializa números financeiros como *strings* ou null.
- Seleção de versão do SQLite é limitada aos dados acabados de semear;
  isso não estabelece regra geral de latest/as-of para histórico real.

### Separação da infraestrutura de dados reais

A brapi disponibiliza `regular_market_price` com `adjustment=provider_unspecified`,
que **não deve ser renomeado para `close` ajustado**. O SGS 432 fornece
Selic-meta anual, e não EPS, BVPS ou cinco anos de proventos.
Por isso, esta jornada **não usa o FinancialPipeline** para inventar esses
campos; usa fixtures explícitas e exercícios de leitura do ObservationStore.
Os adaptadores e o pipeline seguem em código, testados separadamente, e não
estão liberados para publicar dados de terceiros.

## Limitações e riscos

- Não é plataforma de negociação nem backtest.
- Sem tratamento de universo histórico, ações deslistadas, ajustes de base por
  ação, licença de distribuição de dados, suporte multiusuário, calendário B3,
  precificação em tempo real ou time machine.
- Resultados PASS/FAIL/UNKNOWN qualificam critérios didáticos, **não a empresa**
  nem decisão de compra.
- O escopo do armazenamento é de laboratório e fica em memória. Rodadas não
  geram banco em disco, cache em rede, saída por HTTP, arquivos de carteiras
  ou exportação a terceiros.
- O esquema JSON é de demonstração `novera-synthetic-research-v1`; um contrato
  público de API exigirá revisão e versionamento próprios.

## Validação e progresso

Testes em `backend/tests/test_research_demo.py`: cenários positivo/negativo/
incompleto, fixture reingestada sem duplicação, qualidade e proveniência,
saída JSON e texto, argumentos inválidos, ordem dos recibos e bloqueio de
tentativa de socket durante a jornada.

Execute os testes e gates em branch própria antes de integrar:

```sh
uv run --offline --locked ruff check .
uv run --offline --locked ruff format --check .
uv run --offline --locked pytest -q
```

O scanner e a auditoria da CI oficial são requisitos adicionais.
A primeira interface web (**NV-011**) será discutida depois desta entrega
ser aprovada, sem adicionar front/backend novos aqui.

## Definition of Done

- [ ] CI completa verde no commit final, com logs reais anexados ao PR.
- [ ] Três cenários didáticos e demonstração completa no terminal.
- [ ] Pass/Fail/Unknown e evidências sintéticas com motivo.
- [ ] CLI e JSON sem rede ou arquivos reais.
- [ ] Revisão técnica e produto antes de merge; atualizar Notion com evidência.
