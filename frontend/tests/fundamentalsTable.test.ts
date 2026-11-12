import { describe, expect, it } from "vitest";
import type { Period } from "@/lib/fundamentals";
import { balanceTable, cashTable, growth, quarterlyTable } from "@/lib/fundamentalsTable";

const END = ["2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"];
const cr = (n: number) => String(n * 1e7);
function q(end: string, rev: number, exp: number, fin: number, dep: number, pat: number, extra: Record<string, string> = {}): Period {
  return { period_start: end, period_end: end, filed_at: "", audited: true, bank: false, rounding: "", ytd: {}, instant: {},
    quarter: { RevenueFromOperations: cr(rev), Expenses: cr(exp), FinanceCosts: cr(fin), DepreciationDepletionAndAmortisationExpense: cr(dep), ProfitLossForPeriod: cr(pat), ...extra } };
}
const periods = [q(END[0]!, 1100, 800, 20, 30, 200), q(END[1]!, 1000, 780, 20, 30, 180), q(END[2]!, 950, 750, 20, 30, 160), q(END[3]!, 900, 720, 20, 30, 150), q(END[4]!, 1000, 800, 20, 30, 100), q(END[5]!, 900, 700, 20, 30, 90)];

describe("growth", () => {
  it("is percent off the absolute base, null without a base", () => {
    expect(growth(110, 100)).toBe(10);
    expect(growth(-50, -100)).toBe(50); // a loss that halves reads as +50
    expect(growth(5, 0)).toBeNull();
    expect(growth(undefined, 3)).toBeNull();
  });
});

describe("quarterly table", () => {
  const t = quarterlyTable(periods);
  const row = (k: string) => t.rows.find((r) => r.key === k)!;
  it("puts the oldest quarter first and the newest last", () => {
    expect(t.columns.map((c) => c.label)).toEqual(["Jun 2025", "Sep 2025", "Dec 2025", "Mar 2026", "Jun 2026", "Sep 2026"]);
    expect(row("revenue").values.at(-1)).toBe(1100e7);
  });
  it("derives operating profit and margin: revenue less expenses, with interest and depreciation added back", () => {
    expect(row("operating").values.at(-1)).toBe((1100 - (800 - 20 - 30)) * 1e7); // 350 cr
    expect(row("opm").values.at(-1)).toBeCloseTo((350 / 1100) * 100, 6);
    expect(row("npm").values.at(-1)).toBeCloseTo((200 / 1100) * 100, 6);
  });
  it("shows quarter-on-quarter against the previous quarter and year-on-year against the same quarter last year, by date", () => {
    expect(row("revenue").qoq?.at(-1)).toBeCloseTo(10, 6); // 1100 vs 1000
    expect(row("revenue").yoy?.at(-1)).toBeCloseTo(10, 6); // 1100 vs 1000 (Sep 2025)
    expect(row("pat").yoy?.at(-1)).toBeCloseTo(100, 6); // 200 vs 100
    expect(row("pat").qoq?.[0]).toBeNull(); // no earlier quarter loaded
    expect(row("pat").yoy?.[0]).toBeNull();
    expect(row("expenses").yoy).toBeNull(); // growth only under the key lines
  });
  it("drops lines nobody reported", () => {
    expect(t.rows.find((r) => r.key === "other")).toBeUndefined();
  });
  it("uses bank lines for a bank", () => {
    const bank = periods.map((p) => ({ ...p, bank: true, quarter: { InterestEarned: cr(500), Income: cr(600), ProfitLossForThePeriod: cr(100), BasicEarningsPerShareAfterExtraordinaryItems: "7.5" } }));
    const keys = quarterlyTable(bank).rows.map((r) => r.key);
    expect(keys).toContain("interest_earned");
    expect(keys).not.toContain("opm");
  });
});

describe("half-yearly tables", () => {
  it("keeps only the quarters that carry a balance sheet or cash flow", () => {
    const withSheets = periods.map((p, i) => (i % 2 === 0 ? { ...p, instant: { Assets: cr(5000 + i), BorrowingsNoncurrent: cr(10), BorrowingsCurrent: cr(5) }, ytd: { CashFlowsFromUsedInOperatingActivities: cr(300) } } : p));
    const b = balanceTable(withSheets);
    expect(b.columns.map((c) => c.label)).toEqual(["Sep 2025", "Mar 2026", "Sep 2026"]);
    expect(b.rows.find((r) => r.key === "borrowings")?.values).toEqual([15e7, 15e7, 15e7]);
    expect(b.rows.find((r) => r.key === "assets")?.yoy?.at(-1)).toBeCloseTo(((5000 - 5004) / 5004) * 100, 6);
    expect(cashTable(withSheets).columns).toHaveLength(3);
    expect(b.rows.every((r) => r.qoq === null)).toBe(true);
  });
});
