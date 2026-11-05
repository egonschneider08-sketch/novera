import { useState } from "react";

const sources = {
  petr4: { title: "Petrobras · PETR4", description: "Última cotação disponível da ação preferencial.", provider: "brapi", link: "https://brapi.dev/docs/acoes/cotacao", action: "Consultar cotação" },
  "selic-2t25": { title: "Selic no fechamento do trimestre", description: "Meta anual de juros em 30/06/2025 para contextualizar o período da DRE.", provider: "bcb", link: "https://api.bcb.gov.br/dados/serie/bcdata.sgs.432/dados?formato=json&dataInicial=30%2F06%2F2025&dataFinal=30%2F06%2F2025", action: "Consultar Selic" },
};
type Series = keyof typeof sources;
type Reading = {value: number; reference: string; collected: string};

export default function MarketReading({series}: {series: Series}) {
  const source = sources[series];
  const [reading, setReading] = useState<Reading | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function consult() {
    setLoading(true); setError(""); setReading(null);
    try {
      const response = await fetch("/api/v1/market/" + series, {headers: {"X-Novera-Read":"interactive"}, cache:"no-store"});
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (data.series !== series || data.provider !== source.provider || typeof data.value !== "string" ||
          !/^\d+(\.\d+)?$/.test(data.value) || !Number.isFinite(Number(data.value)) ||
          !Number.isFinite(Date.parse(data.reference)) || !Number.isFinite(Date.parse(data.collected))) throw new Error();
      setReading({value: Number(data.value), reference: data.reference, collected: data.collected});
    } catch {
      setError("Consulta indisponível. Confira se o servidor Novera está rodando e tente novamente.");
    } finally { setLoading(false); }
  }
  return <section className="market-reading">
    <div><small>{series === "petr4" ? "Mercado de ações · brapi" : "Contexto econômico · Banco Central"}</small>
      <h2>{source.title}</h2><p>{source.description}</p></div>
    <button type="button" disabled={loading} onClick={consult}>{loading ? "Consultando…" : source.action}</button>
    <div aria-live="polite">{reading && <>
      <strong className="market-number">{series === "petr4" ? reading.value.toLocaleString("pt-BR",{style:"currency",currency:"BRL"}) : reading.value.toLocaleString("pt-BR") + "% a.a."}</strong>
      <p>Referência {series === "petr4" ? new Date(reading.reference).toLocaleString("pt-BR") : reading.reference.split("-").reverse().join("/")} · Consultado em {new Date(reading.collected).toLocaleString("pt-BR")}</p>
    </>}{error && <p role="alert">{error}</p>}</div>
    <a href={source.link} target="_blank" rel="noreferrer">Conferir fonte ↗</a>
  </section>;
}
