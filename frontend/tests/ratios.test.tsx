import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import { FundamentalsPanel } from "@/components/fundamentals/FundamentalsPanel";
import { formatRatio, readingText, snapshot, versusYearAgo, type RatioRow } from "@/lib/ratios";
import { fundamentalsSchema, ratiosSchema } from "@/lib/schemas";

const load = (n: string) => JSON.parse(readFileSync(join(__dirname, `contract/${n}.json`), "utf8"));
const ratios = ratiosSchema.parse(load("instrument_ratios"));
const fundamentals = fundamentalsSchema.parse(load("instrument_fundamentals"));
const row = (over: Partial<RatioRow>): RatioRow => ({ key: "k", label: "L", group: "profitability", unit: "pct", meaning: "m", formula: "f", better: "high", value: "21", note: null, as_of: null, reading: null, reading_basis: null, year_ago: "18", history: [], ...over });

describe("ratio formatting", () => {
  it("writes each unit the way people read it", () => {
    expect(formatRatio("pct", "21.04")).toBe("21.0%");
    expect(formatRatio("x", "17.2112")).toBe("17.21×");
    expect(formatRatio("days", "88.95")).toBe("89 days");
    expect(formatRatio("inr", "38.37")).toBe("₹38.37");
    expect(formatRatio("crore", "888710")).toBe("₹8.89 lakh cr");
    expect(formatRatio("crore", "-6609")).toBe("−₹6,609 cr");
    expect(formatRatio("crore", "65")).toBe("₹65.0 cr");
    expect(formatRatio("pct", null)).toBe("–");
  });
  it("judges the move against a year ago by which direction is better", () => {
    expect(versusYearAgo(row({}))).toEqual({ text: "up 3.0 pts", tone: "good" });
    expect(versusYearAgo(row({ better: "low" }))).toEqual({ text: "up 3.0 pts", tone: "bad" });
    expect(versusYearAgo(row({ better: null }))?.tone).toBe("neutral"); // industry-dependent: no verdict
    expect(versusYearAgo(row({ value: "18.2" }))?.text).toBe("about the same");
    expect(versusYearAgo(row({ year_ago: null }))).toBeNull();
    expect(versusYearAgo(row({ unit: "x", better: "low", value: "0.3", year_ago: "0.5" }))).toEqual({ text: "down 0.2×", tone: "good" });
  });
  it("words the reading by what it was measured against, and says why when there is none", () => {
    expect(readingText(row({ reading: "good", reading_basis: "rule" }))).toBe("Strong");
    expect(readingText(row({ reading: "weak", reading_basis: "own_past", group: "valuation" }))).toBe("Pricier than usual");
    expect(readingText(row({ reading: "good", reading_basis: "own_past", group: "valuation" }))).toBe("Cheaper than usual");
    expect(readingText(row({ reading: "ok", reading_basis: "own_past" }))).toBe("Usual range");
    expect(readingText(row({ reading: "weak", reading_basis: "own_past" }))).toBe("Worse than usual");
    expect(readingText(row({ better: "low" }))).toBe("not enough history");
    expect(readingText(row({ better: null }))).toBe("–"); // market value: a size, not good or bad
    expect(readingText(row({ value: null }))).toBe("–");
  });
  it("leads with the six ratios people look at first", () => {
    expect(snapshot(ratios).map((r) => r.key)).toEqual(["market_cap", "pe", "pb", "roe", "debt_to_equity", "dividend_yield"].filter((k) => ratios.ratios.some((r) => r.key === k)));
    expect(snapshot({ ...ratios, bank: true }).every((r) => r.key !== "debt_to_equity")).toBe(true);
  });
});

describe("Ratios view", () => {
  afterEach(() => vi.restoreAllMocks());
  it("is one click from the summary and groups the ratios with plain meanings, yardsticks and the data behind them", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => new Response(JSON.stringify(String(url).includes("/ratios") ? ratios : fundamentals), { status: 200, headers: { "content-type": "application/json" } })));
    render(<Providers><FundamentalsPanel instrumentId={1} symbol="XYZ" /></Providers>);
    fireEvent.click(await screen.findByRole("button", { name: "Ratios" }));
    await waitFor(() => expect(screen.getByTestId("ratios-view")).toBeTruthy());
    expect(screen.getByText(/Valuation: what you pay/)).toBeTruthy();
    expect(screen.getByText(/Profitability: how well it makes money/)).toBeTruthy();
    expect(screen.getAllByText("Price to book (P/B)").length).toBeGreaterThan(1); // in the snapshot and in its group
    expect(screen.getByText(/Price against what the company's owners' money/)).toBeTruthy();
    expect(screen.getByTestId("snap-market_cap").textContent).toContain("₹37,648 cr");
    expect(screen.getByText(/Price ₹104 \(last close, 2025-06-12\)/)).toBeTruthy();
    expect(screen.getByText(/Two kinds of reading/)).toBeTruthy();
    expect(screen.queryByText("no fixed yardstick")).toBeNull();
  });
});
