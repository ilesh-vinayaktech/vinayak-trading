import { fmtMoney } from "@/lib/formatting";
/** The arithmetic of a backtest study's form, kept out of the components so it is tested on its own. Dates are ISO days. */

const DAY_MS = 86_400_000;
const days = (a: string, b: string) => Math.round((Date.parse(`${b}T00:00:00Z`) - Date.parse(`${a}T00:00:00Z`)) / DAY_MS);

/** How many parameter combinations (trials) a grid makes: every one counts against the strategy. */
export function trialCount(grid: Record<string, number[]>): number {
  const sizes = Object.values(grid).map((v) => v.length);
  return sizes.length === 0 ? 0 : sizes.reduce((a, b) => a * b, 1);
}

/** The holdout's share of the study, 0..1; null when the dates do not make a study. */
export function holdoutShare(start: string, end: string, holdout: string): number | null {
  const whole = days(start, end);
  if (!start || !end || !holdout || !(whole > 0)) return null;
  return days(holdout, end) / whole;
}

/** The holdout start that leaves the last `percent` of the study untouched. */
export function holdoutFor(start: string, end: string, percent: number): string {
  const whole = days(start, end);
  const d = new Date(Date.parse(`${end}T00:00:00Z`) - Math.round((whole * percent) / 100) * DAY_MS);
  return d.toISOString().slice(0, 10);
}

/** What each pass/fail threshold means, in plain words (definitions: docs/validation.md). */
export const THRESHOLD_LABELS: Record<string, string> = {
  min_oos_sharpe: "Out-of-sample Sharpe, at least",
  min_dsr: "Deflated Sharpe probability, at least",
  max_pbo: "Probability of overfitting, at most",
  owner_max_drawdown: "Worst drawdown you accept (0.25 = 25%)",
  max_drawdown_vs_benchmark: "Drawdown against the benchmark's, at most (times)",
  min_benchmark_drawdown: "Benchmark drawdown below which that ratio is not used",
  min_sharpe_over_benchmark: "Sharpe above the benchmark's, at least",
  plateau_tolerance: "Nearby settings may lose at most this share of the Sharpe",
  max_top3_concentration: "Share of profit from the best 3 stocks, months or trades, at most",
  min_oos_days: "Out-of-sample trading days, at least",
  min_regimes: "Market regimes covered, at least",
  max_window_share: "One test window's share of the gains, at most",
};

/** The gates in plain words, with the figure each one judged (from the stored evidence) so a pass is as readable as a fail. */
export const GATE_LABELS: Record<string, string> = {
  holdout_sharpe: "Sharpe on the holdout",
  holdout_drawdown: "Worst drop on the holdout",
  holdout_beats_benchmark: "Beats the index on the holdout",
  oos_days: "Enough days judged out of sample",
  regimes: "Tested in more than one market period",
  window_share: "No single window carries the result",
  oos_sharpe: "Out-of-sample Sharpe",
  deflated_sharpe: "Deflated Sharpe (allows for luck across all the tries)",
  overfitting_probability: "Chance the best settings are overfitted",
  max_drawdown: "Worst drop within the limits",
  beats_benchmark: "Beats the index",
  parameter_plateau: "Holds up when settings move one step",
  survives_2x_costs: "Still profitable at double the costs",
  survives_3x_capital: "Still profitable at triple the capital",
  concentration_instrument: "Profit not just from three stocks",
  concentration_month: "Profit not just from three months",
  concentration_trade: "Profit not just from three trades",
};

export type GateState = "PASS" | "FAIL" | "INSUFFICIENT_EVIDENCE" | "NOT_APPLICABLE";

/** What a check says, in one of four ways. Missing evidence is never shown as a weak pass or an ordinary fail; reports saved before the
 * four-way status carry only `passed` and the text "evidence missing", which is read the same way. */
export function gateState(g: { passed: boolean; detail: string; status?: GateState }): GateState {
  if (g.status) return g.status;
  if (!g.passed && g.detail === "evidence missing") return "INSUFFICIENT_EVIDENCE";
  return g.passed ? "PASS" : "FAIL";
}

export const GATE_STATE_LABEL: Record<GateState, string> = { PASS: "Pass", FAIL: "Fail", INSUFFICIENT_EVIDENCE: "No evidence", NOT_APPLICABLE: "n/a" };
export const GATE_STATE_TONE: Record<GateState, "good" | "bad" | "warn" | "neutral"> = { PASS: "good", FAIL: "bad", INSUFFICIENT_EVIDENCE: "warn", NOT_APPLICABLE: "neutral" };

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

export function gateValue(name: string, e: Record<string, number | null>): string {
  const n = (k: string) => e[k] ?? null;
  const f = (k: string, fmt: (v: number) => string) => (n(k) === null ? "no evidence" : fmt(n(k) as number));
  switch (name) {
    case "oos_days": return f("oos_days", (v) => `${v.toFixed(0)} days`);
    case "regimes": return f("regimes", (v) => `${v.toFixed(0)} periods`);
    case "window_share": return f("window_share", pct);
    case "oos_sharpe": return f("oos_sharpe", (v) => v.toFixed(2));
    case "deflated_sharpe": return f("dsr", (v) => v.toFixed(3));
    case "overfitting_probability": return f("pbo", (v) => v.toFixed(2));
    case "max_drawdown": return n("max_drawdown") === null ? "no evidence" : `${pct(Math.abs(n("max_drawdown") as number))}${n("benchmark_max_drawdown") === null ? "" : ` vs index ${pct(Math.abs(n("benchmark_max_drawdown") as number))}`}`;
    case "beats_benchmark": return n("oos_sharpe") === null || n("benchmark_sharpe") === null ? "no evidence" : `${(n("oos_sharpe") as number).toFixed(2)} vs index ${(n("benchmark_sharpe") as number).toFixed(2)}`;
    case "parameter_plateau": return f("plateau_drop", (v) => `${pct(v)} lost`);
    case "survives_2x_costs": return f("sharpe_2x_costs", (v) => `Sharpe ${v.toFixed(2)}`);
    case "survives_3x_capital": return f("sharpe_3x_capital", (v) => `Sharpe ${v.toFixed(2)}`);
    case "concentration_instrument": return f("top3_instrument", pct);
    case "concentration_month": return f("top3_month", pct);
    case "concentration_trade": return f("top3_trade", pct);
    default: return "";
  }
}

/** Advice, not rules: order limits that do not fit the size of a position make a backtest behave oddly. A position is capital
 *  divided by the number of positions, so the largest position uses the fewest positions in the grid. */
export function orderSizeWarnings(capital: string, maxPositions: number[], min: string, max: string): string[] {
  const cap = Number(capital);
  if (!(cap > 0) || maxPositions.length === 0) return [];
  const biggest = cap / Math.min(...maxPositions);
  const smallest = cap / Math.max(...maxPositions);
  const rs = (n: number) => `₹${fmtMoney(String(Math.round(n)), 0)}`;
  const out: string[] = [];
  const hi = Number(max);
  if (max.trim() !== "" && hi > 0 && hi < biggest) {
    const days = Math.ceil(biggest / hi);
    if (days > 3) {
      out.push(
        `A position can be ${rs(biggest)} (${rs(cap)} over ${Math.min(...maxPositions)} positions), but the largest order is ${rs(hi)}, so building or selling one takes about ${days} days. ` +
          `Sales lag the signals, so the account can hold more stocks than the limit for a while. Consider a largest order of ${rs(biggest / 3)} or more, or none.`,
      );
    }
  }
  const lo = Number(min);
  if (min.trim() !== "" && lo > smallest) {
    out.push(`The smallest order (${rs(lo)}) is more than a position can be (${rs(smallest)} with ${Math.max(...maxPositions)} positions), so those buys would never be placed.`);
  }
  return out;
}
