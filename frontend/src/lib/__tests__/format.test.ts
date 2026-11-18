import { describe, expect, it } from "vitest";
import { cellText, compact, fmtPct, fmtValue } from "../format";

describe("number formatting", () => {
  it("formats currency compactly with the workspace currency", () => {
    expect(fmtValue(37466.92, "currency", "INR")).toBe("₹37.5K");
    expect(fmtValue(-1806.25, "currency", "USD")).toBe("−$1,806");
    expect(fmtValue(1234567, "currency", "EUR")).toBe("€1.23M");
  });
  it("formats ratios and percentage points", () => {
    expect(fmtValue(0.421, "percent")).toBe("42.1%");
    expect(fmtValue(-0.049, "percent_points")).toBe("-4.9 pp");
    expect(fmtPct(-24.94)).toBe("−24.9%");
    expect(fmtPct(12)).toBe("+12.0%");
  });
  it("shows a dash for missing values instead of zero", () => {
    expect(fmtValue(null, "currency")).toBe("—");
    expect(cellText(undefined)).toBe("—");
  });
  it("formats table cells by column role", () => {
    expect(cellText(12.3456, { role: "percent" })).toBe("12.3%");
    expect(cellText(29757.77, { role: "measure", unit: "currency" }, "INR")).toBe("₹29,757.77");
    expect(cellText("2026-10-01T00:00:00")).toBe("2026-10-01");
    expect(compact(950)).toBe("950");
  });
});
