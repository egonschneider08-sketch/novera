# NV-016 — Papéis, permissões e isolamento de empresas (fase 1)

Esta é uma **política Python testável** de autorização, não um sistema de
cadastro/login e **não** uma afirmação de que existe controle de acesso
operacional no website. A camada de identidade confiável continua pendente.

## Papéis

| Papel | Consulta de produtos | Pesquisa | Exportação sintética | Gestão de produtos/usuários |
|---|---|---|---|---|
| Viewer | Sim | Sim | Não | Não |
| Analyst | Sim | Sim | Sim | Não |
| Owner | Sim | Sim | Sim | Sim |

O owner **não** atravessa outro tenant, outro entitlement ou versão de
credencial. Exportar dados reais permanece sempre negado, independentemente
do cargo; a política de licenças e redistribuição é outra camada.

## Contrato de uso em um serviço confiável

O exemplo abaixo **não** é autenticação, mas mostra a forma da política
que um futuro serviço de identidade deverá aplicar **após validar a sessão
no servidor**:

```python
from novera.authorization import (
    MembershipStatus, Permission, Principal, Role, require_permission,
)
from novera.storage import StorageScope

# Somente dados previamente conferidos contra uma sessão e um banco de membros.
principal = Principal(
    subject="user-verified-1",
    tenant="company-verified-1",
    credential_revision="session-revision-1",
    role=Role.VIEWER,
    status=MembershipStatus.ACTIVE,
    entitlements=frozenset({"research-internal"}),
)
scope = StorageScope(
    "company-verified-1", "research-internal", "session-revision-1"
)
require_permission(
    principal, scope, Permission.VIEW_RESEARCH, synthetic=True
)
```

**Jamais** receber `principal` ou `role` diretamente de JSON/URL/cookies
sem validar identidade, associação ao tenant e estado de sessão em fonte
confiável. A API de laboratório do PR #26 não tem login e não usa essa
política para fingir proteção por usuário.

## Invariantes

- `Decision` contém permitido/negado, um código **interno** e versão
  imutável da política.
- `require_permission()` lança mensagem pública genérica `access denied`.
  Não divulgar IDs, entitlements ou motivos detalhados à UI.
- `Principal` exige ID de usuário, empresa, versão e conjunto de direitos
  explícitos; tipos inesperados, associações suspensas e valores alterados
  depois da criação são rejeitados.
- A igualdade com o `StorageScope` atual impede acesso cruzado pelo
  mesmo usuário ou proprietário. Entitlement não é equivalente a
  licença de fornecedor.
- Código não lê rede, banco, cookie, token ou segredo; é determinístico.

## O que falta para cadastrar pessoas de verdade

Entidade de usuário e membership persistidas; cadastro e validação de e-mail,
password hashing com revisão de parâmetros; login/sessões com rotação e
revogação; verificação de identidade em cada requisição; rate limiting;
auditoria; políticas LGPD e recuperação de conta, e verificações de
permissões integradas aos endpoints. Um design de autenticação seguro deve
vir antes de qualquer API privada ou acesso aos dados reais.

Veja [ADR-0010](adr/ADR-0010-tenant-rbac-policy.md) e
[issue NV-016 #27](https://github.com/egonschneider08-sketch/novera/issues/27).
