export default function ResearchNav({page}: {page: "home" | "weg" | "lab"}) {
  return <header className="research-nav"><a className="wordmark" href="#inicio"><span className="brand-mark" aria-hidden="true">N</span><span>Novera</span></a>
    <nav aria-label="Navegação principal">{([
      ["home","#inicio","Estudos"],["weg","#estudos/weg-2t25","WEG"],["lab","#laboratorio","Laboratório"],
    ] as const).map(([id,href,label]) => <a key={id} href={href} aria-current={id === page ? "page" : undefined}>{label}</a>)}</nav>
  </header>;
}
