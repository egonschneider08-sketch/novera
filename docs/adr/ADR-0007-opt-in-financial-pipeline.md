# ADR-0007 — Pipeline financeiro sob demanda, opt-in e transacional

Status: proposto para revisão NV-023. Data: 2026-10-30. Base: main b440ed0
(após integração de NV-009 / PR #16).

## Contexto

O Novera dispõe de contratos financeiros NV-004, SecureHttpClient, adaptadores
independentes brapi v2 e BCB SGS 432 e ObservationStore SQLite versionado.
Esses módulos ainda não trabalham juntos numa única unidade de ingestão.
Misturar coleta, conversão financeira, storage e agendamento desde já dificultaria
auditar falhas e violaria o princípio de incrementos pequenos da Sprint 0/1.

## Decisão

Criar `novera.pipeline` com `FinancialPipeline.run()` e duas tarefas tipadas:
`QuoteRequest(BrapiInstrument, token opcional)` e `SgsRequest(Period)`.
O chamador fornece explicitamente `AccessContext`, `ObservationStore`
e os adaptadores compartilhados. Não se cria cliente HTTP nem storage no
pipeline, nem se fecha recurso pertencente ao chamador.

**Execução desativada por padrão:** `enabled=False` rejeita a chamada antes de
qualquer HTTP. Este recorte admite apenas storage e adapters rotulados
`synthetic=True`, com scope autenticado idêntico ao StorageScope. **Essa
etiqueta não prova ausência de rede**: o chamador deve usar `MockTransport`
nos testes e isolar rede por ambiente. `enabled=True` é opt-in operacional
e não significa permissão para coletar ou redistribuir dados reais.

O pipeline pré-valida tipos de tarefas, existência dos adaptadores, limites
e escopos. Executa as consultas sequencialmente; valida origem, identidade,
timestamps de coleta e `Freshness`. Rejeita `STALE` inclusive quando
recebido de um adapter modificado; política `allow_stale=True` é bloqueada.
`NETWORK` e `FRESH` são relatados distintamente — cache fresco não prova
nova observação econômica nem idade do mercado.

Depois de todas as consultas bem-sucedidas, chama uma única
`ObservationStore.ingest_many()` dentro da transação do storage. Uma falha
HTTP, schema, stale ou armazenamento significa zero *novas* gravações do
lote. As chamadas de rede anteriores não são revertíveis.

## Identidade dos registros

- brapi: `brapi:quote:{ticker}:{market_at_UTC_ISO}`. O contrato lógico
  do storage também inclui identidade Asset estável, tipo, métrica e provider.
  Cotação é `regular_market_price` com ajuste desconhecido;
  **não** é automaticamente `close` elegível a Graham/Bazin.
- SGS 432: `bcb:sgs:432:{data_nominal_ISO}`. A taxa é fração anual
  e não retorno diário. Ausência de dia fica em `unreturned_dates`,
  sem zero implícito, interpolação, forward fill ou afirmação de completude.
- Revisões de conteúdo geram versões econômicas; coletas repetidas geram
  recibos idempotentes segundo a política documentada na ADR-0006.

Retorno `PipelineRun(records, tasks)` preserva recibos armazenados e um
`TaskReport` por consulta com provider, freshness, coleta, quantidade e
datas não retornadas (BCB). Não apresenta ranking, sinal de compra ou
certificação de disponibilidade point-in-time.

## Alternativas descartadas

- Scheduler e coleta automática: prematuros sem licença de dados e proteção
  operacional do ambiente, quotas distribuídas ou monitoramento.
- Ingerir após cada provedor: cria snapshots parciais quando a segunda
  solicitação falha.
- Duplicar retry/cache no pipeline: cria inconsistências e risco de quota.
- Completar lacunas de SGS ou alterar nomes de métricas de preço: inventa
  dados econômicos e permitiria usar cotação não certificada em estratégias.
- Tratar `synthetic=True` como mecanismo de bloqueio de rede: etiqueta de
  procedência não controla `httpx.Client`.

## Riscos e consequências

Somente processos locais em uma thread, sem criptografia nativa SQLite,
serviço multiusuário ou coordenação entre executores. Máximo 16 tarefas por
lote; cada chamada BCB aceita até 366 dias. Execuções não são agendadas,
não têm deadline global e podem ter efeitos de rede mesmo se a transação
final falhar. Não há ainda política de backfill, calendário de pregão,
publicação histórica verificável, condições de revenda de brapi, nem rotina
operacional real para o HTTP 400 em consultas SGS pontuais.

Não executar consultas reais na CI. Termos da brapi restringem
redistribuição e uso comercial; o conjunto de dados BCB possui obrigações
ODbL. Integrar o módulo não libera coleta e exposição pública de dados.

## Evidência e rollback

Testes de integração com `httpx.MockTransport`, sem token real ou rede, cobrindo
falhas atômicas, idempotência, revisões, contextos, synthetic, stale, lacunas,
qualidade e relatórios. Evidências de testes e CI no PR NV-023.

Rollback: reverter as funções e propriedades somente-leitura adicionadas,
sem migração de banco; o schema SQLite NV-009 permanece intacto.
