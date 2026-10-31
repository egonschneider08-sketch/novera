# ADR-0011 — Um único host local para a primeira jornada full stack

**Status:** proposta / NV-025. **Data:** 31/10/2026.

## Contexto

A arquitetura Novera dispõe de estratégias Python, ObservationStore,
pesquisa e comparação sintéticas, React/Vite (NV-011), FastAPI de laboratório
(NV-014) e política pura de autorização por tenant (NV-016).
Sem integração, desenvolver ou demonstrar o sistema exige abrir duas pastas
ou duas portas e não permite exercitar a requisição real da UI à API.
Isso confunde estado offline, dados de servidor e coleta financeira real.

## Decisão

O novo `novera.local_lab` instancia a app FastAPI existente e monta
`StaticFiles(frontend/dist)` na rota **raiz**, depois de todas as rotas
`/api/v1/demo`. O comando explícito `python -m novera.local_lab`
configura Uvicorn em `127.0.0.1:8765`, sem bind público. Não compila
nem baixa dependências automaticamente: exige build Vite prévio.
Arquivos ausentes interrompem o startup com erro claro.

O frontend ganhou uma escolha explícita de **origem**:
- **Dados incorporados:** usa JSON e CSV sintéticos versionados/validados,
  sem requisição de rede.
- **API local:** faz `fetch('/api/v1/demo/comparison')`, com
  `credentials='omit'`, `cache='no-store'`, AbortController e content-type
  JSON; passa o resultado pelo mesmo validador estrito antes de exibir.
  Erros de rede/schema não são mascarados pelo snapshot. Há retry explícito
  e retorno manual ao modo offline.

CSV incorporado fica indisponível em modo API para não representar uma
exportação estática como se viesse do servidor. A API oferece seu próprio
CSV em `/api/v1/demo/comparison.csv` e segue limitada a valores fictícios.

### Segurança do laboratório local

- Mesmo host elimina necessidade de liberar CORS.
- CSP limita `script-src`, `style-src`, `connect-src`, `font-src`,
  `img-src` à origem local; não permite `object-src`, forms ou frames.
- Permissions-Policy desabilita câmera, microfone, geolocalização e pagamento.
- Reutiliza TrustedHostMiddleware, no-store, nosniff, noindex e
  X-Frame-Options existentes no FastAPI.
- Somente diretório `frontend/dist` pré-definido (ou caminho absoluto
  de teste) é montado, com rejeição de arquivos índice symlink.
- Nenhum token, login, conta, banco real, provedor brapi/BCB, coleta de
  mercado ou servidor de produção.

**Atenção:** isolamento localhost + cabeçalhos não substituem autenticação,
permissões, TLS, proteção de rede ou sandbox. Mesmo após a NV-016 RBAC,
ainda não existe um serviço de identidade emissor de Principal confiável,
logo não há acesso de clientes/empresas com contas reais.

## Alternativas rejeitadas

1. Criar CORS permissivo em `127.0.0.1:5173` para acessar a API em
   `127.0.0.1:8765`. Resolveria o demo, mas fragmentaria a execução,
   ampliaria superfícies de configuração e risco de copiar a política
   permissiva para uso comercial.
2. Reimplementar Bazin/Graham em TypeScript. Produziria cálculos
   divergentes e quebraria a origem financeira única em Python.
3. Publicar a API na nuvem diretamente. Seria inseguro antes de identidades,
   isolamento de tenants, direitos de dados, TLS e observabilidade.

## Evidência e próxima fase

`backend/tests/test_local_lab.py` verifica raiz, assets, rotas financeiras,
CSP/host/no-store, bloqueio de rede e falha se o build não existir.
`frontend/src/LabApp.test.tsx` cobre seleção, sucesso via HTTP,
estado de carregamento/erro, schema incompatível, retries e ausência de
fallback silencioso.

A CI faz `npm run build` e executa
`scripts/check_local_lab_build.py`, que testa os assets Vite reais e a
API FastAPI no mesmo TestClient. `scripts/start-local-lab.cmd` oferece
uma experiência Windows reproduzível.

Esta entrega cria um **ambiente de desenvolvimento local**, não uma
release ou hospedagem de SaaS. Evoluções: identidade confiável e sessões
revogáveis; autorização integrada por endpoint/tenant; dados licenciados
com governança point-in-time; deploy controlado com TLS/observabilidade.

[Issue NV-025 #29](https://github.com/egonschneider08-sketch/novera/issues/29).
