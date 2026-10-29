# Novera

Plataforma de pesquisa de investimentos em fase de fundacao (Sprint 0).
O estado atual oferece um pacote Python instalavel e um teste de importacao;
nao fornece cotacoes, API, interface ou algoritmos financeiros validados.

## Requisitos

- Git e Python **3.12** (validado com 3.12.10).
- uv **0.11.27**, versao usada na validacao. Instalacao: https://docs.astral.sh/uv/getting-started/installation/
- Rede para o clone e a primeira instalacao de dependencias publicas.
- Nenhuma credencial de fornecedor, banco de dados ou Node.js e necessario.

## Clone e ambiente

Em PowerShell, Linux ou macOS, partindo do diretorio pai:

```sh
git clone https://github.com/egonschneider08-sketch/novera.git
cd novera
uv sync --locked --group dev
uv run --locked python -c "import novera; print(novera.__name__)"
uv run --locked pytest -q
```

Enquanto o PR da NV-001 estiver em revisao, depois de clonar e antes do sync:

```sh
git switch --track origin/feature/NV-001-monorepo-foundation
```

`uv sync` cria `.venv`, instala o pacote local em modo editavel e usa as versoes
registradas em `uv.lock`. Nao e necessario ativar o ambiente. O resultado
esperado do import e `novera`; a suite inicial deve reportar `1 passed`.
Depois do sync, os testes podem rodar sem rede:

```sh
uv run --offline --locked pytest -q
```

A suite atual verifica apenas a fundacao: importacao do pacote instalado fora
do checkout, com acesso por socket bloqueado. Testes financeiros e mocks de
fornecedores pertencem as proximas issues. Lint, tipagem e CI ainda nao estao
configurados; serao tratados em NV-003/NV-012.

## Estrutura

```text
backend/
  src/novera/       # pacote Python; modulos de dominio surgirao com codigo real
  tests/           # teste basico de instalacao/importacao
frontend/          # placeholder documentado
docs/              # engenharia e documentacao
.github/workflows/ # placeholder; CI funcional sera implementada na NV-012
pyproject.toml     # metadados, build e dependencias
uv.lock            # resolucao versionada das dependencias
```

## Dados e segredos

Nao versione credenciais, tokens ou dados de fornecedores. `.gitignore` exclui
`.env*` (exceto `.env.example`), chaves privadas, arquivos locais de credenciais,
ambientes virtuais, caches e diretorios locais `data/`, `cache/`, `artifacts/`,
alem de Parquet, DuckDB e SQLite. Novos formatos devem receber regras antes
da inclusao de dados. `.env.example`, se criado, deve conter apenas placeholders.

## Processo

Leia [AGENTS.md](AGENTS.md) e o [protocolo de engenharia](docs/engineering-workflow.md).
Use uma issue por branch/PR e Conventional Commits. Enquanto `develop` nao
existir, PRs iniciais de fundacao usam `main`. Merge exige aceite humano.

NV-001 estabelece apenas a estrutura. NV-004 define contratos e proveniencia;
NV-002 extrai o codigo de referencia; NV-003 amplia ambiente e testes;
NV-012 implementa CI e verificacoes de seguranca.
