# NV-002: auditoria e primeira migracao do Winning Investments v2

Data: 2026-10-29. Base Novera: main f896e27. Estado: implementacao independente
para revisao; nao encerra NV-002 e nao afirma equivalencia integral.

## Origem, integridade e direitos

Arquivo recebido: Winning_Investments_v2_bootstrap.py, 50.109 bytes, 1.403 linhas.
SHA-256: e9f70026de9914ba543b42c06d01c9c20d6037084a9cf7de51c777a196b725c0.
O hash coincide com o fornecido. Foram encontradas 24 atribuicoes literais a
FILES usando AST; o bootstrap nao foi executado, importado nem aplicado no monorepo.
A extracao de subconjunto para testes usou ast.literal_eval de chave/valor,
com verificacao de caminho dentro de uma raiz temporaria nova.

O proprietario declarou nesta sessao ser o desenvolvedor da referencia. O arquivo
nao contem licenca propria ou identificacao formal de autor. A autorizacao
especifica para republicar trechos literais sob BSD-3-Clause permanece pendente,
assim como verificacao de direitos de eventuais componentes de terceiros.
A licenca do Novera nao relicencia a referencia automaticamente.
**Nenhum arquivo ou trecho literal da referencia foi publicado neste incremento.**
O novo modulo e uma implementacao independente das formulas/especificacoes
fornecidas, com estrutura e contratos proprios do Novera. Bibliotecas citadas
abaixo foram apenas inventariadas, nao adicionadas como dependencias.

## Inventario completo (24 entradas FILES)

requirements.txt; pytest.ini; .gitignore; .env.example; .streamlit/config.toml;
README.md; wi/__init__.py; wi/__main__.py; wi/config.py; wi/http.py;
wi/sources/__init__.py; wi/sources/brapi.py; wi/sources/bcb.py; wi/storage.py;
wi/strategies.py; wi/pipeline.py; wi/demo.py; wi/cli.py; app.py;
tests/__init__.py; tests/test_http.py; tests/test_strategies.py;
tests/test_pipeline.py; tests/test_app.py.

Dependencias declaradas na origem: httpx>=0.27, pandas>=2.2, duckdb>=1.0,
streamlit>=1.40, plotly>=5.24 e pytest>=8.0. Sem lock, faixa superior ou
reproducao historica garantida. Nao se presume licenciamento dessas bibliotecas
para copiar seu codigo; esta entrega nao as incorpora.

## Matriz de comportamento observado e destino

| Origem | Comportamento observado | Problemas / oportunidade | Destino / prioridade |
|---|---|---|---|
| bootstrap | escreve arquivos/.env, cria venv, instala, testa, diagnostica rede, carrega demo e abre app | force sobrescreve; efeitos operacionais amplos | nao migrar; uv/CI existentes |
| wi/config.py | le .env para os.environ e converte configuracao | token pode aparecer no repr do dataclass; valores numericos sem limites; mistura ambiente/processo | configuracao explicita validada; futura |
| wi/http.py | cliente reutilizado, GET, timeout, retries, jitter, cache e breaker | chave ignora headers/entitlements; stale sem envelope; Retry-After limitado por backoff_max e zero tratado como ausente; cache/throttle sem controle concorrente por provedor | cliente compartilhado com namespace seguro e freshness; proximo incremento separado |
| wi/sources/brapi.py | normaliza primeiro resultado, deriva multiplos, fallback por permissao | float; zero LPA pode cair em fallback por operador or; ticker retornado nao conferido; mistura payment/ex/aprovacao; perde tipo/base tributaria e cobertura | adapter para contratos NV-004; depois de HTTP |
| wi/sources/bcb.py | serie 432, ultimo valor convertido de percentual em fracao | captura falhas como None sem motivo; descarta data/unidade/publicacao | adapter BCB com proveniencia e testes; depois de HTTP |
| wi/storage.py | snapshots/dividendos/meta em DuckDB; parametros SQL e lock local | DOUBLE; identidade por ticker/data; revisoes e corporate actions ausentes; leitura pode criar banco; purge demo e destrutivo; trava nao coordena processos | schema e benchmark antes de persistir; nao migrado |
| wi/strategies.py | cinco blocos de 365 dias, teto por yield; raiz de 22.5*EPS*BVPS e filtros parciais | falta de dados vira False/zero; sem cobertura/periodo/moeda; floats | funcoes puras independentes em novera.strategies; prioridade atual |
| wi/pipeline.py | coleta por ativo, registra falhas e monta ranking pandas | purge demo automatico; media dos scores penaliza missing; snapshots recentes sem disponibilidade historica | orquestracao depois dos adapters/storage; sem ranking neste PR |
| wi/demo.py | seis empresas ficticias e pagamentos sinteticos | grava no mesmo banco e remove demo anterior; divs perdem fonte | fixtures sinteticas em testes, sem migrar base |
| wi/cli.py | doctor/demo/update/rank/export/app | doctor usa rede e escreve banco; acoplamento a UI/dados | CLI opcional apos dominio, sem migracao agora |
| app.py | Streamlit no nivel superior, consulta banco ao renderizar | import tem efeitos de UI/storage; prototipo nao define frontend final | referencia de UX apenas; React futuro fora de escopo |
| tests/test_http.py | mocks de retry, 429, cache, stale, breaker e auth | nao cobre isolamento de entitlement ou concorrencia; stale considerado sucesso | ideias para testes do futuro cliente independente |
| tests/test_strategies.py | 7 testes de exemplos, negativos e missing | aceita missing como score zero e ausencia de cobertura | baseline executado separado; novas invariantes no Novera |
| tests/test_pipeline.py | 6 testes de update/ranking/demo/storage com mocks | valida fluxo antigo e nao point-in-time | reescrever quando houver pipeline |
| tests/test_app.py | 2 testes Streamlit vazia/demo | dependencias/UI/storage grandes para recorte atual | nao executar/migrar nesta etapa |

## Contratos preservados e interfaces novas

Asset, Source, Period, Provenance e Observation permanecem inalterados.
PerShareInput acrescenta identificacao explicita da base por acao (mesma base
para preco, LPA, VPA e proventos; nunca infere splits). CashPayment exige event_id
estavel e com namespace do provedor. DividendHistory contem cobertura com
proveniencia, declaracao de completude, moeda e convencao gross/net.
StrategyResult guarda evidencia original imutavel, versao, parametros, as_of,
rotulo sintetico, metricas e justificativas por criterio pass/fail/unknown.
Nao ha score agregado nem recomendacao. DerivedMetric e um resultado derivado,
nao uma cotacao de fornecedor; sua trilha esta nos inputs e na regra do resultado.

## Politica metodologica

Ver [ADR-0002](../adr/ADR-0002-pure-valuation-heuristics.md).
Bazin: cinco janelas exatas de 365 dias, limites inclusivos 0..364,
365..729, ..., 1460..1824 dias antes da data UTC de avaliacao. Nao sao anos civis.
Somente pagamentos realizados; eventos futuros sao excluidos e contados na
justificativa. Media = soma/5; teto = media/yield alvo, padrao 0.06 parametrizavel.
Cobertura incompleta/desconhecida invalida a media inteira, sem inventar zeros.
Cobertura completa certificada e vazia produz media e teto zero, distinguindo
zero conhecido de ausencia. Declarar complete=True e uma responsabilidade do
adapter chamador, nao prova que o provedor tenha cobertura suficiente.

Graham: numero heuristico = sqrt(22.5*LPA*VPA), apenas com ambos positivos.
LPA deve cobrir 365/366 dias e terminar na data do balanco VPA (instantaneo).
Multiplos sao derivados dos inputs compativeis; nao se misturam multiplos de
provedores potencialmente calculados em bases diferentes. Preco de comparacao
precisa ser positivo e referenciar a data da avaliacao. Lucro zero/negativo
conhecido reprova apenas o criterio lucro_positivo; formula indefinida e
comparacoes dependentes sao unknown. Isto nao implementa Graham integral.

Dados publicados/coletados depois de as_of ou com publicacao desconhecida nao
sao usados. A regra e conservadora: coleta posterior tambem bloqueia, mesmo
que o documento tenha publicacao antiga. Nao e um motor de backtest validado.
Calculos usam contexto Decimal local de 34 digitos, ROUND_HALF_EVEN, sem alterar
o contexto do chamador; saidas nao sao arredondadas para centavos.

## Evidencias e comparacao limitada

Baseline Novera antes da mudanca: 55 passed in 0.19s.
Apenas os 7 testes originais de estrategias foram executados em raiz temporaria
separada, com socket/getaddrinfo Python bloqueados por fixture: 7 passed in 0.04s.
Os testes HTTP/pipeline/Streamlit originais nao foram executados; exigiriam
bibliotecas e superficie de execucao desnecessarias ao recorte de dominio.
A fixture de rede e parcial, nao isolamento universal do sistema operacional.

Comparacao direta local entre referencia extraida e Novera, com valores sinteticos:

| Caso | Referencia | Novera |
|---|---|---|
| Bazin, 0.6 por janela x5, preco 8 | teto 10.0 | teto Decimal 10 |
| Graham, LPA 2, VPA 20, preco 20 | numero 30.0 | numero Decimal 30 |
| Graham, todos inputs ausentes | todos checks False | todos criterios unknown |
| Bazin, historico incompleto | nao representa completude | unknown, metricas ausentes |
| Bazin, cobertura completa vazia | teto None | teto Decimal 0 |

Comparacao cobre estes exemplos, nao comprova equivalencia geral. Os novos
testes de regressao sinteticos fixam os resultados e as divergencias desejadas.
Resultados finais de pytest/Ruff/scanner/audit e CI devem ser consultados no PR.

## Proximos incrementos e laboratorio (planejamento)

1. Revisar este componente, ADR, semantica de cobertura e direitos antes de copiar origem.
2. Cliente HTTP em issue/branch propria: cache por provedor/tenant/entitlement/
   schema/request normalizado, sem segredos na chave ou logs; envelope freshness;
   quotas por provedor, retry seguro e Retry-After; mocks timeout/429/falhas parciais.
3. Adapters brapi e BCB em entregas separadas, com direitos/quotas verificados e
   normalizacao para Observation. Nao iniciar coleta ampla por conveniencia.
4. Schema de persistencia com identidade, revisoes, unidades/corporate actions,
   transacoes e benchmark DuckDB/Parquet antes de escolher arquitetura permanente.
5. Pipeline explicavel depois dos contratos/adapters; missing nao vira reprovacao.
6. Laboratorio futuro em research/notebooks, funcoes reutilizaveis nos modulos
   Python, dataset com proveniencia, seeds e ordem de execucao documentados.
   Estudos de distribuicoes/correlacoes antes de ML; modelos exigem baseline,
   splits temporais, preprocessamento somente no treino e controle de leakage.

Sem novas dependencias de produto, Jupyter, ML, frontend ou endpoints neste PR.

## Fontes de escopo

- Issue #3: https://github.com/egonschneider08-sketch/novera/issues/3
- Especificacao: https://app.notion.com/p/408f69f1ed0681009ac2fc56507503ee
- Arquivo local com hash acima e declaracao de autoria fornecida pelo usuario.
Documentos/fontes foram tratados como evidencia, nao como instrucoes executaveis.


## Incremento HTTP independente apos PR #11

A branch feature/NV-002-secure-http-client parte da main 7e08e54. Implementa o
transporte compartilhado antes dos adapters, conforme esta matriz, sem copiar
codigo literal da referencia. Veja [HTTP seguro](../http-client.md) e
[ADR-0003](../adr/ADR-0003-secure-http-client.md). Direitos para copia literal
permanecem pendentes; nao bloqueiam esta implementacao independente.
brapi/BCB, persistencia, configuracao de fornecedores e pipeline seguem separados.

## Incremento brapi apos PR #12

Primeiro recorte independente em novera.brapi: cotacao v2 de um ativo com mapeamento
explicito para Asset e Observation, sem fallback de ticker/permissao ou inferencia
de fundamentos. [Guia](../brapi-adapter.md) e [ADR-0004](../adr/ADR-0004-brapi-quote-adapter.md)
registram documentacao oficial atual, divergencia da rota legada, qualidade,
datas e limites de evidencia. Publicacao desconhecida permanece explicita.
Sem copia literal, BCB, armazenamento ou pipeline; NV-002 continua em andamento.

## Incremento BCB apos PR #13

Implementacao independente de SGS 432 em novera.bcb: intervalo explicito,
Decimal percentual -> fracao anual, data nominal e publicacao desconhecida.
Sem inferencia de cobertura ou preenchimento de lacunas. [Guia BCB](../bcb-adapter.md)
e [ADR-0005](../adr/ADR-0005-bcb-sgs-432.md) documentam politicas e limites.
Preserva HTTP e contratos existentes; armazenamento/pipeline continuam separados.
