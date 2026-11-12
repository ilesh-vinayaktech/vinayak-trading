import type { Fundamentals } from "@/lib/schemas";

export type Period = Fundamentals["periods"][number];
export type Scope = "quarter" | "ytd" | "instant";

/** "ProfitLossForPeriod" -> "Profit loss for period". */
export function label(name: string): string {
  const words = name.replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// Figures that are not rupee amounts: shown as reported, never scaled to crore.
const PER_UNIT = /PerShare|Earnings(Loss)?Per|FaceValue|Ratio|Percentage|Number/i;

/** Rupees -> crore with 2 decimals (Indian grouping); per-share figures as reported. */
export function figure(name: string, raw: string | undefined): string {
  if (raw === undefined) return "–";
  const n = Number(raw);
  if (!Number.isFinite(n)) return raw;
  if (PER_UNIT.test(name)) return n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return (n / 1e7).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const KEY_LINES = [
  "RevenueFromOperations", "OtherIncome", "Income", "Expenses", "EmployeeBenefitExpense", "FinanceCosts",
  "DepreciationDepletionAndAmortisationExpense", "ProfitBeforeTax", "TaxExpense", "ProfitLossForPeriod",
  "ProfitOrLossAttributableToOwnersOfParent", "BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
  "DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "Assets", "NonCurrentAssets", "CurrentAssets",
  "Equity", "Liabilities", "NoncurrentLiabilities", "CurrentLiabilities", "EquityAndLiabilities",
  "CashFlowsFromUsedInOperatingActivities", "CashFlowsFromUsedInInvestingActivities", "CashFlowsFromUsedInFinancingActivities",
];

/** Every line any shown period reports for a scope: the key lines first, the rest A-Z. */
export function lines(periods: Period[], scope: Scope, filter = ""): string[] {
  const names = new Set<string>();
  for (const p of periods) for (const k of Object.keys(p[scope])) names.add(k);
  const f = filter.trim().toLowerCase();
  const rank = (n: string) => { const i = KEY_LINES.indexOf(n); return i < 0 ? KEY_LINES.length : i; };
  return [...names].filter((n) => !f || label(n).toLowerCase().includes(f)).sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
}

/** "Sep 2026" for a quarter ending 2026-09-30. */
export function quarterName(end: string): string {
  const [y, m] = end.split("-").map(Number);
  return `${["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][(m ?? 1) - 1]} ${y}`;
}
