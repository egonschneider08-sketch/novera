import React from "react";
import ReactDOM from "react-dom/client";
import LabApp from "./LabApp";

const root = document.getElementById("root");
if (!root) throw new Error("Novera: elemento raiz não encontrado.");
ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <LabApp />
  </React.StrictMode>,
);
