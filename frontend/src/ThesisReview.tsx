import { useState, type ReactNode } from "react";

const decisions = ["Manter", "Revisar", "Evidência insuficiente"] as const;
const statements = [
  { quarter: "2T25", revenue: 100, operating: 20 },
  { quarter: "2T26", revenue: 120, operating: 18 },
];
type Review = { at: string; decision: string; reason: string };

function readHistory(prefix: string) {
  let unreadable = 0;
  const records: Review[] = [];
  for (const key of Object.keys(localStorage).filter(key => key.startsWith(prefix))) {
    const raw = localStorage.getItem(key);
    if (raw === null) continue;
    let entry;
    try {
      entry = JSON.parse(raw);
    } catch {
      unreadable++;
      continue;
    }
    if (!entry || typeof entry.at !== "string" || !Number.isFinite(Date.parse(entry.at)) ||
        !decisions.some(d => d === entry.decision) || typeof entry.reason !== "string") {
      unreadable++;
      continue;
    }
    records.push(entry);
  }
  records.sort((a, b) => b.at.localeCompare(a.at));
  return { records, unreadable };
}

type ReviewSheetProps = {
  prefix: string;
  title: string;
  localNotice: string;
  children: ReactNode;
};

export function ReviewSheet({ prefix, title, localNotice, children }: ReviewSheetProps) {
  const [decision, setDecision] = useState("");
  const [reason, setReason] = useState("");
  const [records, setRecords] = useState<Review[]>([]);
  const [message, setMessage] = useState("");
  const [unreadable, setUnreadable] = useState(0);
  function refresh() {
    try {
      const snapshot = readHistory(prefix);
      setRecords(snapshot.records);
      setUnreadable(snapshot.unreadable);
      setMessage("");
    }
    catch { setMessage("Não foi possível ler todo o histórico deste navegador."); }
  }
  return <details className="thesis-review" onToggle={e => { if (e.currentTarget.open) refresh(); }}>
    <summary>{title}</summary>
    {children}
    <form onSubmit={e => {
      e.preventDefault();
      if (!decision || !reason.trim()) return;
      const record = { at: new Date().toISOString(), decision, reason: reason.trim() };
      try {
        const previous = readHistory(prefix);
        localStorage.setItem(prefix + crypto.randomUUID(), JSON.stringify(record));
        setUnreadable(previous.unreadable);
        setRecords([record, ...previous.records]); setReason(""); setDecision("");
        setMessage("Revisão registrada neste navegador.");
      } catch { setMessage("Falha ao salvar. Copie sua justificativa antes de sair."); }
    }}>
      <label>Decisão sobre a hipótese<select required value={decision} onChange={e => setDecision(e.target.value)}>
        <option value="">Escolha uma decisão</option>{decisions.map(d => <option key={d}>{d}</option>)}</select></label>
      <label>Qual evidência sustenta sua decisão?<textarea required maxLength={2000} value={reason}
        onChange={e => setReason(e.target.value)} /></label>
      <button disabled={!reason.trim() || !decision}>Registrar revisão</button>
    </form>
    <p role="status">{message}</p>
    <h3>Histórico neste navegador</h3>
    {unreadable > 0 && <p role="status">
      {unreadable === 1 ? "1 registro ilegível foi preservado." : `${unreadable} registros ilegíveis foram preservados.`}
    </p>}
    <p>{localNotice}</p>
    {records.map((entry, i) => <article key={i}><strong>{entry.decision}</strong> · {new Date(entry.at).toLocaleString("pt-BR")}<p>{entry.reason}</p></article>)}
  </details>;
}

export default function ThesisReview() {
  return <ReviewSheet prefix="novera:thesis:aurora-q2-v1:" title="Revisão de tese · laboratório fictício"
    localNotice="As revisões ficam neste dispositivo. Use apenas notas do exercício fictício.">
    <h2>Aurora Industrial · revisão do 2T26</h2>
    <p><strong>Hipótese registrada antes da divulgação</strong><br />
      Espero crescimento da receita sem queda de margem operacional frente ao mesmo trimestre do ano anterior.</p>
    <table><caption>DRE consolidada · trimestres isolados · dados fictícios</caption>
      <thead><tr><th>Período</th><th>Receita (R$ mi)</th><th>Resultado operacional (R$ mi)</th><th>Margem</th></tr></thead>
      <tbody>{statements.map(s => <tr key={s.quarter}><th scope="row">{s.quarter}</th>
        <td>{s.revenue}</td><td>{s.operating}</td><td>{100 * s.operating / s.revenue}%</td></tr>)}</tbody>
    </table>
    <details><summary>Conferir fonte e cálculo</summary>
      {statements.map(s => <p key={s.quarter}><strong>Demonstrativo fictício Aurora · {s.quarter} · versão 1</strong><br/>
        Receita líquida de R$ {s.revenue} milhões e resultado operacional de R$ {s.operating} milhões.
        Margem = {s.operating} ÷ {s.revenue} × 100.</p>)}
    </details>
  </ReviewSheet>;
}
