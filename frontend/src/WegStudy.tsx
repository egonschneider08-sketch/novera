import MarketReading from "./MarketReading";
import { ReviewSheet } from "./ThesisReview";

// WEG ITR 30/06/2025 v1, consolidated DRE, printed page 13. BRL thousands.
const quarters = [
  { period: "2T24", revenue: 9274426, operating: 1931290 },
  { period: "2T25", revenue: 10207227, operating: 2021942 },
];
const currency = new Intl.NumberFormat("pt-BR");
const percent = new Intl.NumberFormat("pt-BR", { style: "percent", maximumFractionDigits: 2 });
const filing = "https://api.mziq.com/mzfilemanager/v2/d/50c1bd3e-8ac6-42d9-884f-b9d69f690602/53207874-a96b-06c3-48ed-7e89cea775bf?origin=1";

export default function WegStudy() {
  return <main className="company-page">
    <div className="study-cover"><small>WEGE3 · Demonstrações financeiras</small>
    <h1>WEG · resultado do segundo trimestre de 2025</h1>
    <p>Estudo retrospectivo com dados públicos de abril a junho de 2024 e de 2025.</p>
    </div>
    <ReviewSheet prefix="novera:thesis:weg-itr-2025q2-v1:" initiallyOpen title="Ficha de revisão da WEG"
      localNotice="As decisões sobre este estudo ficam neste navegador.">
      <h2>O crescimento da receita veio acompanhado de manutenção da margem operacional?</h2>
      <p>Hipótese do exercício, formulada após a divulgação do resultado.</p>
      <table><caption>Demonstração do resultado consolidado · valores em R$ mil</caption>
        <thead><tr><th>Trimestre</th><th>Receita</th><th>Resultado operacional</th><th>Margem calculada</th></tr></thead>
        <tbody>{quarters.map(q => <tr key={q.period}><th scope="row">{q.period}</th>
          <td>{currency.format(q.revenue)}</td><td>{currency.format(q.operating)}</td>
          <td>{percent.format(q.operating / q.revenue)}</td></tr>)}</tbody>
      </table>
      <p>A margem operacional mostra quanto da receita sobra após os custos e despesas operacionais. O cálculo divide o resultado antes do resultado financeiro e dos tributos (conta 3.05)
        pela receita (3.01). Os valores são dos trimestres isolados, conforme apresentados no ITR de 2025.</p>
      <a href={filing} target="_blank" rel="noreferrer">Consultar ITR da WEG · 30/06/2025 · versão 1 · página impressa 13</a>
    </ReviewSheet>
    <MarketReading series="selic-2t25" />
  </main>;
}
