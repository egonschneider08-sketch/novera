import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import App from "./App";

afterEach(cleanup);

describe("Novera simulated source states", () => {
  it("shows an empty state without reporting zero-valued finance data", () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("SIMULAR ESTADO DA TELA"), { target: { value: "empty" } });
    expect(screen.getByRole("heading", { name: "Nenhum dado disponível" })).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
  it("keeps errors separate from a negative strategy evaluation", () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("SIMULAR ESTADO DA TELA"), { target: { value: "error" } });
    expect(screen.getByRole("heading", { name: "Não foi possível carregar os dados" })).toBeTruthy();
  });
  it("identifies stale as simulated and disables downloads", () => {
    render(<App />);
    fireEvent.change(screen.getByLabelText("SIMULAR ESTADO DA TELA"), { target: { value: "stale" } });
    expect(screen.getByRole("status").textContent).toContain("Visualização desatualizada");
    const button = screen.getByRole("button", { name: /CSV dos cenários/ }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });
});
