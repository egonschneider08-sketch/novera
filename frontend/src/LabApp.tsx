import { useEffect, useState } from "react";
import App from "./App";
import { parseComparison, type Comparison } from "./contracts";

type DataSource = "snapshot" | "local-api";
type RemoteState =
  | { status: "idle" | "loading" }
  | { status: "ready"; comparison: Comparison }
  | { status: "error" };

const API_PATH = "/api/v1/demo/comparison";

/** The browser can request only the same-origin synthetic laboratory API.
 * No real market provider, token, cookie, CORS or automatic fallback is used.
 */
export default function LabApp() {
  const [source, setSource] = useState<DataSource>("snapshot");
  const [reload, setReload] = useState(0);
  const [remote, setRemote] = useState<RemoteState>({ status: "idle" });

  useEffect(() => {
    if (source !== "local-api") return;
    const controller = new AbortController();
    setRemote({ status: "loading" });
    void (async () => {
      try {
        const response = await fetch(API_PATH, {
          method: "GET",
          headers: { Accept: "application/json" },
          credentials: "omit",
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok || !response.headers.get("content-type")?.includes("application/json")) {
          throw new Error("The local laboratory API did not return JSON.");
        }
        const parsed = parseComparison(await response.json());
        if (!parsed.ok) throw new Error("Synthetic data contract rejected the response.");
        if (!controller.signal.aborted) setRemote({ status: "ready", comparison: parsed.value });
      } catch {
        if (!controller.signal.aborted) setRemote({ status: "error" });
      }
    })();
    return () => controller.abort();
  }, [source, reload]);

  return (
    <>
      <section className="source-bar" aria-label="Origem dos dados financeiros fictícios">
        <div className="source-description">
          <strong>Modo de dados</strong>
          <span>Escolha como visualizar o mesmo laboratório fictício.</span>
        </div>
        <div className="source-options" role="group" aria-label="Origem da pesquisa">
          <button
            type="button"
            className={source === "snapshot" ? "source-selected" : ""}
            aria-pressed={source === "snapshot"}
            onClick={() => setSource("snapshot")}
          >
            Dados incorporados
          </button>
          <button
            type="button"
            className={source === "local-api" ? "source-selected" : ""}
            aria-pressed={source === "local-api"}
            onClick={() => setSource("local-api")}
          >
            API local
          </button>
        </div>
        {source === "snapshot" && (
          <span className="source-status">Snapshot Python validado · offline</span>
        )}
        {source === "local-api" && remote.status === "ready" && (
          <span className="source-status" role="status">
            Conectado à API local · somente dados fictícios
          </span>
        )}
      </section>

      {source === "snapshot" ? (
        <App />
      ) : remote.status === "ready" ? (
        <App data={remote.comparison} enableCsvExport={false} />
      ) : (
        <main className="source-feedback" aria-live="polite">
          <p className="source-warning">AMBIENTE DE DEMONSTRAÇÃO — DADOS 100% FICTÍCIOS</p>
          {remote.status === "error" ? (
            <>
              <h1>API local indisponível ou resposta incompatível</h1>
              <p role="alert">
                Não foi possível validar a pesquisa recebida. Nenhum número do snapshot
                será exibido como se tivesse vindo da API. Verifique o servidor Novera Lab.
              </p>
              <div className="source-recovery">
                <button type="button" onClick={() => setReload((previous) => previous + 1)}>
                  Tentar novamente
                </button>
                <button type="button" onClick={() => setSource("snapshot")}>
                  Usar dados incorporados
                </button>
              </div>
            </>
          ) : (
            <>
              <h1>Consultando a API local</h1>
              <p role="status">Carregando cenários fictícios e validando a proveniência.</p>
            </>
          )}
        </main>
      )}
    </>
  );
}
