import { useState } from "react";

const prefix = "novera:thesis:aurora-q2-v1:";
const decisions = ["Manter", "Revisar", "Evidência insuficiente"] as const;
const statements = [
  { quarter: "2T25", revenue: 100, operating: 20 },
  { quarter: "2T26", revenue: 120, operating: 18 },
];
type Review = { at: string; decision: string; reason: string };

function history(): Review[] {
  const records: Review[] = [];
  for (const key of Object.keys(localStorage).filter(key => key.startsWith(prefix))) {
    const entry = JSON.parse(localStorage.getItem(key) ?? "null");
    if (!entry || typeof entry.at !== "string" || !Number.isFinite(Date.parse(entry.at)) ||
        !decisions.some(d => d === entry.decision) || typeof entry.reason !== "string") {
      throw new Error("Invalid review");
    }
    records.push(entry);
  }
  return records.sort((a, b) => b.at.localeCompare(a.at));
}

export default function ThesisReview() {
  const [decision, setDecision] = useState("");
  const [reason, setReason] = useState("");
  const [records, setRecords] = useState<Review[]>([]);
  const [message, setMessage] = useState("");
  function refresh() {
    try { setRecords(history()); setMessage(""); }
    catch { setMessage("Não foi possível ler todo o histórico deste navegador."); }
  }
  return <details className="thesis-review" onToggle={e => { if (e.currentTarget.open) refresh(); }}>
    <summary>Revisão de tese · laboratório fictício</summary>
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
    <form onSubmit={e => {
      e.preventDefault();
      if (!decision || !reason.trim()) return;
      const record = { at: new Date().toISOString(), decision, reason: reason.trim() };
      try {
        const previous = history();
        localStorage.setItem(prefix + crypto.randomUUID(), JSON.stringify(record));
        setRecords([record, ...previous]); setReason(""); setDecision("");
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
    <p>As revisões ficam neste dispositivo. Use apenas notas do exercício fictício.</p>
    {records.map((entry, i) => <article key={i}><strong>{entry.decision}</strong> · {new Date(entry.at).toLocaleString("pt-BR")}<p>{entry.reason}</p></article>)}
  </details>;
}
