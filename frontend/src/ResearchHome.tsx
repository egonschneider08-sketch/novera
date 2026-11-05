import MarketReading from "./MarketReading";
import "./research-home.css";

export default function ResearchHome() {
  return <div className="research-home">
    <main className="research-index">
      <h1>Estudos de ações</h1>
      <p className="index-lead">Escolha uma empresa para conferir os resultados e registrar sua análise.</p>
      <article className="company-study">
        <div className="company-meta"><span>WEGE3 · WEG S.A.</span><span>Dados públicos</span></div>
        <h2>Como mudou a margem da WEG?</h2>
        <p>Compare receita e resultado operacional do segundo trimestre de 2025 com o mesmo período de 2024.</p>
        <a className="study-action" href="#estudos/weg-2t25">Analisar resultados da WEG <span aria-hidden="true">→</span></a>
      </article>
      <MarketReading series="petr4" />
      <section className="practice-study">
        <div><h2>Praticar com a Aurora</h2><p>Use uma empresa fictícia para experimentar Graham, Bazin e a revisão de uma hipótese.</p></div>
        <a href="#laboratorio">Abrir laboratório fictício <span aria-hidden="true">→</span></a>
      </section>
    </main>
  </div>;
}
