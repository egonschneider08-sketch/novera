import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import App from "./App";

afterEach(cleanup);

describe("Novera Lab interactions", () => {
  it("renders a persistent fictitious-data warning and LAB-A", () => {
    render(<App />);
    expect(screen.getByText(/AMBIENTE DE DEMONSTRAÇÃO/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Laboratório Aurora/ })).toBeTruthy();
  });
  it("switches scenarios without changing unknown into failure", () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: /LAB-C/ }));
    expect(screen.getByRole("heading", { name: /Laboratório Lacuna/ })).toBeTruthy();
    expect(screen.getAllByText("Não avaliável").length).toBeGreaterThan(0);
  });
  it("supports keyboard switching to Bazin", () => {
    render(<App />);
    fireEvent.keyDown(screen.getByRole("tab", { name: "Benjamin Graham" }), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Décio Bazin" }).getAttribute("aria-selected")).toBe("true");
  });
});
