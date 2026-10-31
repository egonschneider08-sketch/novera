import { describe, expect, it } from "vitest";
import fixture from "./data/scenarios.json";
import { displayValue, parseComparison } from "./contracts";

function clone(): Record<string, any> {
  return JSON.parse(JSON.stringify(fixture));
}

describe("synthetic data trust boundary", () => {
  it("accepts all Python-produced synthetic datasets and preserves decimals as text", () => {
    const parsed = parseComparison(fixture);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.reports).toHaveLength(3);
    expect(parsed.value.reports.map((report) => report.scenario)).toEqual([
      "complete", "expensive", "incomplete",
    ]);
    expect(parsed.value.reports.every((report) => report.synthetic)).toBe(true);
    expect(parsed.value.reports[0].strategies).toHaveLength(2);
  });

  it("fails closed on real or mixed provider data", () => {
    const altered = clone();
    altered.reports[0].observations[0].source.synthetic = false;
    expect(parseComparison(altered).ok).toBe(false);
    altered.reports[0].observations[0].source.synthetic = true;
    altered.reports[0].observations[0].source.provider = "external-provider";
    expect(parseComparison(altered).ok).toBe(false);
  });

  it("rejects unreviewed schema, manipulated count, duplicates or ranking changes", () => {
    const schema = clone();
    schema.schema = "novera-live-v1";
    expect(parseComparison(schema).ok).toBe(false);
    const total = clone();
    total.total_scenarios = 4;
    expect(parseComparison(total).ok).toBe(false);
    const duplicates = clone();
    duplicates.reports[1].scenario = "complete";
    expect(parseComparison(duplicates).ok).toBe(false);
    const ordering = clone();
    ordering.ordering = "highest_return_first";
    expect(parseComparison(ordering).ok).toBe(false);
  });

  it("distinguishes decimal zero from missing quality and disallows numeric floats", () => {
    const invalid = clone();
    invalid.reports[0].observations[0].value = 1.2;
    expect(parseComparison(invalid).ok).toBe(false);

    const missingAsZero = clone();
    const eps = missingAsZero.reports[2].observations.find(
      (item: { metric: string }) => item.metric === "earnings_per_share",
    );
    eps.value = "0";
    expect(parseComparison(missingAsZero).ok).toBe(false);

    const unknownAsFail = clone();
    unknownAsFail.reports[2].strategies[0].criteria[0].state = "invalid-status";
    expect(parseComparison(unknownAsFail).ok).toBe(false);
  });

  it("rejects invalid provenance hashes and spoofed reference hosts", () => {
    const badHash = clone();
    badHash.reports[0].observations[0].receipt_id = "1234";
    expect(parseComparison(badHash).ok).toBe(false);
    const source = clone();
    source.reports[0].observations[0].source.reference = "https://brapi.dev/actual";
    expect(parseComparison(source).ok).toBe(false);
  });

  it("displays financial numbers without converting to binary float or inferring missing values", () => {
    expect(displayValue("23.000000001", "currency/share")).toBe("R$ 23,000000001");
    expect(displayValue("0", "currency/share")).toBe("R$ 0");
    expect(displayValue(null, "ratio")).toBe("Não avaliável");
  });
});
