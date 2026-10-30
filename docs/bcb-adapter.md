# NV-002: BCB SGS 432 — meta Selic

Implementacao independente em novera.bcb, base main 29963c0 apos PR #13.
[ADR-0005](adr/ADR-0005-bcb-sgs-432.md). Sem codigo literal da referencia.

## Fontes oficiais consultadas em 2026-10-30

- [Catalogo SGS 432](https://dadosabertos.bcb.gov.br/dataset/432-taxa-de-juros---meta-selic-definida-pelo-copom):
  meta Selic definida pelo Copom, serie diaria, percentual ao ano, inicio em
  1999-03-05; fonte Copom/SGS. Nao e a Selic efetiva diaria (outra serie).
- [Recurso JSON e contrato de consulta](https://dadosabertos.bcb.gov.br/dataset/432-taxa-de-juros---meta-selic-definida-pelo-copom/resource/2cb57a62-49de-405d-938b-482051a6e166):
  endpoint /dados/serie/bcdata.sgs.432/dados, formato=json e filtros
  dataInicial/dataFinal em dd/MM/aaaa. Aviso vigente desde 26/03/2025 limita
  consultas diarias a dez anos; ultimos/N limitado a 20. O adapter exige ambos
  os filtros e restringe ainda mais, a 366 dias inclusivos por chamada.
- O catalogo/recurso identificam a licenca dos dados como ODbL. Preservar fonte
  e revisar obrigacoes antes de redistribuir bases. Nao confundir com BSD-3-Clause
  do codigo Novera; este PR nao incorpora uma base de dados BCB.

Nao foi encontrada quota numerica de chamadas por segundo nas paginas consultadas.
Isso nao significa acesso ilimitado. Usar cliente compartilhado, configuracao
conservadora e respeitar 429/Retry-After. Nenhuma autenticacao e adicionada.

### Limites da verificacao externa

O extrator web omitiu a descricao do recurso; leitura direta do HTML oficial
confirmou rota, parametros e limites. A API de metadados CKAN retornou 403.
Duas consultas pontuais de um dia fora dos testes (28/10/2026 e 02/01/2023)
retornaram 400. Nenhum dado economico foi obtido, armazenado ou usado como fixture.
As falhas nao identificam se a causa era do provedor, proxy ou ambiente local.

O schema de resposta implementado e a projecao esperada SGS: array de objetos
com data dd/MM/aaaa e valor decimal textual com ponto. Esta consulta nao
revalidou esse formato por uma resposta de dados bem-sucedida. A implementacao
esta coberta por fixtures sinteticas, nao por certificacao de integracao real.
Confirmar o schema com uma amostra oficial bem-sucedida antes de ativar coleta.

## Interface

BcbAdapter recebe SecureHttpClient(provider="bcb", origin="https://api.bcb.gov.br"),
synthetic obrigatorio e clock now opcional. O chamador controla lifecycle,
politica HTTP e AccessContext; adapter nao fecha o cliente emprestado.
selic_target(Period, context=..., cache_policy=...) retorna JsonEnvelope[SgsWindow].
Nao aceita URL, codigo de serie ou headers arbitrarios.

| Entrada/estado | Representacao |
| --- | --- |
| valor="12.50" (sintetico) | Decimal("0.1250"), PRESENT, fraction/year |
| valor="0" | Decimal zero, PRESENT |
| valor ausente, null ou string vazia | None, MISSING, motivo fixo |
| negativo/tipo incorreto/NaN/comma/expoente/texto longo | None, INVALID, motivo fixo |
| data nominal valida | Period(data, data), sem inventar horario |
| coleta | envelope.fetched_at original |
| publicacao | None, sgs_publication_time_not_provided |
| identidade | Asset("bcb.sgs", "432"), indicador selic_target |
| fonte | BCB, URL publica da consulta, versao bcb-sgs-432-v1, synthetic |
| moeda | None: a taxa e uma fracao anual, nao um montante BRL |

Conversao exata por deslocamento de duas casas decimais; nao arredonda conforme
o contexto Decimal do chamador. Limite local de 64 caracteres no numero textual.
Negativos sao rejeitados como politica especifica da meta Selic nesta versao,
nao como regra universal de juros. Fracoes acima de 1 nao sao truncadas.

observations e uma tupla ordenada apenas com datas retornadas pelo provedor.
unreturned_dates lista as demais datas do intervalo calendario solicitado.
Isso nao significa falha do provedor em cada feriado/final de semana nem prova
de cobertura completa quando a lista esta vazia. Nao ha forward-fill, interpolacao,
annualizacao adicional, retorno diario ou inferencia da vigencia de uma decisao.
Lista vazia preserva todas as datas como nao retornadas; nao cria observacoes zero.

Data invalida, ausente, duplicada ou fora do intervalo, linha nao-objeto e envelope
nao-array geram FetchError INVALID_RESPONSE antes de cachear qualquer linha.
Datas repetidas sao rejeitadas mesmo com valores iguais; nao ha politica de revisoes.
Campos extras nao sao preservados. Invalidade numerica conserva a linha/data
com qualidade INVALID para nao perder uma falha parcial conhecida.

Period exige datas Python, nao datetime. Consulta futura e rejeitada comparando
fim com a data UTC do clock consciente de fuso; essa e uma guarda local, nao um
calendario de divulgacao BCB. O cliente e o adapter devem usar clocks coerentes.
Nao ha limite inferior artificial para a consulta; datas sem registros retornam
lacunas se o provedor responder 200 com array vazio.

## Transporte e stale

Timeout, retries, jitter, 429, rate limiting, cache e invalidacao pertencem ao
SecureHttpClient. Sem loops extras ou particionamento automatico de janelas.
O envelope conserva freshness, fetched_at, age_seconds, attempts, stale_reason e
failure_status. Stale exige opt-in; nao renova Provenance.collected_at e nao prova
atualidade economica. Falhas estruturais/HTTP definitivas nao servem stale.
404/204 nao viram MISSING ou array vazio. Segregacao por tenant/entitlement/revisao
e periodo herdada do HTTP; schema inclui synthetic. Sem tokens ou segredos.

## Exemplo offline

```python
from datetime import date, datetime, timezone
from decimal import Decimal
import httpx
from novera.bcb import BcbAdapter
from novera.contracts import Period
from novera.http import AccessContext, RetryPolicy, SecureHttpClient

def now():
    return datetime(2026, 10, 30, 12, tzinfo=timezone.utc)

with SecureHttpClient(
    "bcb", "https://api.bcb.gov.br", now=now,
    policy=RetryPolicy(min_interval=1),
    transport=httpx.MockTransport(lambda request: httpx.Response(
        200, json=[{"data": "28/10/2026", "valor": "12.50"}],
    )),
) as client:
    result = BcbAdapter(client, synthetic=True, now=now).selic_target(
        Period(date(2026, 10, 28), date(2026, 10, 28)),
        context=AccessContext("demo-user", "public-sgs", "revision-1"),
    )
    assert result.data.observations[0].value == Decimal("0.1250")
    assert result.data.observations[0].provenance.source.synthetic
```

Intervalo de 1 segundo e escolha conservadora do exemplo, nao quota oficial.

## Validacao e handoff

Comandos: uv run --offline --locked pytest -q; Ruff check/format --check;
python scripts/check_secrets.py e --self-test via uv locked; uv export --locked
--all-groups --no-emit-project --no-hashes para temporario e pip-audit --no-deps
--disable-pip -r desse arquivo. Nao ha tipagem estatica configurada.
Mocks bloqueiam DNS/connect Python; nao representam isolamento universal do SO.
CI nao faz consultas BCB; instalacao/auditoria consultam indices/advisories.

Baseline 277 passed in 1.18s. Ruff ajustou ordenacao de imports. Execucoes locais
iniciais foram interrompidas por demora; faulthandler apontou criacao de symlink
temporario no pytest/Windows, antes de um teste tmp_path. Resultados finais,
comando de reexecucao, commit, PR e CI estao no handoff e no PR.

Proximos bloqueios: revisao humana; resposta oficial bem-sucedida para confirmar
wire schema; calendario/completude/revisoes e publicacao antes de uso point-in-time;
direitos ODbL antes de redistribuicao. NV-002 continua aberta. Persistencia,
pipeline e frontend exigem entregas proprias. Sem copia literal da referencia.

### Handoff para o Notion — evidencia local

Branch feature/NV-002-bcb-sgs-adapter, base main 29963c0. Em revisao, nao concluido.
Reexecucao integral: uv run --offline --locked pytest -q --basetemp <novo diretorio
temporario exclusivo> => **329 passed in 129.62s**, incluindo 52 casos BCB.
O caminho novo foi verificado como inexistente antes da chamada. A opcao nao
desabilita testes; criacao de symlinks temporarios ainda causou demora local.
As duas execucoes anteriores interrompidas nao contam como aprovadas.

Ruff check: All checks passed; Ruff format --check: 14 files already formatted.
Scanner: 0 achados; controle negativo: 1 achado sintetico, negative control passed.
git diff --cached --check: exit 0. Exemplo offline acima executado com guard
DNS/connect: aprovado. Export do lock: 40 pacotes; pip-audit: No known
vulnerabilities found. Aviso de export sem hashes mantido, nenhum advisory ignorado.
Resultados remotos, SHA final e links do PR/CI serao anexados ao PR e a pagina
NV-002 do Notion apos publicacao. Esses links nao representam aceite ou merge.
