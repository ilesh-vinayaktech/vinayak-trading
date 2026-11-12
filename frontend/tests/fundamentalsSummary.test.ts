import { describe, expect, it } from "vitest";
import type { Period } from "@/lib/fundamentals";
import { change, crore, summarize, yearAgo } from "@/lib/fundamentalsSummary";

const END = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30"];
function p(end: string, sales: number, profit: number, extra: Partial<Period> = {}): Period {
  return { period_start: end, period_end: end, filed_at: `${end}T00:00:00Z`, audited: true, bank: false, rounding: "Crores", quarter: { RevenueFromOperations: String(sales * 1e7), ProfitLossForPeriod: String(profit * 1e7), BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations: String(profit / 10) }, ytd: {}, instant: {}, ...extra };
}
/** newest first: sales and profit per quarter, in crore */
const series = (rows: [number, number][]) => rows.map(([s, n], i) => p(END[i] as string, s, n));

describe("change", () => {
  it("gives a percent only off a positive base and names turnarounds and losses", () => {
    expect(change(110, 100)).toEqual({ kind: "pct", value: 10 });
    expect(change(5, -3)).toEqual({ kind: "turnaround" });
    expect(change(-2, -5)).toEqual({ kind: "loss_narrowed" });
    expect(change(-9, -5)).toEqual({ kind: "loss_widened" });
    expect(change(-1, 4)).toEqual({ kind: "slipped_to_loss" });
    expect(change(undefined, 4)).toBeNull();
  });
  it("matches the same quarter a year earlier by date, not by position", () => {
    const ps = series([[1, 1], [1, 1], [1, 1], [1, 1], [1, 1], [1, 1]]);
    expect(yearAgo(ps, ps[0] as Period)?.period_end).toBe("2025-09-30");
    expect(yearAgo(ps.slice(0, 3), ps[0] as Period)).toBeUndefined();
  });
  it("writes large amounts in crore and lakh crore", () => {
    expect(crore(745_250_000_000)).toBe("₹74,525 cr");
    expect(crore(1_907_820_000_000)).toBe("₹1.91 lakh cr");
    expect(crore(35_000_000)).toBe("₹3.5 cr");
    expect(crore(-66_090_000_000)).toBe("−₹6,609 cr");
  });
});

describe("summarize", () => {
  it("calls a company with rising sales, profit and margin healthy and says growth is speeding up", () => {
    const s = summarize(series([[1300, 260], [1200, 220], [1150, 190], [1100, 180], [1000, 150], [980, 148]]));
    expect(s.verdict).toBe("good");
    expect(s.headline).toMatch(/Looking healthy/);
    expect(s.headline).toMatch(/speeding up/);
    const sales = s.tiles.find((t) => t.key === "sales");
    expect(sales?.vsYear).toBe("up 30% from a year ago");
    expect(sales?.tone).toBe("good");
    expect(sales?.series.map((x) => x.value)[0]).toBeLessThan(sales?.series.at(-1)?.value ?? 0); // oldest first
    expect(s.tiles.find((t) => t.key === "margin")?.tone).toBe("good");
  });
  it("calls falling sales and profit weakening", () => {
    const s = summarize(series([[800, 40], [850, 60], [900, 80], [950, 90], [1000, 120], [1000, 120]]));
    expect(s.verdict).toBe("weak");
    expect(s.tiles.find((t) => t.key === "profit")?.vsYear).toBe("down 67% from a year ago");
  });
  it("calls flat results mixed", () => {
    const s = summarize(series([[1000, 100], [1000, 100], [1000, 100], [1000, 100], [1010, 101], [1000, 100]]));
    expect(s.verdict).toBe("mixed");
  });
  it("explains a swing from loss to profit", () => {
    const s = summarize(series([[900, 50], [800, 10], [800, 5], [700, -5], [700, -30], [700, -20]]));
    expect(s.tiles.find((t) => t.key === "profit")?.vsYear).toBe("a profit now, against a loss a year ago");
  });
  it("never calls a loss-making company healthy, even when sales rise and the loss shrinks", () => {
    const s = summarize(series([[1300, -50], [1200, -80], [1150, -90], [1100, -100], [1000, -150], [980, -148]]));
    expect(s.verdict).toBe("mixed");
    expect(s.headline).toMatch(/Still losing money/);
    expect(s.checks[0]?.text).toMatch(/lost ₹50\.0 cr/);
    expect(s.tiles.find((t) => t.key === "profit")?.latest).toBe("−₹50.0 cr");
    expect(summarize(series([[900, -200], [1200, -80], [1150, -90], [1100, -100], [1000, -50]])).verdict).toBe("weak");
  });
  it("names a bank's top line total income", () => {
    const ps = series([[1300, 260], [1200, 220], [1150, 190], [1100, 180], [1000, 150]]).map((x) => ({ ...x, bank: true }));
    expect(summarize(ps).tiles[0]?.title).toBe("Total income");
  });
  it("needs a year of history before it judges", () => {
    const s = summarize(series([[900, 50], [800, 10]]));
    expect(s.verdict).toBe("unknown");
    expect(summarize([]).tiles).toEqual([]);
  });
  it("checks that profit turns into cash, and flags when it does not", () => {
    const base = series([[1300, 260], [1200, 220], [1150, 190], [1100, 180], [1000, 150]]);
    const withCash = (cfo: number) => [{ ...(base[0] as Period), ytd: { ProfitLossForPeriod: String(480 * 1e7), CashFlowsFromUsedInOperatingActivities: String(cfo * 1e7) } }, ...base.slice(1)];
    expect(summarize(withCash(500)).checks.find((c) => /turned into cash/.test(c.text))?.tone).toBe("good");
    const bad = summarize(withCash(100)).checks.find((c) => /turned into cash/.test(c.text));
    expect(bad?.tone).toBe("bad");
    expect(bad?.text).toMatch(/closer look/);
  });
  it("reads debt from the balance sheet: debt-free, or up and down against last year, per rupee of owners' money", () => {
    const base = series([[1300, 260], [1200, 220], [1150, 190], [1100, 180], [1000, 150]]);
    const sheet = (cur: Record<string, string>, ago: Record<string, string>) => base.map((x, i) => (i === 0 ? { ...x, instant: cur } : i === 4 ? { ...x, instant: ago } : x));
    const free = summarize(sheet({ BorrowingsNoncurrent: "0", BorrowingsCurrent: "0" }, {}));
    expect(free.checks.some((c) => /debt-free/.test(c.text))).toBe(true);
    const up = summarize(sheet({ BorrowingsNoncurrent: String(900 * 1e7), BorrowingsCurrent: String(100 * 1e7), Equity: String(2000 * 1e7) }, { BorrowingsNoncurrent: String(500 * 1e7), BorrowingsCurrent: String(100 * 1e7) }));
    const c = up.checks.find((x) => /Borrowings/.test(x.text));
    expect(c?.tone).toBe("bad");
    expect(c?.text).toMatch(/up 67%/);
    expect(c?.text).toMatch(/₹0.50 of debt for every ₹1/);
  });
});
