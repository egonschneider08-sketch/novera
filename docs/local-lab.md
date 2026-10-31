# NV-025 — Novera Lab: React + FastAPI em um único servidor local

Esta é a **primeira experiência full stack executável do Novera**. O frontend
React/TypeScript recebe dados da API FastAPI por uma **mesma origem local**,
sem CORS, contas de usuário ou provedores de mercado. O laboratório mantém
os três cenários fictícios LAB-A/B/C e deixa a análise financeira em Python.

## No Windows (PowerShell)

A partir da pasta onde você já executou os 418 testes:

```powershell
cd C:\Users\Schneider\Documents\novera
git status --short
git fetch origin
git switch feature/NV-025-local-fullstack-lab
uv sync --locked --group dev
cd frontend
npm ci --ignore-scripts
npm run build
cd ..
uv run --offline --locked python -m novera.local_lab
```

**Use `git switch` somente se o repositório não tiver alterações locais
que você queira preservar**. Uma opção mais segura é clonar a branch em
outra pasta, como mostrado no README principal. O procedimento final na
`main` trocará `git switch` por `git pull --ff-only` quando o PR for
integrado. Essa primeira execução instala as dependências do Node e Python
pelo npm/uv; depois os comandos offline de Python funcionam sem rede.

Ou, se preferir um único comando (após instalar Git, Node.js e uv):

```powershell
.\scripts\start-local-lab.cmd
```

O arquivo `.cmd` sincroniza dependências travadas, verifica as fixtures,
compila o frontend e inicia a aplicação sem mudar de branch nem usar
`cd novera-api`. Não é um serviço Windows nem inicia sozinho ao ligar o PC.

## Onde acessar

| Endereço | Descrição |
|---|---|
| http://127.0.0.1:8765/ | Interface React responsiva, servido pelo FastAPI |
| http://127.0.0.1:8765/api/v1/demo/health | Estado do laboratório |
| http://127.0.0.1:8765/api/v1/demo/scenarios | Catálogo LAB-A/B/C |
| http://127.0.0.1:8765/api/v1/demo/comparison | Relatórios completos em JSON |
| http://127.0.0.1:8765/api/v1/demo/comparison.csv | CSV fictício |

A interface inicia no modo **Dados incorporados**, sem requisição HTTP. Use
o seletor de origem de dados e escolha **API local** para consumir realmente
`GET /api/v1/demo/comparison` no mesmo domínio/porta. Você verá a indicação
de conexão e poderá navegar entre ativos LAB-A/B/C. Quando a resposta falhar,
o app não apresenta valores incorporados como se fossem atualizados: exibe
um erro e permite tentar novamente ou voltar manualmente ao snapshot.

**CSV**: no modo API, a exportação CSV do snapshot fica bloqueada para
não confundir um arquivo incorporado com a resposta HTTP. O endpoint CSV
da API continua acessível diretamente no endereço listado acima.
No modo incorporado, JSON e CSV permanecem disponíveis com disclaimers.
A saída JSON na tela API contém o cenário retornado pelo servidor.

## Arquitetura

```text
Browser — http://127.0.0.1:8765/
    │
    ├─ GET /                     → StaticFiles(React/Vite frontend/dist)
    ├─ GET /assets/...            → JavaScript + CSS compilados
    └─ GET /api/v1/demo/comparison→ FastAPI Pydantic
                                       │
                                       └→ novera.research_compare
                                               │
                                               ├→ ObservationStore.memory
                                               └→ Bazin/Graham (Python)
```

`python -m novera.local_lab` falha explicitamente se `frontend/dist/index.html`
não existir. Nenhum arquivo compilado é gerado pelo Python; execute
`npm run build` sempre que mudar o frontend.

A mesma origem elimina a necessidade de permissões CORS amplas. O
servidor permanece restrito a **127.0.0.1**. As respostas recebem política
`Content-Security-Policy` local, `Permissions-Policy`, `no-store` e
os headers já implementados na API.

## Testes

```powershell
uv run --offline --locked pytest -q
cd frontend
npm run build
npm run test
```

O teste Python monta um diretório temporário de HTML e JS e verifica
que a rota raiz, assets e API coexistem, sem rede, com host e cabeçalhos
restritos. Os testes React verificam origem incorporada/API, dados
válidos, erros de rede/schema, ausência de fallback silencioso e retry.

## Limites de segurança e produto

Esta é uma experiência de **dados 100% fictícios**. Não publicar o
servidor em `0.0.0.0`, abrir portas do roteador ou oferecê-lo como SaaS.
O token `Principal` da política RBAC não é login. Ainda faltam usuários
persistidos, autenticação, sessões revogáveis, isolamento de dados por
empresa, TLS público, controles de produção, auditoria LGPD, licenças
financeiras e disponibilidade histórica point-in-time.
