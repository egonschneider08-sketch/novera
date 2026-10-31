# ADR-0010 — Autorização por tenant e papéis: política pura, negar por padrão

**Estado:** proposta (NV-016, recorte inicial). **Data:** 30/10/2026.

## Contexto

O Novera possui observações financeiras isoladas por
`StorageScope(tenant, entitlement, credential_revision)` e
`AccessContext` para acesso a provedores, mas **não** possui um diretório
de usuários, autenticação, controle de sessões ou cadastro.

Antes de permitir visualizar produtos e pesquisas de empresas no mesmo
sistema, precisamos de uma política de permissões independente de HTTP,
JWT, senhas e provedores. Um ator administrador não deve contornar o
isolamento de empresas, a versão de credenciais ou direitos de dados reais.

## Decisão

Criar `novera.authorization` como módulo Python **puro e separado** de
identificação/autenticação. O `Principal` imutável exige:
`subject` (ID interno), `tenant`, `credential_revision`,
`Role`, `MembershipStatus` e conjunto imutável de `entitlements`.
Ele é **apenas um contrato de alegações**: criar uma instância Python
não prova que o usuário efetuou login.

Política versionada `tenant-rbac-v1`:

| Permissão | Viewer | Analyst | Owner |
|---|:---:|:---:|:---:|
| Ver produtos | Sim | Sim | Sim |
| Ver pesquisas | Sim | Sim | Sim |
| Exportar pesquisa sintética | Não | Sim | Sim |
| Gerenciar produtos | Não | Não | Sim |
| Gerenciar usuários | Não | Não | Sim |
| Gerenciar direitos internos | Não | Não | Sim |

Regra complementar e mandatória: **exportar pesquisa marcada como real é
negado em todas as funções**, inclusive owner, até existir uma autorização
de distribuição de dados com prova de licença/contrato. Permitir visualização
interna com entitlements **não** certifica licença de provedor ou operação
comercial; fontes reais exigem gates adicionais de governança.

`evaluate(principal, scope, permission, synthetic=bool)` retorna
`Decision(allowed, code, policy_version)`. Concede uma permissão
somente se todas as condições forem satisfeitas:

1. Principal, permissão, flag synthetic e StorageScope são de tipos
   esperados; dados mutados são revalidados.
2. Membership está ativa.
3. Tenant e credential_revision coincidem **exatamente** com o StorageScope,
   inclusive para owners.
4. Entitlement exato do recurso pertence ao conjunto do usuário.
5. Role concede a ação. Exportações reais têm bloqueio adicional.

`require_permission()` falha fechado com `AccessDenied("access denied")`,
sem revelar ao cliente a razão interna, IDs de tenant ou entitlements.

## Por que não implementar login agora?

Um login realmente seguro exige identidade persistida e verificada,
hashing de senhas com algoritmo apropriado e revisão de parâmetros,
ciclo de sessões/refresh/rotações, MFA quando aplicável, proteção CSRF,
rate limiting, auditoria de ações, tratamento de dados pessoais e
mecanismos de revogação. Usar `Principal` instanciado com JSON enviado
pelo navegador seria uma vulnerabilidade de escalonamento de privilégios.

A API sintética no [PR #26](https://github.com/egonschneider08-sketch/novera/pull/26)
e a UI no [PR #24](https://github.com/egonschneider08-sketch/novera/pull/24)
continuam **independentes, sem autenticação declarada e não integradas**.
Não acoplar esta política às rotas públicas demonstrativas por enquanto:
primeiro criar o serviço de identidade capaz de gerar Principal confiável
e mapear a identidade à empresa do servidor, nunca à escolha do cliente.

## Limitações, testes e rollback

- O `Principal` não é um token autenticado, não armazena segredo
  e pode ser instanciado por código Python. Seu uso só é seguro
  com um emissor **confiável e verificado**, futuro.
- `entitlements` são permissão de produto, não redistribuição
  contratual de cotações ou indicadores financeiros.
- Nenhum acesso anônimo a dados de empresa é concedido; o laboratório
  sintético continuará isolado e sem usuário.
- Este PR não implementa logout, cadastro, cookies, recuperação de senha,
  banco de usuários, serviços HTTP, UI de administração ou autenticação
  por JWT. O estado geral NV-016 permanece **em desenvolvimento**.
- Testes offline cobrem matriz de roles, tenant errado, entitlement errado,
  credencial revisada, suspensão, mutações de dataclasses e
  exceção sem informações pessoais ou de empresas.

Rollback: remover `authorization.py`, seus testes e documentos.
Sem nova dependência, endpoint ou migração de banco.

[GitHub issue NV-016 #27](https://github.com/egonschneider08-sketch/novera/issues/27).
