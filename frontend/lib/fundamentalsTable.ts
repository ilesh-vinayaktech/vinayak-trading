import type { Period } from "@/lib/fundamentals";
import { quarterName } from "@/lib/fundamentals";
import { yearAgo } from "@/lib/fundamentalsSummary";

/** A results table the way finance sites print it: quarters across (oldest to newest), lines down, growth under the key lines. */
export type Kind = "amount" | "percent" | "pershare";
export type Row = { key: string; label: string; kind: Kind; strong: boolean; values: (number | undefined)[]; qoq: (number | null)[] | null; yoy: (number | null)[] | null };
export type Table = { columns: { label: string; end: string }[]; rows: Row[] };

type Figures = Record<string, string>;
const num = (f: Figures, names: string[]): number | undefined => {
  for (const n of names) {
    const v = f[n];
    if (v !== undefined && Number.isFinite(Number(v))) return Number(v);
  }
  return undefined;
};

const DAY = 86_400_000;
const daysBetween = (a: string, b: string) => Math.round((Date.parse(a) - Date.parse(b)) / DAY);

/** Growth in percent; off a negative base the sign still reads the right way (loss narrowing is positive). Null if no base. */
export function growth(cur: number | undefined, prev: number | undefined): number | null {
  if (cur === undefined || prev === undefined || prev === 0) return null;
  return ((cur - prev) / Math.abs(prev)) * 100;
}

type Spec = { key: string; label: string; kind?: Kind; strong?: boolean; growth?: boolean; get: (f: Figures) => number | undefined };

const PAT = ["ProfitLossForPeriod", "ProfitLossForThePeriod"];
const EPS = ["BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "BasicEarningsPerShareAfterExtraordinaryItems"];

const operating = (f: Figures) => {
  const r = num(f, ["RevenueFromOperations", "Income"]), e = num(f, ["Expenses"]);
  return r === undefined || e === undefined ? undefined : r - (e - (num(f, ["FinanceCosts"]) ?? 0) - (num(f, ["DepreciationDepletionAndAmortisationExpense"]) ?? 0));
};
const pct = (a: (f: Figures) => number | undefined, b: (f: Figures) => number | undefined) => (f: Figures) => {
  const x = a(f), y = b(f);
  return x === undefined || !y ? undefined : (x / y) * 100;
};
const revenue = (f: Figures) => num(f, ["RevenueFromOperations", "Income"]);
const profit = (f: Figures) => num(f, PAT);

const COMPANY: Spec[] = [
  { key: "revenue", label: "Revenue", strong: true, growth: true, get: revenue },
  { key: "expenses", label: "Expenses", get: (f) => num(f, ["Expenses"]) },
  { key: "operating", label: "Operating profit", strong: true, growth: true, get: operating },
  { key: "opm", label: "Operating margin", kind: "percent", get: pct(operating, revenue) },
  { key: "other", label: "Other income", get: (f) => num(f, ["OtherIncome"]) },
  { key: "interest", label: "Interest", get: (f) => num(f, ["FinanceCosts"]) },
  { key: "depreciation", label: "Depreciation", get: (f) => num(f, ["DepreciationDepletionAndAmortisationExpense"]) },
  { key: "pbt", label: "Profit before tax", strong: true, growth: true, get: (f) => num(f, ["ProfitBeforeTax"]) },
  { key: "tax", label: "Tax", get: (f) => num(f, ["TaxExpense"]) },
  { key: "pat", label: "Net profit", strong: true, growth: true, get: profit },
  { key: "npm", label: "Net profit margin", kind: "percent", get: pct(profit, revenue) },
  { key: "eps", label: "EPS (₹)", kind: "pershare", strong: true, growth: true, get: (f) => num(f, EPS) },
];

const BANK: Spec[] = [
  { key: "interest_earned", label: "Interest earned", get: (f) => num(f, ["InterestEarned"]) },
  { key: "other", label: "Other income", get: (f) => num(f, ["OtherIncome"]) },
  { key: "income", label: "Total income", strong: true, growth: true, get: (f) => num(f, ["Income"]) },
  { key: "interest_paid", label: "Interest paid", get: (f) => num(f, ["InterestExpended"]) },
  { key: "opex", label: "Operating expenses", get: (f) => num(f, ["OperatingExpenses"]) },
  { key: "operating", label: "Profit before provisions", strong: true, growth: true, get: (f) => num(f, ["OperatingProfitBeforeProvisionAndContingencies"]) },
  { key: "provisions", label: "Provisions", get: (f) => num(f, ["ProvisionsOtherThanTaxAndContingencies"]) },
  { key: "pbt", label: "Profit before tax", strong: true, growth: true, get: (f) => num(f, ["ProfitLossFromOrdinaryActivitiesBeforeTax", "ProfitBeforeTax"]) },
  { key: "tax", label: "Tax", get: (f) => num(f, ["TaxExpense"]) },
  { key: "pat", label: "Net profit", strong: true, growth: true, get: profit },
  { key: "npm", label: "Net profit margin", kind: "percent", get: pct(profit, (f) => num(f, ["Income"])) },
  { key: "eps", label: "EPS (₹)", kind: "pershare", strong: true, growth: true, get: (f) => num(f, EPS) },
];

const debt = (f: Figures) => {
  const a = num(f, ["BorrowingsNoncurrent"]), b = num(f, ["BorrowingsCurrent"]);
  return a === undefined && b === undefined ? undefined : (a ?? 0) + (b ?? 0);
};
const BALANCE: Spec[] = [
  { key: "assets", label: "Total assets", strong: true, growth: true, get: (f) => num(f, ["Assets"]) },
  { key: "noncurrent_assets", label: "Non-current assets", get: (f) => num(f, ["NoncurrentAssets"]) },
  { key: "current_assets", label: "Current assets", get: (f) => num(f, ["CurrentAssets"]) },
  { key: "receivables", label: "Trade receivables", get: (f) => num(f, ["TradeReceivablesCurrent"]) },
  { key: "inventories", label: "Inventories", get: (f) => num(f, ["Inventories"]) },
  { key: "cash", label: "Cash and equivalents", get: (f) => num(f, ["CashAndCashEquivalents"]) },
  { key: "equity", label: "Owners' equity", strong: true, growth: true, get: (f) => num(f, ["Equity"]) },
  { key: "borrowings", label: "Borrowings", strong: true, growth: true, get: debt },
  { key: "payables", label: "Trade payables", get: (f) => num(f, ["TradePayablesCurrent"]) },
  { key: "liabilities", label: "Total liabilities", get: (f) => num(f, ["Liabilities"]) },
];

const CASH: Spec[] = [
  { key: "cfo", label: "Cash from operations", strong: true, get: (f) => num(f, ["CashFlowsFromUsedInOperatingActivities"]) },
  { key: "cfi", label: "Cash from investing", get: (f) => num(f, ["CashFlowsFromUsedInInvestingActivities"]) },
  { key: "cff", label: "Cash from financing", get: (f) => num(f, ["CashFlowsFromUsedInFinancingActivities"]) },
  { key: "net", label: "Net change in cash", strong: true, get: (f) => num(f, ["IncreaseDecreaseInCashAndCashEquivalents"]) },
  { key: "capex", label: "Spent on plant and equipment", get: (f) => num(f, ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"]) },
  { key: "dividends", label: "Dividends paid", get: (f) => num(f, ["DividendsPaidClassifiedAsFinancingActivities"]) },
];

function build(all: Period[], specs: Spec[], scope: "quarter" | "ytd" | "instant", keep: (p: Period) => boolean, withQoq: boolean): Table {
  const cols = all.filter(keep).sort((a, b) => a.period_end.localeCompare(b.period_end)); // oldest first
  const prevQuarter = (p: Period) => all.find((o) => Math.abs(daysBetween(p.period_end, o.period_end) - 91) <= 12);
  const rows = specs
    .map((s): Row => {
      const at = (p: Period | undefined) => (p ? s.get(p[scope]) : undefined);
      return {
        key: s.key, label: s.label, kind: s.kind ?? "amount", strong: s.strong ?? false,
        values: cols.map(at),
        qoq: s.growth && withQoq ? cols.map((p) => growth(at(p), at(prevQuarter(p)))) : null,
        yoy: s.growth ? cols.map((p) => growth(at(p), at(yearAgo(all, p)))) : null,
      };
    })
    .filter((r) => r.values.some((v) => v !== undefined));
  return { columns: cols.map((p) => ({ label: quarterName(p.period_end), end: p.period_end })), rows };
}

/** Quarterly results; banks get their own lines. `periods` is newest first. */
export function quarterlyTable(periods: Period[]): Table {
  return build(periods, periods[0]?.bank ? BANK : COMPANY, "quarter", () => true, true);
}
export function balanceTable(periods: Period[]): Table {
  return build(periods, BALANCE, "instant", (p) => num(p.instant, ["Assets", "Equity"]) !== undefined, false);
}
export function cashTable(periods: Period[]): Table {
  return build(periods, CASH, "ytd", (p) => num(p.ytd, ["CashFlowsFromUsedInOperatingActivities"]) !== undefined, false);
}
