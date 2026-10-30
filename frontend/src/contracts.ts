/** Fail-closed boundary for checked-in Python-generated synthetic research JSON. */
export type EvaluationState = "pass" | "fail" | "unknown";
export type DataQuality = "present" | "missing" | "invalid" | "not_applicable";
export type ScenarioName = "complete" | "expensive" | "incomplete";

export interface Observation {
  record_key: string;
  receipt_id: string;
  version: number;
  metric: string;
  kind: string;
  value: string | null;
  quality: DataQuality;
  reason: string | null;
  unit: string;
  currency: string | null;
  reference_period: { start: string; end: string };
  source: { provider: string; reference: string; rule_version: string; synthetic: true };
  collected_at: string;
  published_at: string | null;
  publication_unknown_reason: string | null;
}

export interface Metric {
  name: string;
  value: string | null;
  quality: "present" | "missing";
  unit: string;
  currency: string | null;
  period: { start: string; end: string };
  reason: string;
}

export interface Strategy {
  methodology: string;
  rule_version: string;
  state: EvaluationState;
  as_of: string;
  synthetic: true;
  coverage: null | {
    source: string;
    synthetic: true;
    start: string;
    end: string;
    collected_at: string;
    published_at: string | null;
    complete_by_fixture: boolean;
  };
  metrics: Metric[];
  criteria: { name: string; state: EvaluationState; reason: string }[];
}

export interface ResearchReport {
  schema: "novera-synthetic-research-v1";
  scenario: ScenarioName;
  label: string;
  asset: { namespace: "novera.demo"; identifier: string };
  as_of: string;
  synthetic: true;
  disclaimer: string;
  share_basis: string;
  dividend_coverage_certified_by_fixture: boolean;
  observations: Observation[];
  strategies: Strategy[];
}

export interface Comparison {
  schema: "novera-synthetic-comparison-v1";
  synthetic: true;
  ordering: "user_selection_not_investment_ranking";
  disclaimer: string;
  total_scenarios: number;
  reports: ResearchReport[];
}

export type ParsedComparison =
  | { ok: true; value: Comparison }
  | { ok: false; error: string };

const scenarioIds = new Set<ScenarioName>(["complete", "expensive", "incomplete"]);
const evaluationStates = new Set<EvaluationState>(["pass", "fail", "unknown"]);
const qualities = new Set<DataQuality>(["present", "missing", "invalid", "not_applicable"]);
const decimal = /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/;
const sha256 = /^[0-9a-f]{64}$/;

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function string(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function period(value: unknown): boolean {
  return object(value) && string(value.start) && string(value.end);
}

function scalar(value: unknown, quality: unknown): boolean {
  if (quality === "present") return typeof value === "string" && decimal.test(value);
  return value === null && qualities.has(quality as DataQuality);
}

function validStrategy(value: unknown): boolean {
  if (!object(value) || !string(value.methodology) || !string(value.rule_version) ||
      !evaluationStates.has(value.state as EvaluationState) ||
      value.synthetic !== true || !string(value.as_of) ||
      !Array.isArray(value.metrics) || !Array.isArray(value.criteria) ||
      value.criteria.length === 0 || value.metrics.length === 0) return false;

  if (value.coverage !== null) {
    if (!object(value.coverage) || value.coverage.synthetic !== true ||
        typeof value.coverage.complete_by_fixture !== "boolean" ||
        !string(value.coverage.source) || !string(value.coverage.start) ||
        !string(value.coverage.end) || !string(value.coverage.collected_at)) return false;
  }
  return value.metrics.every((item: unknown) =>
    object(item) && string(item.name) && string(item.unit) &&
    string(item.reason) && period(item.period) &&
    (item.quality === "present" || item.quality === "missing") &&
    scalar(item.value, item.quality)
  ) && value.criteria.every((item: unknown) =>
    object(item) && string(item.name) && string(item.reason) &&
    evaluationStates.has(item.state as EvaluationState)
  );
}

function validObservation(value: unknown): boolean {
  if (!object(value) || !object(value.source) ||
      value.source.provider !== "novera-synthetic-fixture" ||
      value.source.synthetic !== true || !string(value.source.rule_version) ||
      typeof value.source.reference !== "string" ||
      !value.source.reference.startsWith("https://example.invalid/") ||
      !string(value.receipt_id) || !sha256.test(value.receipt_id) ||
      !Number.isSafeInteger(value.version) || (value.version as number) < 1 ||
      !string(value.record_key) || !string(value.metric) || !string(value.unit) ||
      !period(value.reference_period) || !string(value.collected_at)) return false;
  return qualities.has(value.quality as DataQuality) && scalar(value.value, value.quality);
}

/** Never accept real/mixed data or an unreviewed schema in the browser. */
export function parseComparison(input: unknown): ParsedComparison {
  const bad = { ok: false as const, error: "O arquivo de demonstração é incompatível ou não é sintético." };
  if (!object(input) ||
      input.schema !== "novera-synthetic-comparison-v1" ||
      input.synthetic !== true ||
      input.ordering !== "user_selection_not_investment_ranking" ||
      !string(input.disclaimer) ||
      !input.disclaimer.includes("100% FICTÍCIOS") ||
      !Array.isArray(input.reports) ||
      input.reports.length < 1 || input.reports.length > 3 ||
      input.total_scenarios !== input.reports.length) return bad;

  const seen = new Set<ScenarioName>();
  for (const report of input.reports) {
    if (!object(report) || report.schema !== "novera-synthetic-research-v1" ||
        report.synthetic !== true ||
        !scenarioIds.has(report.scenario as ScenarioName) ||
        !string(report.disclaimer) || report.disclaimer !== input.disclaimer ||
        !string(report.label) || !string(report.as_of) ||
        typeof report.dividend_coverage_certified_by_fixture !== "boolean" ||
        !string(report.share_basis) || !object(report.asset) ||
        report.asset.namespace !== "novera.demo" ||
        !string(report.asset.identifier) ||
        !Array.isArray(report.observations) || report.observations.length === 0 ||
        !report.observations.every(validObservation) ||
        !Array.isArray(report.strategies) || report.strategies.length !== 2 ||
        !report.strategies.every(validStrategy) ||
        !report.strategies.some((s: unknown) => object(s) && s.methodology === "graham-number-partial") ||
        !report.strategies.some((s: unknown) => object(s) && s.methodology === "bazin-five-365-day-windows")
    ) return bad;
    if (seen.has(report.scenario as ScenarioName)) return bad;
    seen.add(report.scenario as ScenarioName);
  }
  return { ok: true, value: input as unknown as Comparison };
}

export const stateLabels: Record<EvaluationState, string> = {
  pass: "Critério atendido",
  fail: "Critério não atendido",
  unknown: "Não avaliável",
};

export const scenarioLabels: Record<ScenarioName, string> = {
  complete: "Dados completos",
  expensive: "Preço elevado",
  incomplete: "Dados insuficientes",
};

/** Expand Decimal scientific notation using only digit strings (never a JS financial float). */
function plainDecimal(value: string): string {
  const match = /^(-?)(\\d+)(?:\\.(\\d+))?[eE]([+-]?\\d+)$/.exec(value);
  if (!match) return value;
  const [, sign, whole, fraction = "", rawExponent] = match;
  const exponent = Number(rawExponent);
  if (!Number.isInteger(exponent) || Math.abs(exponent) > 60) return value;
  const digits = whole + fraction;
  const position = whole.length + exponent;
  if (position <= 0) return sign + "0." + "0".repeat(-position) + digits;
  if (position >= digits.length) return sign + digits + "0".repeat(position - digits.length);
  return sign + digits.slice(0, position) + "." + digits.slice(position);
}

/** String manipulation only; no float parsing or financial recalculation. */
export function displayValue(value: string | null, unit: string): string {
  if (value === null) return "Não avaliável";
  const number = plainDecimal(value).replace(".", ",");
  if (unit === "currency/share") return `R$ ${number}`;
  return `${number} ${unit}`;
}
