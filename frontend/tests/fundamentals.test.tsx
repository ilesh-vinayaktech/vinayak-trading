import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import { FundamentalsPanel } from "@/components/fundamentals/FundamentalsPanel";
import { figure, label, lines, quarterName } from "@/lib/fundamentals";
import { fundamentalsSchema } from "@/lib/schemas";

const real = fundamentalsSchema.parse(JSON.parse(readFileSync(join(__dirname, "contract/instrument_fundamentals.json"), "utf8")));

describe("fundamentals helpers", () => {
  it("names a line from its XBRL element", () => {
    expect(label("ProfitLossForPeriod")).toBe("Profit loss for period");
    expect(label("BasicEarningsLossPerShareFromContinuingOperations")).toBe("Basic earnings loss per share from continuing operations");
  });
  it("shows rupees as crore and per-share figures as reported", () => {
    expect(figure("Income", "745250000000")).toBe("74,525.00");
    expect(figure("BasicEarningsLossPerShareFromContinuingOperations", "38.37")).toBe("38.37");
    expect(figure("Income", undefined)).toBe("–");
  });
  it("lists key lines first and filters by the label", () => {
    const p = [{ ...real.periods[0]!, quarter: { ZetaLine: "1", Income: "2", ProfitLossForPeriod: "3" } }];
    expect(lines(p, "quarter")).toEqual(["Income", "ProfitLossForPeriod", "ZetaLine"]);
    expect(lines(p, "quarter", "profit")).toEqual(["ProfitLossForPeriod"]);
    expect(quarterName("2026-09-30")).toBe("Sep 2026");
  });
});

describe("Fundamentals panel", () => {
  afterEach(() => vi.restoreAllMocks());
  it("opens on a plain-language summary, with the full statements one click away", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(real), { status: 200, headers: { "content-type": "application/json" } })));
    render(<Providers><FundamentalsPanel instrumentId={1} symbol="XYZ" /></Providers>);
    await waitFor(() => expect(screen.getByTestId("fundamentals-summary")).toBeTruthy());
    expect(screen.getByTestId("tile-sales").textContent).toContain("₹74,525 cr");
    expect(screen.getByTestId("tile-profit").textContent).toContain("₹13,934 cr");
    expect(screen.queryByText("Balance sheet, at the quarter end")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "All figures" }));
    await waitFor(() => expect(screen.getByText("Quarterly results")).toBeTruthy());
    expect(screen.getByText("Net profit")).toBeTruthy();
    expect(screen.getAllByText("QoQ").length).toBeGreaterThan(0); // growth rows under the key lines
    expect(screen.getAllByText("YoY").length).toBeGreaterThan(0);
    expect(screen.getByText("Balance sheet")).toBeTruthy();
    expect(screen.getAllByText("1,90,782.00").length).toBeGreaterThan(0); // Assets 1,907,820,000,000 rupees = 1,90,782 crore
    expect(screen.getAllByText("Jun 2025").length).toBeGreaterThan(0);
    expect(screen.getByText("Every line item the filings report")).toBeTruthy();
  });
  it("says so when no results are stored", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ...real, bases: [], basis: null, periods: [] }), { status: 200, headers: { "content-type": "application/json" } })));
    render(<Providers><FundamentalsPanel instrumentId={1} symbol="XYZ" /></Providers>);
    await waitFor(() => expect(screen.getByText(/No quarterly results are stored for XYZ/)).toBeTruthy());
  });
});
