# Novera

Plataforma de pesquisa de investimentos em fase de fundacao (Sprint 0/1).
O backend inclui contratos e heuristicas puras Bazin/Graham, cliente HTTP,
adaptadores de brapi/BCB, armazenamento SQLite e pipeline de ingestao controlada.
Uma primeira jornada de pesquisa **totalmente sintetica e offline** pode ser
executada no terminal. O projeto ainda nao fornece API, frontend ou servico
comercial com cotacoes reais, recomendacoes ou metodologias validadas em mercado.
A versao `0.1.0` identifica somente o pacote inicial; nao representa uma
release do produto nem validacao para uso em producao.

## Requisitos

- Git e Python **3.12** (validado com 3.12.10).
- uv **0.11.27**, versao usada na validacao. Instalacao: https://docs.astral.sh/uv/getting-started/installation/
- Rede para o clone e a primeira instalacao de dependencias publicas.
- Nenhuma credencial de fornecedor, banco de dados ou Node.js e necessario.

## Clone e ambiente

Em PowerShell, Linux ou macOS, partindo de um diretorio pai onde
`novera` ainda nao exista:

```sh
git clone --branch main https://github.com/egonschneider08-sketch/novera.git novera
cd novera
uv sync --locked --group dev
uv run --locked python -c "import novera; print(novera.__name__)"
uv run --locked pytest -q
```

Para testar uma branch de funcionalidade antes do merge, use o nome da
branch no clone em uma pasta separada, sem sobrescrever arquivos locais.
Dependencias podem ser reutilizadas do cache global do uv.

`uv sync` cria `.venv`, instala o pacote local em modo editavel e usa as versoes
registradas em `uv.lock`. Nao e necessario ativar o ambiente. O resultado
esperado do import e `novera`; a suite deve passar; a contagem cresce com os contratos da NV-004.
Depois do sync, os testes podem rodar sem rede:

```sh
uv run --offline --locked pytest -q
```

A suite cobre contratos, heuristicas sinteticas e importacao do pacote instalado fora
do checkout, em modo Python isolado (`-I`). No subprocesso, o teste substitui
`socket.socket` antes de importar `novera`, detectando tentativas de criar
sockets por essa chamada Python. Isso e uma verificacao parcial: nao bloqueia
DNS por outras funcoes, extensoes nativas, processos externos ou outros meios
de I/O de rede. Nao constitui isolamento de rede do sistema operacional nem
garantia universal de ausencia de I/O. `uv --offline` impede acesso de rede
pelo uv, nao pelo codigo executado. Os testes nao validam provedores ou performance de investimento.
Lint, formato e CI inicial estao integrados; tipagem estatica
nao esta configurada. Veja [CI e seguranca](docs/ci-security.md).

## Primeira jornada de pesquisa (100% ficticia)

Explore tres cenarios didaticos sem credenciais, sem arquivos persistentes
e sem chamada de rede. O exemplo percorre contratos, armazenamento SQLite
em memoria, consultas e calculos Graham/Bazin, mostrando evidencias e
condicoes PASS, FAIL e UNKNOWN.

```sh
uv run --offline --locked python -m novera.research_demo --scenario complete --format text
uv run --offline --locked python -m novera.research_demo --scenario expensive --format text
uv run --offline --locked python -m novera.research_demo --scenario incomplete --format json
```

Este laboratorio **nao** utiliza cotacoes B3 nem pode ser interpretado como
uma recomendacao. Detalhes: [guia da pesquisa sintetica](docs/research-demo.md).

## Estrutura

```text
backend/
  src/novera/       # pacote Python; modulos de dominio surgirao com codigo real
  tests/           # contratos, dominio sintetico e importacao
frontend/          # placeholder documentado
docs/              # engenharia e documentacao
.github/workflows/ # checks de qualidade e seguranca
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

Contratos internos e limitacoes: [NV-004](docs/financial-contracts.md).

Auditoria, formulas e limites da migracao: [Winning Investments v2](docs/migrations/winning-investments-v2.md).

Cliente HTTP GET, politicas e exemplo offline: [HTTP seguro](docs/http-client.md).

Primeiro adaptador de cotacao, validado somente com dados sinteticos:
[brapi v2](docs/brapi-adapter.md). Sem coleta automatica ou credenciais no ambiente de testes.

Serie economica inicial, conversao Decimal e testes offline:
[BCB SGS 432](docs/bcb-adapter.md).
