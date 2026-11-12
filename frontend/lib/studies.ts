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
