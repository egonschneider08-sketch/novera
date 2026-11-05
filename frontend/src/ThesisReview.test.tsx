import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import ThesisReview from "./ThesisReview";

afterEach(() => { cleanup(); localStorage.clear(); });

it("reopens the researcher's decision and evidence after remount", async () => {
  const first = render(<ThesisReview />);
  fireEvent.click(screen.getByText(/Revisão de tese ·/));
  expect(screen.getByText("15%")).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox"), {target: {value: "Revisar"}});
  fireEvent.change(screen.getByRole("textbox"), {target: {value: "A margem caiu de 20% para 15%."}});
  fireEvent.click(screen.getByRole("button", {name: "Registrar revisão"}));
  first.unmount();
  render(<ThesisReview />);
  fireEvent.click(screen.getByText(/Revisão de tese ·/));
  expect(await screen.findByText("A margem caiu de 20% para 15%.")).toBeTruthy();
});

it("preserves readable reviews and can save when a sibling record is damaged", async () => {
  const prefix = "novera:thesis:aurora-q2-v1:";
  localStorage.setItem(prefix + "broken", "{");
  localStorage.setItem(prefix + "old", JSON.stringify({
    at: "2026-01-01T00:00:00.000Z", decision: "Manter", reason: "Análise anterior",
  }));
  render(<ThesisReview />);
  fireEvent.click(screen.getByText(/Revisão de tese ·/));
  expect(await screen.findByText("Análise anterior")).toBeTruthy();
  expect(screen.getByText(/1 registro ilegível/)).toBeTruthy();
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "Revisar" } });
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Nova evidência" } });
  fireEvent.click(screen.getByRole("button", { name: "Registrar revisão" }));
  expect(await screen.findByText("Nova evidência")).toBeTruthy();
  expect(screen.getByText("Análise anterior")).toBeTruthy();
  expect(localStorage.getItem(prefix + "broken")).toBe("{");
  expect(localStorage.length).toBe(3);
});
