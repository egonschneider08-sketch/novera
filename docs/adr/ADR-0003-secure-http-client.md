# ADR-0003: transporte GET e cache segregado por acesso

Status: proposto para revisao NV-002. Data: 2026-10-29.

## Contexto
A auditoria da referencia mostrou cache sem identidade de credencial e stale sem
envelope. O dominio ja esta integrado na main 7e08e54; adapters precisam de uma
base HTTP testavel sem duplicar resiliencia ou misturar dados de usuarios.
Direitos de publicacao literal da referencia seguem pendentes; codigo independente.

## Decisao
Adicionar HTTPX 0.28.1 travado no pyproject/uv.lock como dependencia de runtime.
Usar HTTPTransport reutilizado, TLS default verificado e trust_env=False, sem jar
de cookies/redirects/netrc/retries internos. Apenas GET, com timeout em todas as
fases e retry limitado de falhas transitorias. Retry-After nao pode ser encurtado;
se ultrapassar espera operacional maxima, falhar e manter cooldown.
Serializar rede por instancia/provedor e espacamento via monotonic injetavel.
Nao introduzir async, cache distribuido, circuit breaker ou banco nesta entrega.

Cache LRU em memoria, HMAC-SHA256 com chave aleatoria por cache e namespace completo
por acesso/requisicao/schema. Retornar envelope com origem/freshness/idade/falha.
Cache somente apos validacao; JSON fracionario como Decimal, sem duplicatas ou
nao finitos literais. Stale somente opt-in limitado, sem bypass de autorizacao.
401/403 invalidam a particao de acesso. Nao armazenar requests/headers/cookies.
Valor cacheado copiado para nao permitir mutacao cruzada entre consumidores.

Erros sanitizados; logs de transporte conhecidos suprimidos apenas no contexto
ativo, sem alterar niveis globais. Nao imprimir corpos, URLs, tokens ou hashes.
Respeitar diretivas conservadoras no-store/no-cache/must-revalidate/Vary:* e
encurtar TTL por max-age/Age. Adapters terao schemas especificos obrigatorios.

## Alternativas
requests nao oferece transporte mockavel equivalente sem adaptacao adicional;
urllib exigiria implementar mais controle de pool/timeout. HTTPX Client manteria
estado de cookies sem valor neste recorte: transporte direto reduz estado entre
usuarios. Cache em disco/distribuido exigiria ciclo de vida, permissao, criptografia
e invalidacao ainda nao especificados. Nao copiar cliente da referencia evita
herdar isolamento incompleto e nao depende de relicenciamento pendente.

## Consequencias e limites
Uma instancia por provedor deve ser compartilhada para quota/concurrency local.
Nao coordena processos, nao autentica usuarios nem descobre revogacoes em cache
fresco: camada de acesso deve autorizar cada chamada e atualizar namespace.
Sem deadline global, HTTP cache RFC completo, limites comerciais automaticos ou
validacao de fornecedor. Validators e transports customizados sao confiaveis;
nao ha garantia universal de detectar segredos, cancelar I/O ou isolar rede.
HTTPcore tem loggers conhecidos travados; upgrades precisam revisar essa protecao.
Freshness nao certifica validade financeira nem habilita backtest.

## Evidencias
Testes offline em backend/tests/test_http.py e documentacao docs/http-client.md.
Comandos/resultados reais e CI ficam no PR NV-002 deste incremento. Nenhuma API
externa foi chamada pelos testes; sem dados reais, credenciais ou deploy.

## Rollback
Reverter commit e dependencia/lock juntos; nao existem migracoes persistentes.
Cache e somente process-local e descartado ao encerrar o processo.
