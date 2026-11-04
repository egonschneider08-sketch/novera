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
