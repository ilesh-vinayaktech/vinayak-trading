/** How the price chart behaves when you move it with the mouse. Kept as small pure functions so the rules are testable without a canvas. */

/** Within this many bars of the first loaded bar (or past it) the user is reaching for earlier history. */
export const EXTEND_WITHIN_BARS = 3;

/** True when a view the USER moved has reached the left edge of what is loaded: time to load earlier history. */
export function reachedLeftEdge(range: { from: number } | null, movedByUser: boolean): boolean {
  return movedByUser && range !== null && range.from < EXTEND_WITHIN_BARS;
}

export type SavedView<T> = { key: string; range: { from: T; to: T } };

/** After earlier history was loaded the chart is rebuilt; keep the user where they were instead of jumping to "fit everything".
 *  Anything else (a new stock, timeframe or range preset) fits the data. */
export function viewToRestore<T>(saved: SavedView<T> | null, key: string, extending: boolean): { from: T; to: T } | null {
  return extending && saved !== null && saved.key === key ? saved.range : null;
}
