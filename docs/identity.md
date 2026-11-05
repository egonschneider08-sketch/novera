# NV-026 fase A — Núcleo local de identidade e sessões verificadas

**Status:** implementação isolada em revisão, não é login público nem
SaaS multiusuário. Usuários do Novera Lab ainda podem acessar apenas
os cenários fictícios sem autenticação; as rotas `/api/v1/demo/*`
continuam demonstrativas e não usam o novo banco de contas.

## O que foi construído

`backend/src/novera/identity.py` cria um SQLite separado daquele
utilizado nas observações financeiras, sem conta padrão e sem conversão
automática de esquemas desconhecidos. A base contém usuários,
associações a tenants, direitos de produto e sessões revogáveis.
Senhas passam por Argon2id com sal aleatório; o token entregue
por `issue_session()` é aleatório de 256 bits e o SQLite guarda apenas
seu digest SHA-256. Sessões têm prazo e exigem que o usuário continue
ativo, com senha/revisão e associação ao tenant corretas.

A recuperação `resolve(token, tenant=..., entitlement=...)` retorna
um `AuthenticatedContext` com `Principal` e `StorageScope`
construídos **somente depois de verificar a sessão persistida**.
O contexto pode então passar por
`require_permission(context.principal, context.scope, ...)`,
reutilizando a política RBAC NV-016. Isto ainda não significa que
qualquer endpoint esteja protegido: **não existem endpoints de login**.

## Primeiro bootstrap — somente operador local

Pré-requisitos: Python 3.12, uv e Git. Primeiro sincronize
as dependências travadas na pasta do Novera. Para criar um banco
**novo** (não sobrescreve arquivo existente), abra um PowerShell
interativo e execute:

```powershell
cd C:\Users\Schneider\Documents\novera
uv sync --locked --group dev

uv run --locked python scripts/bootstrap_local_identity.py `
  --database "C:\Users\Schneider\Documents\novera-identity.sqlite3" `
  --subject "local-operator-1" `
  --tenant "novera-lab" `
  --entitlement "synthetic-research"
```

A CLI solicita a senha duas vezes via `getpass`, sem argumentos
de senha na linha de comando. Não imprime senhas nem tokens.
O caminho é apenas um **exemplo**; mantenha o banco em uma área
local protegida por ACLs NTFS e fora do repositório Git.

A ferramenta não tem opções para hospedar o banco, criar usuários
anônimos ou reabrir o mesmo arquivo com `create=True`.
O bootstrap é uma operação administrativa de confiança, **não
implementa autenticação no navegador**.

## Contrato do backend (exemplo interno)

O código seguinte é demonstrativo para um serviço Python confiável
e não deve ser colocado diretamente em uma rota HTTP. Não exponha
os tokens em `print()`, logs ou argumentos CLI.

```python
from novera.authorization import Permission, require_permission
from novera.identity import IdentityStore

with IdentityStore.local(ABSOLUTE_TRUSTED_DB_PATH) as store:
    # O serviço confiável verificou o escopo solicitado e recebeu o
    # segredo num canal protegido; não aceitar role vinda do cliente.
    grant = store.issue_session(
        subject="local-operator-1",
        password=VERIFIED_SECRET_FROM_SECURE_INPUT,
        tenant="novera-lab",
    )
    context = store.resolve(
        grant.token,
        tenant="novera-lab",
        entitlement="synthetic-research",
    )
    if context is not None:
        require_permission(
            context.principal,
            context.scope,
            Permission.VIEW_RESEARCH,
            synthetic=True,
        )
    store.revoke_session(grant.token)
```

`VERIFIED_SECRET_FROM_SECURE_INPUT` e `ABSOLUTE_TRUSTED_DB_PATH`
representam dados entregues por uma futura camada confiável, não
variáveis padrão do projeto.

## Segurança e operação — limites atuais

- **Argon2id:** `argon2-cffi==25.1.0`, 19 MiB/2 passagens,
  paralelismo 1; revisar desempenho antes de carga real.
- **Sessões:** padrão 3600 s, máximo 24 h, no máximo 8 sessões
  ativas por membro/empresa; ao trocar senha ou alterar membership
  as sessões pertinentes são revogadas.
- **Isolamento:** token fica vinculado a usuário e tenant; para
  emitir `Principal`, a entidade precisa continuar ativa e possuir
  entitlement exato no banco. Nenhum papel concede automaticamente
  direitos financeiros de redistribuição.
- **Banco local:** caminho absoluto, criação exclusiva, sem symlinks,
  versão e DDL verificados, permissões 0600 em POSIX. **Windows:
  revisar manualmente ACLs NTFS**; não existe criptografia do banco inteiro.
- **Brute force:** não há rate limiting por IP/conta, 2FA ou lockout
  na fronteira HTTP. A diferença temporal entre erros não prova
  proteção contra enumeração. Portanto, não disponibilizar `issue_session`
  como rota pública.
- **Recuperação:** perda de senha ou banco ainda não possui fluxo de
  reset, recuperação segura, backup ou rotação de chaves em nuvem.
- **Testes:** offline, schemas desconhecidos e permissões de arquivo,
  hash/salt, ausência de senha/token em claro, revogação por
  logout/alteração de acesso/senha, suspensão e isolamento de tenants.

**Próxima fase NV-026 B:** escolher arquitetura de sessões/cookies,
proteção CSRF, rate limit de ingresso, autenticação HTTP, emissão
de `Principal` em dependency injection e aplicação de
`require_permission` às rotas **privadas**. Somente então projetar
telas de login/cadastro, contas e produtos.

[ADR-0012](adr/ADR-0012-identity-sessions-argon2id.md) ·
[Issue NV-026 #31](https://github.com/egonschneider08-sketch/novera/issues/31).
