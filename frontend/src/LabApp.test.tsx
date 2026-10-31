import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import fixture from "./data/scenarios.json";
import LabApp from "./LabApp";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

const response = (data: unknown, contentType = "application/json") => ({
  ok: true,
  status: 200,
  headers: { get: (name: string) => name === "content-type" ? contentType : null },
  json: async () => data,
});

describe("Novera local single-origin flow", () => {
  it("uses Python-bundled synthetic snapshots with no HTTP by default", () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    render(<LabApp />);
    expect(screen.getByText(/Snapshot Python validado/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Laboratório Aurora/ })).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("loads and validates the local-only HTTP comparison without a third-party origin", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(fixture));
    vi.stubGlobal("fetch", fetchMock);
    render(<LabApp />);
    fireEvent.click(screen.getByRole("button", { name: "API local" }));

    expect(await screen.findByText(/Conectado à API local/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Laboratório Aurora/ })).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/demo/comparison");
    expect(options.method).toBe("GET");
    expect(options.credentials).toBe("omit");
    expect(options.cache).toBe("no-store");
    expect(options.headers.Accept).toBe("application/json");
    expect((screen.getByRole("button", { name: /CSV apenas no snapshot/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("does not silently show old snapshot values when local API is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connection-refused")));
    render(<LabApp />);
    fireEvent.click(screen.getByRole("button", { name: "API local" }));

    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringContaining("Nenhum número do snapshot"),
    );
    expect(screen.queryByRole("heading", { name: /Laboratório Aurora/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Usar dados incorporados" })).toBeTruthy();
  });

  it("fails closed if HTTP schema is not synthetic", async () => {
    const untrusted = JSON.parse(JSON.stringify(fixture));
    untrusted.reports[0].observations[0].source.synthetic = false;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(untrusted)));
    render(<LabApp />);
    fireEvent.click(screen.getByRole("button", { name: "API local" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("rejects unexpected HTML instead of parsing and displaying financial values", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(fixture, "text/html")));
    render(<LabApp />);
    fireEvent.click(screen.getByRole("button", { name: "API local" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("retries after an error and allows an explicit return to offline data", async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(response(fixture));
    vi.stubGlobal("fetch", fetchMock);
    render(<LabApp />);
    fireEvent.click(screen.getByRole("button", { name: "API local" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(await screen.findByText(/Conectado à API local/)).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    fireEvent.click(screen.getByRole("button", { name: "Dados incorporados" }));
    expect(screen.getByText(/Snapshot Python validado/)).toBeTruthy();
  });
});
