# NV-002: cliente HTTP seguro (GET/JSON)

Implementacao independente em `novera.http`, base main 7e08e54 apos merge do PR #11.
Nenhum trecho literal da referencia Winning Investments v2 foi copiado.
Decisoes: [ADR-0003](adr/ADR-0003-secure-http-client.md).

## Escopo e interfaces

- SecureHttpClient(provider, origin): uma instancia compartilhada por provedor,
  origem HTTPS fixa e confiavel, sem caminho, credenciais, query ou fragmento.
  Reutiliza HTTPTransport e pool; TLS verificado, sem redirects, cookies,
  proxies de ambiente, netrc ou retries ocultos. Context manager fecha o pool.
- get_json(path, context, schema_version, validator, params, headers, cache_policy):
  somente GET. Nao existem POST, escrita ou replay automatico de operacoes inseguras.
  O endpoint e relativo a origem fixa; query deve conter apenas dados publicos.
  Credenciais devem usar Authorization ou X-API-Key, nunca URL/query/context IDs.
- AccessContext: tenant, entitlement e credential_revision sao IDs opacos nao secretos,
  fornecidos pela camada autenticada da aplicacao. Isto **nao autentica usuarios**.
- Validator obrigatorio: funcao confiavel que valida e normaliza o payload; a versao
  de schema deve mudar junto com a sua semantica. JSON usa Decimal para fracionarios,
  rejeita NaN/Infinity e campos duplicados. O cliente nao valida contratos de mercado.
- JsonEnvelope: data, freshness, fetched_at UTC, age_seconds, attempts,
  stale_reason e failure_status. Payload e IDs de contexto omitidos de repr.

## Politicas

RetryPolicy padrao: timeout 10s para connect/read/write/pool; max_retries=2
(ate tres tentativas), backoff_base=0.5s, cap=8s, jitter uniforme completo,
max_wait=60s por espera e min_interval=0.2s. Relogios, sleep e jitter injetaveis
permitem testes deterministas. Nao ha deadline global nem cancelamento assinc.
Read timeout mede inatividade por leitura, nao duracao total de um download.
O corpo JSON decodificado e limitado a 2.000.000 bytes antes de validar/cachear;
isso nao e um limite duro de memoria do descompressor ou de validators confiaveis.

Retry apenas para timeouts, erros de transporte e HTTP 408/429/500/502/503/504.
HTTP 3xx nao e seguido. Outros status e JSON/schema invalidos falham sem retry.
Retry-After aceita segundos inteiros nao negativos e HTTP-date, incluindo zero;
o prazo do servidor nao e reduzido pelo cap do backoff. Espera = maior prazo
entre servidor, jitter e espacamento do provedor. Prazo acima de max_wait faz
falhar sem reenviar cedo; o cooldown permanece para chamadas posteriores.
O lock por instancia limita a uma operacao de rede por provedor, inclusive
esperas/retries, entre usuarios/contextos. Nao ha quota distribuida entre
instancias/processos, nem inferencia de limite de plano comercial.

## Cache e direitos de acesso

MemoryCache e limitado (padrao 256 entradas, LRU), somente em memoria. A chave e
HMAC-SHA256 com segredo aleatorio por cache, nao URL/token em texto ou hash simples.
Identidade inclui provedor, origem/requisicao normalizada, tenant, entitlement,
revisao da credencial, schema e todos os headers, inclusive material de autenticacao e headers de variacao.
Credenciais novas separam entradas mesmo se o contexto declarado nao mudou.
So o valor validado e copiado; request, headers, cookies e resposta bruta nao
sao armazenados. Retornos sao copias defensivas. Cache compartilhado entre
provedores preserva a separacao; seus usuarios devem usar o mesmo dominio de
relogio monotonic. Limite por entradas, nao quota de bytes agregada.

TTL default 60s. ttl=0 nao gera hit fresco. A politica atual nao pode estender
o TTL original de uma entrada. max-age/Age do servidor podem encurta-lo.
no-store/no-cache/must-revalidate e Vary:* impedem armazenamento. Nao e um
cache HTTP RFC completo: sem ETag, revalidacao condicional ou Expires. Adapters
devem respeitar termos/licencas e verificar se o recurso pode ser cacheado.

Stale default desligado. Opt-in exige max_stale finito; idade e recalculada apos
as tentativas, sem renovar fetched_at. Fallback somente para falhas transitorias
ou cooldown, dentro de TTL+max_stale, no mesmo namespace. Erros permanentes ou
schema invalido nunca retornam stale. 401/403 invalidam a particao de acesso
(todos os recursos do mesmo provedor/contexto/credenciais); outros erros invalidam
a entrada correspondente. Nenhuma falha grava payload parcial ou erro no cache.
Revogacoes ainda nao observadas nao sao descobertas em hits frescos: o chamador
deve autorizar cada acesso e atualizar contexto/revisao ou limpar o cache.
clear() invalida dados; nao remove cooldown. Nao ha garantia de revogacao de
respostas que ja tenham sido entregues ou autorizacao externa automatica.

Freshness descreve a obtencao HTTP/local, **nao atualidade financeira**.
NETWORK significa resposta 200 validada, FRESH hit local dentro do TTL e STALE
fallback com falha explicita. Dataset de fornecedor pode estar antigo mesmo em
NETWORK. Adapters devem preservar datas/publicacao/coleta e flags no dominio.

## Segredos e erros

FetchError preserva somente kind, attempts e status; nao carrega excecao original,
URL, contexto ou corpo. Nenhum log de payload/requisicao e emitido pelo cliente.
Logs brutos dos namespaces HTTPX/httpcore conhecidos da versao travada sao
suprimidos por filtro somente no ContextVar da operacao ativa; nao sao mudados
niveis globais nem logs de outros threads. Outros loggers/custom transports e
validators confiaveis continuam responsabilidade da aplicacao. Nao habilitar
instrumentacao externa que imprima requests, headers ou variaveis locais.

Campos tipicos de credenciais em payloads e ecos dos valores de credenciais
conhecidos sao rejeitados antes de validar/cachear. Isto e defesa adicional,
nao classificador universal de segredos: validators precisam selecionar campos
permitidos e nao introduzir credenciais. IDs de contexto nao devem ser tokens.
Chaves HMAC nao tornam payloads cacheados nao sensiveis; o cache nao deve ser
exposto a usuarios nem persistido. Nao ha cache em disco neste incremento.

## Exemplo offline (dados sinteticos)

```python
from decimal import Decimal
import httpx
from novera.http import AccessContext, SecureHttpClient

def validate_quote(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("price"), Decimal):
        raise ValueError("invalid quote")
    return payload["price"]

transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b'{"price":12.34}'))
with SecureHttpClient("synthetic", "https://provider.invalid", transport=transport) as client:
    result = client.get_json(
        "/quote", context=AccessContext("demo-user", "demo-plan", "revision-1"),
        schema_version="demo-v1", validator=validate_quote,
    )
    assert result.data == Decimal("12.34")
    assert result.freshness == "network"
```

## Verificacoes e limites de evidencia

```sh
uv sync --locked --group dev
uv run --offline --locked pytest -q
uv run --offline --locked ruff check .
uv run --offline --locked ruff format --check .
uv run --offline --locked python scripts/check_secrets.py --self-test
uv run --offline --locked python scripts/check_secrets.py
```

Testes HTTP usam MockTransport, relogio/sleep falsos, fixtures sinteticas e guard
contra DNS/connect Python. Cobrem timeout, 429/date/zero/cooldown, jitter e ritmo,
concorrencia, contextos, rotacao, provedores, headers/schema/query, TTL/LRU/stale,
401/403, erros parciais, fechamento de streams, logs e segredos, validacao JSON.
Nao fazem chamadas a APIs reais. O guard nao e isolamento universal do SO;
os testes verificam configuracao de timeout/excecoes simuladas, nao latencia
real de uma rede, TLS, DNS, proxy ou comportamento de fornecedores.

Baseline main: 114 passed in 0.20s. Primeira bateria HTTP: 175 testes passaram;
Ruff identificou uma atribuicao lambda em teste, corrigida para def sem ignorar
regra. Um teste novo de import falhou porque substituir socket.socket por funcao
quebrava a heranca de SSLSocket no import do HTTPX, nao por uso de rede. O guard
foi corrigido para bloquear DNS/create_connection/connect preservando a classe;
a reexecucao completa passou com 212 testes. Resultados finais e CI no PR.
Auditoria inclui dependencias do lock; acesso a indice/advisories exige rede.

## Referencias primarias

- https://www.python-httpx.org/advanced/timeouts/
- https://www.python-httpx.org/advanced/transports/
- https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after

Proximos incrementos: adapters brapi/BCB em PRs separados, contratos e proveniencia,
cache distribuido somente com requisitos/benchmark, pipeline depois de adapters.
Sem nova coleta, banco, UI, deploy ou copia literal do Winning Investments v2.


## Ocorrencia na publicacao inicial

O scanner identificou duas fixtures deliberadamente sinteticas (URL .invalid
com user:password e parametro api_key com valor synthetic). A sequencia local
nao interrompeu o shell no exit nao zero do scanner e publicou o primeiro commit.
Corrigido com anotacoes allowlist estritamente nas duas linhas de fixtures,
justificadas no proprio teste, sem desabilitar plugins ou reduzir a varredura.
O controle negativo com marcador sintetico de chave continua obrigatorio.
As verificacoes posteriores foram executadas com fail-fast antes do commit.
Nenhum token, senha de servico ou credencial real foi identificado nesses achados.
A CI inicial e as reexecucoes devem ser relatadas separadamente no PR.
