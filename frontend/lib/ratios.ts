import type { Ratios } from "@/lib/schemas";

export type RatioRow = Ratios["ratios"][number];
export type Group = RatioRow["group"];

export const GROUPS: { key: Group; title: string; blurb: string }[] = [
  { key: "valuation", title: "Valuation: what you pay", blurb: "Price against what the business earns and owns. Cheap is not the same as good: compare with the company's own past and with similar companies." },
  { key: "profitability", title: "Profitability: how well it makes money", blurb: "How much profit the business squeezes from its sales, assets and owners' money." },
  { key: "growth", title: "Growth: is it getting bigger", blurb: "Compared with the same period a year earlier." },
  { key: "strength", title: "Financial strength: could it ride out a bad patch", blurb: "Debt, ability to pay bills, and (for banks) the share of bad loans." },
  { key: "efficiency", title: "Efficiency: how hard it works its assets", blurb: "Industry-dependent: read these against similar companies, not against a fixed number." },
  { key: "cash", title: "Cash: is profit real", blurb: "Profit on paper against money actually received." },
];

const group = (n: number, digits = 2) => n.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** A ratio value as people read it: 21.0%, 17.2×, 89 days, ₹8.8 lakh cr. */
export function formatRatio(unit: RatioRow["unit"], raw: string | null): string {
  if (raw === null) return "–";
  const n = Number(raw);
  if (!Number.isFinite(n)) return "–";
  switch (unit) {
    case "pct": return `${group(n, 1)}%`;
    case "x": return `${group(n, 2)}×`;
    case "days": return `${group(n, 0)} days`;
    case "inr": return `₹${group(n, 2)}`;
    case "crore": {
      const sign = n < 0 ? "−" : "";
      const a = Math.abs(n);
      return a >= 1e5 ? `${sign}₹${group(a / 1e5)} lakh cr` : `${sign}₹${group(a, a >= 100 ? 0 : 1)} cr`;
    }
  }
}

/** How a ratio moved against a year ago, in the ratio's own units, and whether that is better, worse or unjudged. */
export function versusYearAgo(r: RatioRow): { text: string; tone: "good" | "bad" | "neutral" } | null {
  if (r.value === null || r.year_ago === null) return null;
  const d = Number(r.value) - Number(r.year_ago);
  if (!Number.isFinite(d)) return null;
  const unit = r.unit === "pct" ? " pts" : r.unit === "x" ? "×" : r.unit === "days" ? " days" : "";
  const tiny = Math.abs(d) < (r.unit === "x" ? 0.05 : r.unit === "days" ? 1 : 0.5);
  const text = tiny ? "about the same" : `${d > 0 ? "up" : "down"} ${group(Math.abs(d), r.unit === "days" ? 0 : r.unit === "crore" ? 0 : 1)}${unit}`;
  if (tiny || r.better === null) return { text, tone: "neutral" };
  return { text, tone: (d > 0) === (r.better === "high") ? "good" : "bad" };
}

const RULE_LABEL = { good: "Strong", ok: "Fair", weak: "Weak" } as const;
const VALUATION_LABEL = { good: "Cheaper than usual", ok: "Usual range", weak: "Pricier than usual" } as const;
const PAST_LABEL = { good: "Better than usual", ok: "Usual range", weak: "Worse than usual" } as const;

/** What to print in the Reading column: a verdict against a rule of thumb, against the company's own past, or why there is none. */
export function readingText(r: RatioRow): string {
  if (r.reading !== null) {
    if (r.reading_basis === "own_past") return (r.group === "valuation" ? VALUATION_LABEL : PAST_LABEL)[r.reading];
    return RULE_LABEL[r.reading];
  }
  if (r.value === null || r.better === null) return "–"; // no value, or a size rather than good or bad
  return "not enough history";
}

/** The six ratios people look at first, in order; only those that apply and have a value. */
export function snapshot(r: Ratios): RatioRow[] {
  const order = r.bank ? ["market_cap", "pe", "pb", "roe", "gross_npa", "dividend_yield"] : ["market_cap", "pe", "pb", "roe", "debt_to_equity", "dividend_yield"];
  return order.flatMap((k) => { const x = r.ratios.find((y) => y.key === k); return x ? [x] : []; });
}
