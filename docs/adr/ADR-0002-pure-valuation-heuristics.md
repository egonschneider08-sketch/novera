# ADR-0002: heuristicas puras e estados nao avaliaveis

Status: proposto para revisao NV-002. Data: 2026-10-29.

## Contexto
A referencia usa floats, scores booleanos e ausencia como zero/False. O Novera
ja tem contratos rastreaveis; estes nao devem ser substituidos por outro snapshot.
O recorte solicitado e Bazin/Graham como dominio independente de HTTP/DB/UI.

## Decisao
Implementar independentemente duas funcoes puras sobre Observation e wrappers
imutaveis de ajuste por acao, eventos e cobertura. Resultado com regra versionada,
parametros explicitos, evidencia, metricas e criterios pass/fail/unknown.
Qualquer criterio unknown torna o estado global unknown; criterios fail
conhecidos continuam visiveis separadamente. Nao calcular score/ranking.

Bazin-cash-v1 preserva cinco janelas de 365 dias e yield alvo configuravel.
Somente cobertura completa certificada permite interpretar janelas sem eventos
como zero. Eventos futuros ficam excluidos; duplicatas ou dados realizados
invalidos tornam historico nao avaliavel. Sem conversao gross/net ou splits.
Cobertura completamente vazia gera teto zero, diferente de ausencia de historico.
Comparacao ultimos/primeiros dividendos nao significa crescimento monotonico.

Graham-number-v1 usa sqrt(22.5*LPA*VPA) para positivos. Exige LPA anual
365/366 dias terminando no balanco VPA. Deriva P/L e P/VP em vez de misturar
multiplos externos. Dados ausentes/invalidos/incompativeis nao reprovam regra;
EPS conhecido zero/negativo reprova a regra de lucro positivo, mantendo numero
heuristico e comparacoes dependentes nao avaliaveis. Nao equivale a Graham integral.
Preco deve ser positivo e da data de avaliacao para comparacoes; a heuristica
fundamental pode existir sem preco. Sem preenchimento de ultimo dia negociado.

as_of obrigatorio com fuso, dia de referencia UTC. Publicacao desconhecida ou
conhecimento/publicacao posterior nao habilitam calculo. Decimal com contexto
proprio (34 digitos, ROUND_HALF_EVEN); erros de faixa viram unknown.

## Alternativas
Anos civis mudariam janelas da referencia sem base suficiente nesta entrega.
Somar apenas anos observados ou imputar zeros produziria vies de cobertura.
Migrar scores diretamente penalizaria indisponibilidade e esconderia limites.
Copiar codigo original aguarda autorizacao especifica de licenciamento; nao
impede implementacao independente das formulas fornecidas.

## Consequencias
Entradas mais exigentes podem impedir avaliar dados atualmente disponiveis nas
APIs. Adapters precisam certificar cobertura, identificadores e ajustes de forma
verificavel. Nao ha garantia automatica de completude, ausencia de revisoes
futuras, validacao de corporate actions, atualidade dos fundamentos ou cobertura
historica. Nao ha conversao de moedas/unidades, taxonomia CVM ou recomendacao.
Novas regras de calendario, arredondamento, staleness ou metodologia exigem
nova versao e testes. Derivados usam evidencia do resultado, sem fabricar data
de publicacao de um registro de fornecedor.

## Evidencias
Auditoria: docs/migrations/winning-investments-v2.md. Testes sinteticos em
backend/tests/test_strategies.py; baseline original isolado e comparacao numerica
limitada, documentados separadamente. Comandos/resultados finais no PR NV-002.

## Rollback
Reverter commits desta entrega; nenhum schema, dado persistido ou API alterado.
