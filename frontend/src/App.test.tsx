import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import fixture from "./data/scenarios.json";
import App from "./App";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("Novera export and provenance safety", () => {
  it("fails closed on a real or incompatible dataset", () => {
    const invalid = JSON.parse(JSON.stringify(fixture));
    invalid.synthetic = false;
    render(<App data={invalid} />);
    expect(screen.getByRole("alert").textContent).toContain("Não foi possível validar");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("offers visible receipt details and explicit downloads only in demo mode", () => {
    const makeUrl = vi.fn(() => "blob:synthetic-fixture");
    const revoke = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL: makeUrl, revokeObjectURL: revoke });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<App />);
    fireEvent.click(screen.getByText("Inspecionar origem, versões e recibos"));
    expect(screen.getAllByText("Recibo SHA-256").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: /JSON do ativo/ }));
    expect(makeUrl).toHaveBeenCalledTimes(1);
    expect(revoke).toHaveBeenCalledWith("blob:synthetic-fixture");
  });
});
