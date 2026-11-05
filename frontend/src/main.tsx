import React from "react";
import ReactDOM from "react-dom/client";
import LabApp from "./LabApp";
import ResearchNav from "./ResearchNav";
import ResearchHome from "./ResearchHome";
import WegStudy from "./WegStudy";

function onNavigation(update: () => void) {
  window.addEventListener("hashchange", update);
  return () => window.removeEventListener("hashchange", update);
}

function Application() {
  const route = React.useSyncExternalStore(onNavigation, () => location.hash);
  const page = route === "#estudos/weg-2t25" ? "weg" : route === "#laboratorio" ? "lab" : "home";
  return <><ResearchNav page={page} />{page === "weg" ? <WegStudy /> : page === "lab" ? <LabApp /> : <ResearchHome />}</>;
}

const root = document.getElementById("root");
if (!root) throw new Error("Novera: elemento raiz não encontrado.");
ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <Application />
  </React.StrictMode>,
);
