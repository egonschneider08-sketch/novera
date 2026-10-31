# Novera Lab — frontend sintético NV-011

React + TypeScript + Vite. Primeira interface responsiva para analisar
**exclusivamente três cenários fictícios**: LAB-A (PASS), LAB-B (FAIL)
e LAB-C (UNKNOWN). Não é uma plataforma de mercado em tempo real,
não requer senha ou API e não gera recomendação de investimento.

## Executar na sua máquina

Requisitos: Node.js >= 22.12, npm compatível com o lockfile,
Python 3.12 e uv 0.11.27 para verificar a origem dos dados.

```sh
# A partir da raiz do repositório:
uv sync --locked --group dev
uv run --offline --locked python frontend/scripts/materialize_demo.py --check

cd frontend
npm ci --ignore-scripts
npm run dev
```

Abra o endereço local apresentado pelo Vite. As dependências são instaladas
uma vez; depois disso, o aplicativo usa apenas os arquivos estáticos do build.
Não há requisição a cotação, dados de terceiros nem backend HTTP.

## Testes e build

```sh
cd frontend
npm run build
npm run test
npm audit --audit-level=high
```

O GitHub Actions deve executar esses gates junto ao check determinístico
das fixtures. Não confundir sucesso no build com autorização para publicar
dados financeiros reais.

## Garantias da origem dos números

Os arquivos `src/data/scenarios.json` e `src/data/comparison.csv` são
produzidos por `scripts/materialize_demo.py` usando o **backend Python**
existente (`novera.research_compare`, SQLite em memória, Bazin e Graham).
O navegador não recalcula estratégias, nem faz arredondamento em `Number`.
Decimal é texto, inclusive quando o Python usa notação científica.
O check de CI compara os artefatos versionados aos gerados pelo backend.

Em caso de mudança nas regras Python, regenere explicitamente na raiz:

```sh
uv run --offline --locked python frontend/scripts/materialize_demo.py --write
```

Revise o diff de JSON e CSV e nunca substitua esse material por
resultados de brapi, BCB ou empresas reais sem um novo projeto de
autorização, licenciamento e isolamento de usuários.

## Jornada de pesquisa

Escolha entre LAB-A/B/C. Alterne Graham/Bazin pelo teclado ou mouse,
leia as justificativas por critério, qualidade, períodos e proveniência,
e exporte somente dados fictícios. O menu lateral simula estados vazio,
erro ou stale; stale é claramente rotulado e bloqueia downloads.
Abaixo de 760px a navegação se adapta ao celular.

## Fora do escopo

API pública, login, assinaturas, painel de clientes, séries B3, carregamento
de fornecedor, alertas e recomendações. O hash de recibo é uma trilha de
integridade local, não uma assinatura criptográfica verificável externamente.

Arquitetura: [ADR-0008](../docs/adr/ADR-0008-react-synthetic-research-ui.md).
Roteiro completo: [issue NV-011 #23](https://github.com/egonschneider08-sketch/novera/issues/23).
