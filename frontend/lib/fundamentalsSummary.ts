import type { Period } from "@/lib/fundamentals";
import { quarterName } from "@/lib/fundamentals";

/** A plain-language reading of a company's results: what is happening, and is it getting better. Pure; no judgement is hidden in the UI. */
export type Tone = "good" | "bad" | "neutral";
export type Change =
  | { kind: "pct"; value: number }
  | { kind: "turnaround" } // loss a year ago, profit now
  | { kind: "loss_narrowed" }
  | { kind: "loss_widened" }
  | { kind: "slipped_to_loss" }; // profit a year ago, loss now

export type Tile = {
  key: "sales" | "profit" | "margin" | "eps";
  title: string;
  meaning: string;
  latest: string;
  quarter: string;
  vsYear: string;
  tone: Tone;
  momentum: string | null;
  series: { label: string; value: number }[]; // oldest first
};
export type Check = { tone: Tone; text: string };
export type Summary = { verdict: "good" | "mixed" | "weak" | "unknown"; headline: string; checks: Check[]; tiles: Tile[] };

const SALES = ["RevenueFromOperations", "Income"];
const PROFIT = ["ProfitLossForPeriod", "ProfitLossForThePeriod"];
const EPS = ["BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations", "BasicEarningsPerShareAfterExtraordinaryItems"];

function pick(figures: Record<string, string>, names: string[]): number | undefined {
  for (const n of names) {
    const v = figures[n];
    if (v !== undefined && Number.isFinite(Number(v))) return Number(v);
  }
  return undefined;
}

const DAY = 86_400_000;
const days = (a: string, b: string) => Math.round((Date.parse(a) - Date.parse(b)) / DAY);
/** The same quarter one year earlier, matched by date (never by position). */
export function yearAgo(periods: Period[], p: Period): Period | undefined {
  return periods.find((o) => Math.abs(days(p.period_end, o.period_end) - 365) <= 10);
}

export function change(cur: number | undefined, prev: number | undefined): Change | null {
  if (cur === undefined || prev === undefined) return null;
  if (prev > 0 && cur < 0) return { kind: "slipped_to_loss" };
  if (prev > 0) return { kind: "pct", value: ((cur - prev) / prev) * 100 };
  if (cur > 0) return { kind: "turnaround" };
  if (cur > prev) return { kind: "loss_narrowed" };
  if (cur < prev) return { kind: "loss_widened" };
  return null;
}

function tone(c: Change | null): Tone {
  if (!c) return "neutral";
  if (c.kind === "pct") return c.value > 5 ? "good" : c.value < -5 ? "bad" : "neutral";
  return c.kind === "turnaround" || c.kind === "loss_narrowed" ? "good" : "bad";
}

function words(c: Change | null): string {
  if (!c) return "no year-ago figure to compare with";
  switch (c.kind) {
    case "pct": return Math.abs(c.value) < 1 ? "about the same as a year ago" : `${c.value > 0 ? "up" : "down"} ${Math.abs(c.value).toFixed(0)}% from a year ago`;
    case "turnaround": return "a profit now, against a loss a year ago";
    case "loss_narrowed": return "still a loss, but smaller than a year ago";
    case "loss_widened": return "a bigger loss than a year ago";
    case "slipped_to_loss": return "a loss now, against a profit a year ago";
  }
}

/** Rupees to crore, or lakh crore for the very large. */
export function crore(rupees: number): string {
  const c = Math.abs(rupees / 1e7);
  const sign = rupees < 0 ? "−" : "";
  if (c >= 1e5) return `${sign}₹${(c / 1e5).toFixed(2)} lakh cr`;
  if (c >= 100) return `${sign}₹${Math.round(c).toLocaleString("en-IN")} cr`;
  return `${sign}₹${c.toFixed(1)} cr`;
}

const rupee = (n: number) => `${n < 0 ? "−" : ""}₹${Math.abs(n).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

/** Is growth speeding up or slowing: this quarter's year-on-year change against the previous quarter's. */
function momentum(periods: Period[], value: (p: Period) => number | undefined): string | null {
  const yoy = (p: Period | undefined): Change | null => {
    const a = p && yearAgo(periods, p);
    return p && a ? change(value(p), value(a)) : null;
  };
  const a = yoy(periods[0]), b = yoy(periods[1]);
  if (a?.kind !== "pct" || b?.kind !== "pct") return null;
  const d = a.value - b.value;
  return d > 3 ? "growth is speeding up" : d < -3 ? "growth is slowing down" : null;
}

export function summarize(all: Period[]): Summary {
  const periods = all; // newest first
  const latest = periods[0];
  if (!latest) return { verdict: "unknown", headline: "No results to read yet.", checks: [], tiles: [] };
  const q = (p: Period, names: string[]) => pick(p.quarter, names);
  const sales = (p: Period) => q(p, SALES);
  const profit = (p: Period) => q(p, PROFIT);
  const margin = (p: Period) => {
    const s = sales(p), n = profit(p);
    return s && n !== undefined ? (n / s) * 100 : undefined;
  };
  const eps = (p: Period) => q(p, EPS);
  const ago = yearAgo(periods, latest);
  const series = (f: (p: Period) => number | undefined) =>
    periods.slice(0, 8).flatMap((p) => { const v = f(p); return v === undefined ? [] : [{ label: quarterName(p.period_end), value: v }]; }).reverse();
  const qName = quarterName(latest.period_end);

  const salesChange = change(sales(latest), ago && sales(ago));
  const profitChange = change(profit(latest), ago && profit(ago));
  const epsChange = change(eps(latest), ago && eps(ago));
  const m = margin(latest), mAgo = ago && margin(ago);
  const marginDelta = m !== undefined && mAgo !== undefined ? m - mAgo : null;

  const tiles: Tile[] = [];
  const s0 = sales(latest);
  if (s0 !== undefined) tiles.push({ key: "sales", title: latest.bank ? "Total income" : "Sales", meaning: latest.bank ? "Interest and fees the bank earned this quarter." : "Money the company earned from its business this quarter.", latest: crore(s0), quarter: qName, vsYear: words(salesChange), tone: tone(salesChange), momentum: momentum(periods, sales), series: series(sales) });
  const p0 = profit(latest);
  if (p0 !== undefined) tiles.push({ key: "profit", title: "Profit", meaning: "What was left after all costs, interest and tax.", latest: crore(p0), quarter: qName, vsYear: words(profitChange), tone: tone(profitChange), momentum: momentum(periods, profit), series: series(profit) });
  if (m !== undefined) tiles.push({ key: "margin", title: "Profit margin", meaning: "Profit kept out of every ₹100 of sales (negative: a loss). Higher is healthier.", latest: `${m < 0 ? "−" : ""}₹${Math.abs(m).toFixed(1)} per ₹100`, quarter: qName, vsYear: marginDelta === null ? "no year-ago figure to compare with" : Math.abs(marginDelta) < 0.5 ? "about the same as a year ago" : `${marginDelta > 0 ? "better" : "worse"} by ₹${Math.abs(marginDelta).toFixed(1)} than a year ago`, tone: marginDelta === null ? "neutral" : marginDelta > 0.5 ? "good" : marginDelta < -0.5 ? "bad" : "neutral", momentum: null, series: series(margin) });
  const e0 = eps(latest);
  if (e0 !== undefined) tiles.push({ key: "eps", title: "Earnings per share", meaning: "Profit for each share you would own.", latest: rupee(e0), quarter: qName, vsYear: words(epsChange), tone: tone(epsChange), momentum: null, series: series(eps) });

  const checks: Check[] = [];
  // consistency: how many of the last four quarters beat the same quarter a year before
  const recent = periods.slice(0, 4).map((p) => { const a = yearAgo(periods, p); return a ? change(profit(p), profit(a)) : null; }).filter((c): c is Change => c !== null);
  if (recent.length >= 3) {
    const up = recent.filter((c) => (c.kind === "pct" ? c.value > 0 : c.kind === "turnaround" || c.kind === "loss_narrowed")).length;
    checks.push({ tone: up === recent.length ? "good" : up >= Math.ceil(recent.length / 2) ? "neutral" : "bad", text: `Profit was ahead of the year-before level in ${up} of the last ${recent.length} quarters.` });
  }
  // cash backing: cash from operations against profit, year to date (cash flow is filed half-yearly)
  const cashP = periods.find((p) => pick(p.ytd, ["CashFlowsFromUsedInOperatingActivities"]) !== undefined);
  let cashScore = 0;
  if (cashP) {
    const cfo = pick(cashP.ytd, ["CashFlowsFromUsedInOperatingActivities"]) as number;
    const pat = pick(cashP.ytd, PROFIT);
    const bank = cashP.bank;
    if (!bank && pat !== undefined && pat > 0) {
      const ratio = cfo / pat;
      cashScore = ratio >= 0.8 ? 1 : ratio < 0.4 ? -1 : 0;
      checks.push({ tone: cashScore > 0 ? "good" : cashScore < 0 ? "bad" : "neutral", text: `Profit turned into cash: the business brought in ${crore(cfo)} from operations against ${crore(pat)} of profit (year so far to ${quarterName(cashP.period_end)}).${cashScore < 0 ? " Profit that is not turning into cash deserves a closer look." : ""}` });
    }
  }
  // debt: borrowings on the latest balance sheet against the one a year before
  const debt = (p: Period) => { const a = pick(p.instant, ["BorrowingsNoncurrent"]), b = pick(p.instant, ["BorrowingsCurrent"]); return a === undefined && b === undefined ? undefined : (a ?? 0) + (b ?? 0); };
  const sheet = periods.find((p) => debt(p) !== undefined);
  let debtScore = 0;
  if (sheet && !sheet.bank) {
    const d = debt(sheet) as number;
    const eq = pick(sheet.instant, ["Equity"]);
    const prior = yearAgo(periods, sheet);
    const dPrior = prior ? debt(prior) : undefined;
    if (d === 0) { debtScore = 1; checks.push({ tone: "good", text: `No borrowings on the ${quarterName(sheet.period_end)} balance sheet: the company is debt-free.` }); }
    else {
      const cmp = dPrior !== undefined && dPrior > 0 ? ((d - dPrior) / dPrior) * 100 : null;
      debtScore = cmp === null ? 0 : cmp < -10 ? 1 : cmp > 20 ? -1 : 0;
      const dte = eq && eq > 0 ? ` That is ₹${(d / eq).toFixed(2)} of debt for every ₹1 of owners' money.` : "";
      checks.push({ tone: debtScore > 0 ? "good" : debtScore < 0 ? "bad" : "neutral", text: `Borrowings are ${crore(d)}${cmp === null ? "" : cmp > 5 ? `, up ${cmp.toFixed(0)}% from a year earlier` : cmp < -5 ? `, down ${Math.abs(cmp).toFixed(0)}% from a year earlier` : ", about the same as a year earlier"}.${dte}` });
    }
  }

  const score =
    (tone(salesChange) === "good" ? 1 : tone(salesChange) === "bad" ? -1 : 0) +
    (tone(profitChange) === "good" ? 1 : tone(profitChange) === "bad" ? -1 : 0) +
    (marginDelta === null ? 0 : marginDelta > 0.5 ? 1 : marginDelta < -0.5 ? -1 : 0) +
    cashScore + debtScore;
  const scored = salesChange !== null || profitChange !== null;
  const losing = p0 !== undefined && p0 < 0;
  const shrinking = profitChange !== null && tone(profitChange) === "good";
  if (losing) checks.unshift({ tone: "bad", text: `The company lost ${crore(Math.abs(p0 as number))} this quarter: it spent more than it earned.` });
  // a company that is losing money is never called healthy, whatever the direction
  const verdict = !scored ? "unknown" : losing ? (shrinking ? "mixed" : "weak") : score >= 2 ? "good" : score <= -2 ? "weak" : "mixed";
  const speed = tiles.map((t) => t.momentum).find((x) => x !== null);
  const headline = {
    good: "Looking healthy: sales and profit are moving the right way.",
    mixed: losing ? "Still losing money, though the loss is smaller than a year ago." : "A mixed picture: some things are improving, others are not.",
    weak: losing ? "Losing money, and not improving against a year ago." : "Weakening: sales or profit are falling against a year ago.",
    unknown: `Not enough history to compare ${qName} with a year ago.`,
  }[verdict] + (speed && verdict !== "unknown" ? ` Growth is ${speed.replace("growth is ", "")}.` : "");
  return { verdict, headline, checks, tiles };
}
