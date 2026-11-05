import React from "react";
import ReactDOM from "react-dom/client";
import LabApp from "./LabApp";
import ResearchHome from "./ResearchHome";
import WegStudy from "./WegStudy";

function onNavigation(update: () => void) {
  window.addEventListener("hashchange", update);
  return () => window.removeEventListener("hashchange", update);
}

function Application() {
  const route = React.useSyncExternalStore(onNavigation, () => location.hash);
  if (route === "#estudos/weg-2t25") return <WegStudy />;
  if (route === "#laboratorio") return <LabApp />;
  return <ResearchHome />;
}

const root = document.getElementById("root");
if (!root) throw new Error("Novera: elemento raiz não encontrado.");
ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <Application />
  </React.StrictMode>,
);
