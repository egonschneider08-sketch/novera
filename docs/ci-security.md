# NV-012: CI e seguranca inicial

Base dependente de NV-003 (parcial), NV-004 e NV-001. Nao integrar fora de ordem.
Workflow quality.yml: pull_request sem filtro de base, push nas branches de
trabalho/main e workflow_dispatch. Sem pull_request_target, deploy, tokens de
provedores, permissoes de escrita ou credenciais persistidas no checkout.
Actions fixadas por SHA de tags consultadas via git ls-remote.

## Comandos reproduziveis

```sh
uv sync --locked --group dev
uv run --offline --locked ruff check .
uv run --offline --locked ruff format --check .
uv run --offline --locked pytest -q
uv run --offline --locked python scripts/check_secrets.py --self-test
uv run --offline --locked python scripts/check_secrets.py
uv export --locked --all-groups --no-emit-project --no-hashes --output-file requirements-audit.txt
uv run --locked pip-audit --no-deps --disable-pip --progress-spinner off -r requirements-audit.txt
```

O ultimo comando exige acesso ao servico publico de advisories. O workflow usa
/tmp/novera-requirements.txt para nao criar exportacao no checkout. Sync exige
indice de pacotes. Testes, lint e scanner executam offline apos sync;
uv --offline nao constitui isolamento universal de rede para codigo Python.

## Varredura

O wrapper de detect-secrets 1.5.0 enumera arquivos versionados por git ls-files,
usa detectores locais via API scan_file e falha se houver achados. Exibe apenas
contagem, nunca valores, hashes ou conteudo. Nao verifica credenciais por rede.
Falha em arquivos ilegíveis, symlinks e lista vazia. Nao varre historico Git,
segredos em arquivos ignorados ou servicos externos; heuristicas nao garantem
ausencia de segredos. Filtros padrao podem ignorar hashes de lockfiles.
O controle negativo usa apenas cabecalho sintetico, nunca uma chave real.

## Falhas encontradas e correcoes

- Auditoria inicial: pytest 8.4.2, PYSEC-2026-1845, correcao indicada >=9.0.3.
  Atualizacao e lock resolveram pytest 9.2.0; auditoria repetida sem
  vulnerabilidades conhecidas. Nenhuma excecao de advisory adicionada.
- Controle negativo inicial do CLI detect-secrets retornou zero indevidamente
  no Windows. Inspecao mostrou enumeracao vazia de arquivos, inclusive para
  fixture explicita. git ls-files + API scan_file removeu essa enumeracao;
  controle passou detectando um achado sintetico.
- Ruff corrigiu quatro problemas de imports e formatou tres arquivos de
  contratos/testes. Sem alteracao de comportamento; suite repetida.
- Primeiro controle de falha deliberada do pytest apontou arquivo temporario
  fora de um projeto isolado e encontrou diretorio alheio inacessivel no Temp.
  Reexecucao com rootdir/confcutdir em diretorio temporario proprio exercitou
  o assert False esperado, com exit 1. Nenhum arquivo de falha foi versionado.

## Limites e revisao

Auditoria inclui dependencias publicadas de runtime/dev exportadas pelo uv,
nao audita pacote local nem ambiente isolado de build do hatchling.
Checks nao viram protecao obrigatoria de branches automaticamente.
NV-003 continua parcial (codigo/licenca de referencia ausentes); nao se declara
NV-012 concluida antes dos criterios remanescentes serem aceitos.
Resultados locais e GitHub Actions devem ser distinguidos no PR.
