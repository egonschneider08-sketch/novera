# ADR-0012 — Credenciais Argon2id e sessões opacas em SQLite isolado

**Estado:** proposto para revisão na NV-026 (fase A). **Data:** 31/10/2026.

## Problema e ameaça

O Novera Lab [NV-025](https://github.com/egonschneider08-sketch/novera/pull/30)
já reúne React e FastAPI de laboratório local, e o módulo
`novera.authorization` define a matriz RBAC por tenant. Entretanto um
`Principal` criado no código por si só **não demonstra autenticação**;
aceitar `role`, `tenant` ou `subject` diretamente de um request permitiria
escalonamento de privilégio. Precisamos de uma fonte confiável de identidade
antes de qualquer endpoint privado.

A análise de ameaças desta etapa considera vazamento de senha/token,
força bruta, enumeração, acesso entre empresas, papel alterado após login,
sessões antigas após troca de senha, adulteração do esquema SQLite,
arquivos locais permissivos e confusão de usuários com dados de provedores.

## Decisão técnica — núcleo de identidade, sem HTTP

Criar `novera.identity.IdentityStore` em um banco SQLite **dedicado**
e independente de `ObservationStore`, com `application_id=NOVI`,
`user_version=1`, esquema e índices explicitamente verificados em cada
abertura. Bancos desconhecidos ou com alterações no esquema são recusados;
não há migração destrutiva nem criação implícita de banco quando `create=False`.

Dados do schema:

| Tabela | Conteúdo | Proteção |
| --- | --- | --- |
| users | ID opaco, hash Argon2id, revision aleatória, disabled | Hash, sem senha em claro |
| memberships | (user, tenant), papel, active/suspended | Vínculo explícito, role versionável |
| entitlements | (user, tenant, direito de produto) | Chave composta e FK |
| sessions | digest SHA-256 do token, user, tenant, credential_revision, issued/expires/revoked | Nenhum token em claro persistido |

A API **interna** de administração local pode provisionar usuários, alterar
membros e suspender contas. Não é endpoint, não existe autoinscrição,
administrador pré-criado nem senha padrão. O bootstrap é feito por CLI
interativa com `getpass`, nunca parâmetro `--password`, argumento shell,
arquivo .env ou credencial versionada.

### Senhas e sessões

- Argon2id por `argon2-cffi==25.1.0`, parâmetros fixos
  `memory_cost=19456 KiB` (19 MiB), `time_cost=2`,
  `parallelism=1`, salt aleatório 16 bytes e hash 32 bytes;
  revisar custo/latência antes de operar com concorrência real.
  Fonte da API: <https://argon2-cffi.readthedocs.io/en/stable/api.html>.
- Passwords de 12 a 128 caracteres (até 1024 bytes UTF-8), sem
  truncamento ou normalização silenciosa. A CLI confirma por comparação
  de tempo constante e não ecoa a senha no terminal.
- Credenciais desconhecidas e incorretas retornam a mesma exceção
  sanitizada. Verificação Argon2id de hash fictício para conta desconhecida
  reduz a diferença de timing, **mas não elimina enumeração por tempo**,
  nem substitui rate limit, lockout e proteção de abuso.
- `secrets.token_urlsafe(32)` fornece 256 bits aleatórios em
  43 caracteres URL-safe. Persiste somente SHA-256 do token.
  O `SessionGrant` omite o bearer token de seu `repr`.
- TTL padrão 1 hora; permitido apenas de 60 segundos a 24 horas.
  Máximo 8 sessões ativas por usuário e empresa; sessões antigas
  são revogadas. Validade e revogação são verificadas pelo banco em
  **cada** `resolve()`, não por uma credencial JWT não revogável.
- Alteração de senha gera novo hash/revisão e revoga todas as sessões.
  Alteração de membership revoga sessões no tenant. Desabilitar usuário
  revoga sessões de todos os tenants, em transações.
- `resolve(token,tenant,entitlement)` consulta o token e associações
  **do lado do servidor**, devolve `AuthenticatedContext(Principal,StorageScope)`
  apenas para sessão válida, tenant correto, membership ativa e entitlement.
  O serviço consumidor deve obter tenant e entitlement de um recurso
  validado no servidor, não confiar nos parâmetros livres de um request.
- Verificar uma sessão não confere licença para redistribuição de dados.
  O gate de exportações reais da NV-016 continua fechado.

### Limites de segurança do armazenamento

- Arquivo criado exclusivamente (equivalente a `O_EXCL`), modo
  `0600` em POSIX; bloqueio de links simbólicos e caminhos relativos.
  Arquivo POSIX já existente com permissões de grupo/others é recusado.
- No Windows, **é necessária verificação da ACL de NTFS por um operador**:
  o modo POSIX 0600 não é suficiente para controlar a conta do serviço
  nem diretórios herdados. Não apresentar o DB como criptografado.
- SQLite é usado com foreign keys e `synchronous=FULL`, uma conexão
  por thread; não é arquitetura para várias instâncias/distribuição.
- IDs e scope são opacos, consultas parametrizadas e erros sem payload
  sensível. O armazenamento mantém hash de senhas e digests de tokens,
  **mas não oferece criptografia de todos os dados em repouso**.
- O esquema versionado rejeita incompatibilidade, não detecta
  alterações intencionais em todos os dados por um atacante com acesso
  de escrita ao arquivo. Backups/recuperação e audit log também
  precisam de decisão antes da produção.

## Alternativas rejeitadas

- JWTs de longa duração ou perfis enviados pelo frontend: permitem
  confiar em claims sem verificar revogação/alterações de papel.
- Guardar tokens ou senhas em texto puro: não aceitável em incidentes.
- Hashing artesanal/PBKDF de baixa configuração: utilizar biblioteca
  mantida, parametrizada e revisável.
- Acoplar identidades a ObservationStore: violaria isolamento
  de dados financeiros e tornaria migrações complexas.

## Validação e fases posteriores

Testes offline cobrem hash/sal, igualdade genérica do erro para
credencial inexistente, TTL, revogação e rotação, sessões entre
empresas, role alterado, suspensão, política de entitlements,
falha para arquivos/esquemas inválidos, modo arquivo seguro e
ausência de requisições de rede.

Este incremento é **somente a fase A da NV-026**. Ainda faltam:

1. Segurança da interface HTTP: autenticação por cookie HttpOnly, Secure
   onde HTTPS, SameSite, CSRF/Origin checks, anti-bruteforce, limites por IP,
   emissão e renovação, auditoria de eventos sem PII/segredos.
2. Aplicação de RBAC em endpoints **privados** (enquanto a API de laboratório
   pode continuar pública, mas só fictícia), controle horizontal/vertical.
3. Telas de login/saída, gestão de contas e sessões, acessibilidade e testes
   com navegador. Política LGPD e implantação/TLS são trabalhos adicionais.

Não declarar autenticação produtiva, SaaS, multiempresa ou liberação de
dados reais até completar essas fases. Bootstrap/armazenamento ainda
não foram testados manualmente em Windows; testes automatizados rodam
em Linux CI, dev Windows exige confirmação local.

**Referências:** [NV-026 GitHub issue #31](https://github.com/egonschneider08-sketch/novera/issues/31),
[ADR-0010 RBAC](ADR-0010-tenant-rbac-policy.md).
