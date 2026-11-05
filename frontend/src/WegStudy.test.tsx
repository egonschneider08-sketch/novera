import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import WegStudy from "./WegStudy";

afterEach(() => { cleanup(); localStorage.clear(); });

it("uses quarterly consolidated figures and keeps WEG decisions separate from Aurora", async () => {
  localStorage.setItem("novera:thesis:aurora-q2-v1:example", JSON.stringify({
    at: "2025-01-01T00:00:00Z", decision: "Manter", reason: "Hipótese da Aurora",
  }));
  render(<WegStudy />);
  expect(screen.getByRole("table")).toBeTruthy();
  for (const value of ["9.274.426", "1.931.290", "10.207.227", "2.021.942", "20,82%", "19,81%"]) {
    expect(screen.getByText(value)).toBeTruthy();
  }
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "Revisar" } });
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Margem menor." } });
  fireEvent.click(screen.getByRole("button", { name: "Registrar revisão" }));
  expect(await screen.findByText("Margem menor.")).toBeTruthy();
  expect(screen.queryByText("Hipótese da Aurora")).toBeNull();
  expect(Object.keys(localStorage).filter(key => key.startsWith("novera:thesis:weg-"))).toHaveLength(1);
});
