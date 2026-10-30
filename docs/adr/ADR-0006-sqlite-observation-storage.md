# ADR-0006 — SQLite local para observações financeiras versionadas

Status: **proposto para revisão da NV-009**. Data: 2026-10-30.

## Contexto

O Novera já possui contratos financeiros e adaptadores brapi e BCB, mas não possui
um repositório persistente, nem direito presumido de redistribuir dados de
terceiros. A primeira necessidade é guardar `Observation`/`Provenance` sem
perder metadados, idempotência e evidências de revisão, sempre offline no teste.

## Decisão

Adotar **SQLite (biblioteca padrão do Python)** apenas para persistência local,
com instância por escopo de autorização e thread; `MemoryCache` HTTP não é o banco.

| Critério | SQLite escolhido | DuckDB não selecionado agora |
| --- | --- | --- |
| Transações | ACID, `BEGIN IMMEDIATE`, rollback | Transações disponíveis, porém novo runtime |
| Distribuição | Sem dependências adicionais | Dependência de runtime adicional |
| Escritas e identidade | Chaves/índices/FK/UNIQUE nativos | Melhor foco em consultas colunares analíticas |
| Concorrência | Um escritor; sem coordenação distribuída | Não substitui serviço transacional multiusuário |
| Consulta analítica | Adequada a recorte inicial pequeno | Vantagem em workloads colunares e volumes altos |
| Evolução | Migrações explícitas por versão do schema | Pode ser introduzido como camada analítica posterior |

Armazenar duas estruturas relacionais: `versions` identifica uma versão econômica
imutável (`logical_id`, `content_id`); `collections` guarda os recibos de coleta
(`receipt_id`) e o payload completo, mantendo a história de proveniência. O
fingerprint econômico exclui somente `collected_at` e URL de referência; alterações
financeiras, datas de referência, valor, qualidade, regra ou publicação produzem
nova versão. Captura posterior da mesma versão gera outro recibo, não outro
valor econômico. Uma revisão para conteúdo anterior retorna sua versão histórica.

O `StorageScope` (tenant, entitlement, credential_revision) e o marcador
`synthetic` são explícitos e fixos na instância; toda consulta filtra ambos.
Essas identidades são fornecidas pela camada autenticada, não constituem
mecanismo de autenticação. Não se persistem tokens nem referências com parâmetros
de URL desconhecidos. Somente URLs HTTPS de fonte pública e parâmetros de consulta
estritamente permitidos são aceitos.

O valor `Decimal` é serializado como string e reconstruído exatamente. Datas e
horários preservam o offset timezone e os enums são revalidados antes de salvar
ou ao ler. Registro sem publicação continua explicitamente desconhecido.

A API de consulta retorna **todas as versões/recibos** que correspondam ao filtro,
sem inferir a versão mais recente nem limitar resultados por decisão financeira.

## Segurança, limites e consequências

- API síncrona para conexão/thread única; não é armazenamento para múltiplos
  processos/usuários em produção. Banco sem criptografia em repouso nativa.
- Banco local exige caminho absoluto, criação exclusiva e esquema conhecido.
  Nenhuma migração implícita, nenhuma sobrescrita de arquivo existente.
- SQL parametrizado, operações em lote transacionais e validação de integridade
  ao consultar. Hashes detectam alterações acidentais sem recomputação do hash,
  mas **não garantem prova criptográfica contra invasor com escrita total**.
- `query` lista recibos e revisões; consumidores que precisem de `latest` devem
  definir política explícita, inclusive disponibilidade point-in-time.
- Isolamento de leitura depende da camada de serviço não expor arquivos SQLite
  diretamente e autorizar abertura de escopos. Não usar em infraestrutura
  multi-tenant sem fronteiras de segurança adicionais.
- `record_key` precisa ser um identificador estável fornecido pela aplicação,
  e não ticker ou timestamp arbitrário. Retornar ao mesmo conteúdo anterior
  reutiliza a versão conhecida, não cria uma versão numérica nova.
- Repositório não realiza coleta, não armazena token, não agenda chamadas e não
  libera redistribuição de dados brapi/BCB.

## Alternativas e rollback

PostgreSQL exige serviço e política de autorização ainda não projetados.
DuckDB/Parquet será reconsiderado para snapshots analíticos volumosos após
benchmarks. Para reverter este incremento, remover `novera.storage` e seus testes
sem migração no banco dos usuários: **nenhum dado real foi ingerido**.

## Testes e aceite

Testar reabertura, precisão Decimal, todos os estados Quality, revisões,
coleções repetidas, SQL injection, isolamento entre escopos, rollback,
inspeção de schema, adulteração de payload e round-trip dos contratos
BCB/brapi com MockTransport. CI não solicita dados de mercado.
