/** Number formats for the NSE smart-money views (Indian digit grouping). */
export const inr = (v: number | null | undefined, digits = 2) => (v === null || v === undefined ? "–" : v.toLocaleString("en-IN", { maximumFractionDigits: digits }));
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${v.toFixed(2)}%`);
export const cr = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `₹${inr(v)} Cr`);
/** A signed change in percentage points, e.g. "+0.52 pts"; null when either filing lacks the figure. */
export const delta = (now: number | null | undefined, before: number | null | undefined) => (now == null || before == null ? null : now - before);
export const signed = (v: number | null, unit = "") => (v === null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(2)}${unit}`);
export const tone = (v: number | null) => (v === null || v === 0 ? "" : v > 0 ? "text-emerald-700" : "text-red-700");
export const day = (iso: string | null) => (iso ? iso.replace("T", " ").slice(0, 16) : "–");
