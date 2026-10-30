# NV-010 — Comparação e exportação auditáveis (primeiro recorte sintético)

**Esta entrega NÃO é um ranking financeiro.** São três casos fictícios de
pesquisa já implementados na [NV-024](research-demo.md), comparados com
critérios didáticos e origem integralmente rastreável. A tarefa NV-010
continua em andamento: rankings/exports de investimentos reais exigem
comparabilidade e regras de dados que ainda não existem.

## Objetivo da experiência

O usuário consegue selecionar entre um e três cenários fictícios, observar os
estados das duas heurísticas e baixar dados estruturados por uma ferramenta
de terminal. A ordem de exibição é aquela informada, **não** um cálculo
de qualidade, potencial de retorno ou atratividade de investimento.

```sh
uv run --offline --locked python -m novera.research_compare --format text
uv run --offline --locked python -m novera.research_compare --format json
uv run --offline --locked python -m novera.research_compare --format csv
uv run --offline --locked python -m novera.research_compare --scenario incomplete --scenario complete --format json
```

Esses comandos não contatam provedores e não criam arquivo automaticamente.
No PowerShell, redirecionar para um arquivo é uma ação **explícita** do
usuário; conferir encoding UTF-8 ao exportar documentos com acentos.

## Origem e algoritmo de apresentação

```text
Seleção explícita de 1–3 cenários pertencentes à allowlist
    ↓
run_scenario: SQLite em memória, leitura de Observations, Bazin/Graham
    ↓
ComparisonReport — ordem de seleção, sem pontuação comparativa
    ↓
Texto (vista geral), JSON (proveniência completa), CSV (linhas de regras e métricas)
```

- Seleção vazia, nomes fora da allowlist e duplicatas são recusados.
- Uma comparação usa exatamente a mesma referência temporal e convenção
  de share basis em todos os cenários produzidos pela fixture.
- Cada `StrategyResult` mantém versão, estado e razões individuais;
  UNKNOWN não é convertido em FAIL nem excluído para melhorar uma posição.
- Todos os valores financeiros calculados são `Decimal`, apresentados
  em **strings**, nunca número binário JSON. Dados faltantes ficam
  `null` no JSON e campo vazio com `quality=missing` no CSV.
- O JSON de comparação `novera-synthetic-comparison-v1` inclui os
  relatórios detalhados de `novera-synthetic-research-v1`, com
  referências, fontes, períodos, datas, quality, recibos, versões
  e cobertura de proventos declarada somente pelas fixtures.
- O CSV tem linhas `metric` e `criterion`: colunas explícitas
  `row_type`, `quality`, `criterion_state`, `rule_version`,
  `receipt_ids`, `source` e `synthetic=true`, além de disclaimer.
  Números ausentes permanecem em branco, **não zero**.
- O CSV só contém células derivadas de fixtures e constantes internas,
  não texto de usuário ou provedores; uma exportação geral de dados
  externos precisará de defesa contra formula injection e revisão de
  direitos/consentimento.

## Limites de uso

A comparação não atribui notas, recomendação de compra/venda, ranking de
rentabilidade, risco ou referência B3; nem cria API, scheduler, frontend
ou exposição comercial de dados. Não confundir três cenários inventados
com cobertura histórica real de Bazin, EPS/BVPS verificados ou retorno
de empresas brasileiras. A infraestrutura de ingestão brapi/BCB
continua separada e sujeita aos termos de dados dos provedores.

## Testes e decisão de roadmap

`backend/tests/test_research_compare.py` cobre seleção, duplicatas,
estados diferentes, JSON/CSV sem float, quality, recibos, textos,
reprodução determinística, rejeição de uso real e execução em subprocesso
do entrypoint instalado. Só usa dados sintéticos; não há chamadas de rede
nem arquivos persistentes nos testes.

A aprovação deste recorte **não conclui NV-010 inteira**. Depois da
NV-011 (interface inicial) e de uma fonte financeira historicamente
certificada, avaliar regras de comparação por data-base, moeda, versão,
ativo, missing e conformidade. Antes disso, somente experimentos sintéticos.
