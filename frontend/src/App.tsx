import { useMemo, useState, type KeyboardEvent } from "react";
import fixture from "./data/scenarios.json";
import comparisonCsv from "./data/comparison.csv?raw";
import {
  displayValue,
  parseComparison,
  scenarioLabels,
  stateLabels,
  type EvaluationState,
  type ResearchReport,
  type Strategy,
} from "./contracts";
import "./styles.css";

type Method = "graham" | "bazin";
type ViewMode = "demo" | "empty" | "stale" | "error";

const metricLabels: Record<string, string> = {
  graham_number: "Número de Graham",
  bazin_ceiling: "Preço-teto Bazin",
  pe: "Preço / Lucro",
  pb: "Preço / Valor patrimonial",
  margin: "Margem estimada (razão)",
  annual_average: "Proventos médios anuais",
  yield_365d: "Yield últimos 365 dias",
};
const methodLabels: Record<Method, string> = {
  graham: "Benjamin Graham",
  bazin: "Décio Bazin",
};
const modes: { value: ViewMode; label: string }[] = [
  { value: "demo", label: "Demonstração" },
  { value: "empty", label: "Sem dados" },
  { value: "stale", label: "Desatualizado (simulado)" },
  { value: "error", label: "Erro (simulado)" },
];

function StateTag({ state, compact = false }: { state: EvaluationState; compact?: boolean }) {
  return (
    <span className={`state-tag state-${state}${compact ? " compact" : ""}`}>
      <span aria-hidden="true" className="state-dot" />
      {stateLabels[state]}
    </span>
  );
}

function download(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function MethodTab({
  method, selected, onClick, onKeyDown,
}: {
  method: Method;
  selected: boolean;
  onClick: () => void;
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      type="button"
      id={`tab-${method}`}
      role="tab"
      aria-controls="method-panel"
      aria-selected={selected}
      tabIndex={selected ? 0 : -1}
      className={`method-tab ${selected ? "active" : ""}`}
      onClick={onClick}
      onKeyDown={onKeyDown}
    >
      {methodLabels[method]}
    </button>
  );
}

function Evidence({ report }: { report: ResearchReport }) {
  return (
    <section className="panel evidence-panel" aria-labelledby="evidence-title">
      <div className="section-heading">
        <div>
          <p className="eyebrow">TRANSPARÊNCIA</p>
          <h2 id="evidence-title">Dados e proveniência</h2>
          <p className="section-description">
            Registros recuperados do SQLite em memória. Todas as fontes abaixo são artificiais.
          </p>
        </div>
        <span className="tiny-count">{report.observations.length} observações</span>
      </div>
      <div className="table-viewport" tabIndex={0} role="region" aria-label="Tabela de observações com rolagem horizontal">
        <table>
          <thead>
            <tr>
              <th scope="col">Informação</th>
              <th scope="col">Valor</th>
              <th scope="col">Qualidade</th>
              <th scope="col">Período de referência</th>
            </tr>
          </thead>
          <tbody>
            {report.observations.map((observation) => (
              <tr key={observation.receipt_id}>
                <th scope="row">{observation.metric.replaceAll("_", " ")}</th>
                <td className="numeric-cell">
                  {displayValue(observation.value, observation.unit)}
                </td>
                <td>
                  <span className={observation.quality === "present" ? "quality-present" : "quality-missing"}>
                    {observation.quality === "present" ? "Presente" : "Ausente / não avaliável"}
                  </span>
                </td>
                <td className="mono-cell">
                  {observation.reference_period.start} — {observation.reference_period.end}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <details className="provenance-details">
        <summary>
          <span>Inspecionar origem, versões e recibos</span>
          <span aria-hidden="true">＋</span>
        </summary>
        <div className="provenance-list">
          {report.observations.map((obs) => (
            <div className="provenance-item" key={obs.receipt_id}>
              <strong>{obs.record_key}</strong>
              <dl>
                <div><dt>Provedor</dt><dd>{obs.source.provider} — sintético</dd></div>
                <div><dt>Versão</dt><dd>{obs.source.rule_version} / registro {obs.version}</dd></div>
                <div><dt>Publicado</dt><dd>{obs.published_at ?? "Desconhecido"}</dd></div>
                <div><dt>Coletado</dt><dd>{obs.collected_at}</dd></div>
                <div><dt>Recibo SHA-256</dt><dd className="hash">{obs.receipt_id}</dd></div>
                <div><dt>Referência</dt><dd>{obs.source.reference}</dd></div>
              </dl>
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}

function Analysis({ report, method, onMethodChange }: {
  report: ResearchReport;
  method: Method;
  onMethodChange: (method: Method) => void;
}) {
  const strategy: Strategy | undefined = report.strategies.find((item) =>
    method === "graham"
      ? item.methodology === "graham-number-partial"
      : item.methodology === "bazin-five-365-day-windows"
  );
  if (!strategy) return <p role="alert">A metodologia selecionada não existe nesta demonstração.</p>;

  function onTabKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const next: Method = method === "graham" ? "bazin" : "graham";
    onMethodChange(next);
    document.getElementById(`tab-${next}`)?.focus();
  }
  const passed = strategy.criteria.filter((item) => item.state === "pass").length;
  const failed = strategy.criteria.filter((item) => item.state === "fail").length;
  const unknown = strategy.criteria.filter((item) => item.state === "unknown").length;

  return (
    <section className="panel analysis-panel" aria-labelledby="analysis-heading">
      <div className="analysis-header">
        <div>
          <p className="eyebrow">METODOLOGIAS</p>
          <h2 id="analysis-heading">Análise fundamentalista</h2>
          <p className="section-description">
            Heurísticas didáticas independentes, com justificativas verificáveis.
          </p>
        </div>
        <div className="tabs" role="tablist" aria-label="Método de avaliação">
          <MethodTab method="graham" selected={method === "graham"} onClick={() => onMethodChange("graham")} onKeyDown={onTabKeyDown} />
          <MethodTab method="bazin" selected={method === "bazin"} onClick={() => onMethodChange("bazin")} onKeyDown={onTabKeyDown} />
        </div>
      </div>
      <div id="method-panel" role="tabpanel" aria-labelledby={`tab-${method}`} tabIndex={0}>
        <div className="method-summary">
          <div>
            <p className="fine-label">RESULTADO DO MÉTODO</p>
            <h3>{methodLabels[method]}</h3>
            <p className="rule-id">Regra: {strategy.rule_version}</p>
          </div>
          <StateTag state={strategy.state} />
        </div>

        <div className="stat-tiles">
          {strategy.metrics.slice(0, 4).map((metric) => (
            <div className="stat-tile" key={metric.name}>
              <p>{metricLabels[metric.name] ?? metric.name.replaceAll("_", " ")}</p>
              <strong className={metric.value === null ? "metric-missing" : ""}>
                {displayValue(metric.value, metric.unit)}
              </strong>
              <span>{metric.quality === "present" ? "Dado calculado" : "Ausente · não inferido"}</span>
            </div>
          ))}
        </div>
        {strategy.metrics.length > 4 && (
          <details className="extras-details">
            <summary>Exibir outras {strategy.metrics.length - 4} métricas e janelas</summary>
            <div className="extra-metrics">
              {strategy.metrics.slice(4).map((metric) => (
                <div key={metric.name}>
                  <span>{metric.name.replaceAll("_", " ")}</span>
                  <strong>{displayValue(metric.value, metric.unit)}</strong>
                </div>
              ))}
            </div>
          </details>
        )}

        <div className="criteria-heading">
          <div>
            <h3>Critérios analisados</h3>
            <p>Cada resultado mantém sua própria justificativa.</p>
          </div>
          <div className="criteria-count" aria-label={`${passed} atendidos, ${failed} não atendidos, ${unknown} não avaliáveis`}>
            <span className="pass-count">{passed} atendidos</span>
            <span className="fail-count">{failed} não atendidos</span>
            <span className="unknown-count">{unknown} sem avaliação</span>
          </div>
        </div>
        <ul className="criteria-list">
          {strategy.criteria.map((criterion) => (
            <li className="criterion" key={criterion.name}>
              <div className="criterion-body">
                <strong>{criterion.name.replaceAll("_", " ")}</strong>
                <p>{criterion.reason}</p>
              </div>
              <StateTag state={criterion.state} compact />
            </li>
          ))}
        </ul>
        <p className="methodology-note">
          Estados indicam somente o atendimento a critérios didáticos, não a qualidade de uma empresa ou oportunidade de investimento.
        </p>
      </div>
    </section>
  );
}

function Placeholder({ mode }: { mode: "empty" | "error" }) {
  const error = mode === "error";
  return (
    <section className="panel placeholder" aria-live="polite">
      <div className="placeholder-icon" aria-hidden="true">{error ? "!" : "∅"}</div>
      <p className="eyebrow">SIMULAÇÃO DA INTERFACE</p>
      <h2>{error ? "Não foi possível carregar os dados" : "Nenhum dado disponível"}</h2>
      <p>
        {error
          ? "Esta é uma simulação de erro de leitura. Nenhum número financeiro foi exibido ou preenchido artificialmente."
          : "Este estado representa um resultado vazio. Ausência de dados não significa retorno zero nem critério reprovado."}
      </p>
      <span className="placeholder-hint">Escolha “Demonstração” no seletor lateral para retornar aos cenários fictícios.</span>
    </section>
  );
}

export function App({ data = fixture, enableCsvExport = true }: { data?: unknown; enableCsvExport?: boolean }) {
  const parsed = useMemo(() => parseComparison(data), [data]);
  const [scenario, setScenario] = useState("complete");
  const [method, setMethod] = useState<Method>("graham");
  const [mode, setMode] = useState<ViewMode>("demo");

  if (!parsed.ok) {
    return (
      <main className="fatal-error" role="alert">
        <div className="fatal-logo">N</div>
        <h1>Não foi possível validar a demonstração</h1>
        <p>{parsed.error}</p>
        <p>O Novera bloqueia dados com origem não verificada, schema incompatível ou ausência confundida com zero.</p>
      </main>
    );
  }

  const comparison = parsed.value;
  const report = comparison.reports.find((entry) => entry.scenario === scenario) ?? comparison.reports[0];
  const price = report.observations.find((item) => item.metric === "close");
  const isVisible = mode === "demo" || mode === "stale";
  const isStale = mode === "stale";

  return (
    <div className="app">
      <div className="demo-ribbon" role="note">
        <span className="ribbon-dot" aria-hidden="true" />
        AMBIENTE DE DEMONSTRAÇÃO — DADOS 100% FICTÍCIOS · SEM COTAÇÕES REAIS
      </div>
      <header className="topbar">
        <a className="wordmark" href="#inicio" aria-label="Novera, início">
          <span className="brand-mark" aria-hidden="true"><span>ᐱ</span></span>
          <span className="brand-name">novera<span>.</span></span>
        </a>
        <div className="topbar-right">
          <span className="topbar-context">Plataforma de pesquisa</span>
          <a href="https://github.com/egonschneider08-sketch/novera/blob/main/docs/research-demo.md"
             target="_blank" rel="noreferrer" className="docs-link">Documentação <span aria-hidden="true">↗</span></a>
          <span className="lab-avatar" aria-label="Ambiente LAB">LAB</span>
        </div>
      </header>
      <div className="layout">
        <aside className="sidebar" aria-label="Navegação de pesquisa">
          <div className="sidebar-group">
            <p className="sidebar-overline">WORKSPACE</p>
            <div className="current-page"><span aria-hidden="true">◈</span> Visão de pesquisa</div>
          </div>
          <div className="sidebar-group scenarios-group">
            <div className="sidebar-group-heading">
              <p className="sidebar-overline">ATIVOS FICTÍCIOS</p>
              <span className="tiny-count">03</span>
            </div>
            <div className="scenario-nav" aria-label="Escolher ativo fictício">
              {comparison.reports.map((item) => (
                <button key={item.scenario} type="button"
                  className={`scenario-button ${item.scenario === report.scenario ? "selected" : ""}`}
                  aria-current={item.scenario === report.scenario ? "true" : undefined}
                  onClick={() => setScenario(item.scenario)}>
                  <span className="scenario-symbol" aria-hidden="true">{item.asset.identifier.slice(-1)}</span>
                  <span className="scenario-copy">
                    <strong>{item.asset.identifier}</strong>
                    <small>{scenarioLabels[item.scenario]}</small>
                  </span>
                  {item.scenario === report.scenario && <span className="scenario-active-dot" aria-hidden="true" />}
                </button>
              ))}
            </div>
          </div>
          <div className="sidebar-group view-group">
            <label htmlFor="view-select" className="sidebar-overline">SIMULAR ESTADO DA TELA</label>
            <select id="view-select" value={mode} onChange={(event) => setMode(event.target.value as ViewMode)}>
              {modes.map((entry) => <option value={entry.value} key={entry.value}>{entry.label}</option>)}
            </select>
            <p className="sidebar-help">Teste vazio, erro e stale sem conectar fornecedores.</p>
          </div>
          <div className="sidebar-footer">
            <div className="sidebar-info-icon" aria-hidden="true">i</div>
            <div><strong>Ambiente isolado</strong><span>Sem contas, API externa ou dados reais.</span></div>
          </div>
        </aside>
        <main id="inicio" className="main-content">
          <div className="breadcrumb">Laboratório <span>/</span> Pesquisa fundamentalista <span>/</span> <strong>{report.asset.identifier}</strong></div>
          <div className="page-top">
            <div>
              <p className="eyebrow">VISÃO DE PESQUISA <span className="eyebrow-separator">/</span> EDIÇÃO LAB</p>
              <h1>Pesquisa com <em>evidências.</em></h1>
              <p className="intro">Uma visão clara de dados, metodologias e limites — antes de qualquer decisão.</p>
            </div>
            <span className="simulation-badge"><span aria-hidden="true">◌</span> 100% sintético</span>
          </div>

          {isStale && (
            <div className="alert-banner stale-banner" role="status">
              <strong>Visualização desatualizada — simulação.</strong>
              <span>Os registros abaixo são apenas um exemplo de tela stale. Nenhum dado foi consultado agora; as exportações ficam bloqueadas.</span>
            </div>
          )}
          {!isVisible ? (
            <Placeholder mode={mode} />
          ) : (
            <>
              <section className="asset-hero" aria-labelledby="asset-title">
                <div className="asset-hero-main">
                  <span className="asset-symbol-icon" aria-hidden="true">{report.asset.identifier.slice(-1)}</span>
                  <div>
                    <p className="fine-label hero-eyebrow">PESQUISA · ATIVO SIMULADO</p>
                    <h2 id="asset-title" aria-live="polite">{report.label}</h2>
                    <div className="asset-tags">
                      <span className="ticker">{report.asset.identifier}</span>
                      <span>BRL · Brasil (cenário)</span>
                      <span>Ref. {report.as_of.slice(0, 10)}</span>
                    </div>
                  </div>
                </div>
                <div className="hero-quote">
                  <p>PREÇO FICTÍCIO DE FECHAMENTO</p>
                  <strong>{displayValue(price?.value ?? null, "currency/share")}</strong>
                  <span>Base por ação: {report.share_basis}</span>
                </div>
              </section>

              <section className="context-strip" aria-label="Indicadores de origem">
                <div><span className="strip-icon" aria-hidden="true">◈</span><span><small>Fonte</small><strong>Fixture Python verificada</strong></span></div>
                <div><span className="strip-icon" aria-hidden="true">▦</span><span><small>Registros</small><strong>{report.observations.length} observações</strong></span></div>
                <div><span className="strip-icon" aria-hidden="true">◎</span><span><small>Disponibilidade</small><strong>{report.dividend_coverage_certified_by_fixture ? "Cobertura fictícia declarada" : "Cobertura não certificada"}</strong></span></div>
              </section>

              <Analysis report={report} method={method} onMethodChange={setMethod} />
              <Evidence report={report} />

              <section className="export-panel" aria-label="Exportação de pesquisa">
                <div className="export-copy">
                  <span className="export-icon" aria-hidden="true">↓</span>
                  <div>
                    <h2>Leve a evidência com você</h2>
                    <p>Arquivos estritamente demonstrativos, com origem, data e versão.</p>
                  </div>
                </div>
                <div className="export-actions">
                  <button type="button" disabled={isStale} className="secondary-button"
                    onClick={() => download(`novera-${report.scenario}-ficticio.json`, JSON.stringify(report, null, 2), "application/json;charset=utf-8")}>
                    ↓ JSON do ativo
                  </button>
                  <button type="button" disabled={isStale || !enableCsvExport} className="primary-button"
                    title={enableCsvExport ? "Exportação de cenários fictícios gerados pelo Python" : "CSV incorporado desativado enquanto a API é a origem dos dados"}
                    onClick={() => download("novera-cenarios-ficticios.csv", comparisonCsv, "text/csv;charset=utf-8")}>
                    ↓ {enableCsvExport ? "CSV dos cenários" : "CSV apenas no snapshot"}
                  </button>
                </div>
              </section>
            </>
          )}
          <footer className="page-footer">
            <div><strong>novera<span>.</span></strong> <span>Laboratório de pesquisa · NV-011</span></div>
            <p>{comparison.disclaimer} Não há recomendações, negociações ou acesso ao mercado nesta versão.</p>
          </footer>
        </main>
      </div>
    </div>
  );
}

export default App;
