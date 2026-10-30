# ADR-0008 — React/Vite para a interface de pesquisa sintética

**Estado:** proposto, NV-011 / GitHub issue #23. **Data:** 2026-10-30.

## Contexto

O Novera já tem NV-024 (jornada Bazin/Graham do SQLite em memória) e a fase
sintética NV-010 (comparação e exportação auditável em JSON/CSV). Ainda não há
API pública, autenticação nem licença de redistribuição de cotações brapi.
Uma primeira interface responsiva deve testar o entendimento do produto sem
misturar valores reais, implantar permissões falsas nem recalcular métricas.

## Decisão

Implementar um frontend **React + TypeScript + Vite** isolado em `frontend/`,
com lockfile npm versionado, build estático, testes Vitest + Testing Library e
CI independente. Não há router, backend HTTP, dependência visual externa ou CDN.

**Fonte de verdade é Python:** `frontend/scripts/materialize_demo.py` importa
`novera.research_compare`, gera `src/data/scenarios.json` e
`src/data/comparison.csv` a partir do SQLite/strategies, deterministicamente.
Ambos ficam versionados. A CI valida bit a bit que esses arquivos correspondem
ao Python. Não existe reimplementação Bazin/Graham em JavaScript.

**Barreira de confiança:** a interface só renderiza dados que passam na
verificação do schema `novera-synthetic-comparison-v1`, dos 3 cenários LAB,
dos estados PASS/FAIL/UNKNOWN, dos recibos, dos `Decimal` textuais e do rótulo
`synthetic=true`. Valores desconhecidos e dados reais são recusados.
Notação científica de Decimal é expandida como texto, nunca como `Number` do
valor financeiro.

**Estados de UX:** demo, vazio, erro de carregamento e stale simulado são
distintos e textuais; stale não é confundido com coleta recente e bloqueia
download. O seletor é visivelmente de simulação. A visão de evidências mantém
proveniência, data, versão e hash de recibo; a navegação por abas também aceita
teclado. Desktop e mobile usam o mesmo conjunto de dados.

**Exportações:** JSON contém apenas o cenário sintético escolhido; CSV contém
os 3 cenários gerados pelo Python. Os downloads são ações explícitas, sem
upload, telemetria, conexão financeira ou coleta automática.

## Alternativas e consequências

- Streamlit permitiria prototipagem rápida, mas a arquitetura alvo do produto
  é React/TypeScript. Melhor não introduzir dois frontends permanentes.
- Construir FastAPI antes de UX real adicionaria autenticação/licenciamento
  prematuros e superfícies de ataque. A futura NV-014 define um contrato HTTP
  separado, com autenticação e validações próprias.
- Copiar resultados financeiros para TypeScript ou escrever novas fórmulas
  produziria divergência entre backend e frontend. O artefato estático
  versionado e a verificação na CI tornam esse risco revisável.

O build não equivale a uma plataforma multiusuário, não tem atualizações live,
nem prova a disponibilidade histórica de dados. Os registros são inteiramente
fictícios e os provedores externos não são consultados. Nenhum status de
critério constitui recomendação de investimento. O frontend não deve ser
exposto como serviço real de análise antes de NV-014/NV-016 e revisão de dados.

## Segurança, teste e rollback

- Dependências npm com versões explícitas e lockfile gerado no Actions.
- `npm ci`, `npm run build`, `npm run test`, auditoria npm de produção e
  check determinístico do Python em CI.
- Sem tokens no bundle, `fetch()` para provedor, link de mercado ou import
  de datasets externos. URL de documentação abre apenas GitHub.
- Revisão de a11y inclui foco, labels, estados textuais e responsividade;
  uma auditoria completa WCAG e testes em dispositivos reais são futuros.
- Rollback: reverter `frontend/`, workflow frontend e ADR, sem alterações
  no schema SQLite, no backend financeiro ou em credenciais.

**Evidência:** issue
https://github.com/egonschneider08-sketch/novera/issues/23
e PR de implementação NV-011.
