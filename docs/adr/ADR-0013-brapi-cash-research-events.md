# ADR-0013 — separar eventos brapi de pagamentos financeiros

Status: proposto · Data: 2026-11-04 · Issue: #33 / NV-027

## Contexto

O endpoint de proventos fornece datas e valores, sem certificar recebimento,
completude do histórico, moeda ou disponibilidade histórica dos dados. O contrato
Observation de caixa usado por estratégias não deve ganhar significado falso.

## Decisão

Criar DTO imutável de pesquisa em `brapi_dividends.py`, separado de Observation e
sem entrada no pipeline/Bazin. Usar transporte existente e validação antes do cache.
Retornar explicitamente pagamento não verificado, cobertura desconhecida e valores
sem base de ajuste certificada. Rejeitar conversão de ticker e duplicação ambígua.

## Alternativas

Converter diretamente em cash_distribution facilitaria persistência, mas trataria
um anúncio como fluxo realizado. Reaproveitar somente payload bruto perderia
validação, tipos, precisão e limites de consumo.

## Consequências

Nenhuma nova dependência, rota ou migração. Operação real exige verificação
contratual e validação externa. A limitação de janela/eventos pode rejeitar históricos
legítimos grandes; dividir consultas exige futura política explícita de cobertura.

## Evidência e rollback

Testes offline e documentação em `docs/brapi-dividends.md`; evidência de CI no PR.
Rollback: remover módulo, testes e referências; nenhum dado persistente é alterado.
