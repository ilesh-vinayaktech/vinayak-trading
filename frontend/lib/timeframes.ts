import type { Bars, Timeframe } from "@/lib/schemas";

export type Bar = Bars["bars"][number];
export type Intraday = Exclude<Timeframe, "1d">;

export const TIMEFRAME_LABELS: Record<Timeframe, string> = { "1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1h", "1d": "1D" };

/** Longest span (calendar days) the API serves per request; it refuses more, so the UI never asks. */
export const INTRADAY_MAX_DAYS: Record<Intraday, number> = { "1m": 31, "5m": 124, "15m": 366, "30m": 366, "1h": 731 };
/** What a timeframe opens on when picked. */
export const INTRADAY_DEFAULT_DAYS: Record<Intraday, number> = { "1m": 5, "5m": 30, "15m": 90, "30m": 180, "1h": 365 };
export const INTRADAY_PRESETS = [
  { key: "1D", days: 1 },
  { key: "5D", days: 5 },
  { key: "1M", days: 31 },
  { key: "3M", days: 92 },
  { key: "6M", days: 183 },
  { key: "1Y", days: 366 },
  { key: "2Y", days: 731 },
] as const;

const IST_OFFSET_S = 19800; // India has no daylight saving: a fixed +05:30

export const isIntraday = (tf: Timeframe): tf is Intraday => tf !== "1d";

export function shiftDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}

/** First day of a request ending at `end`, never wider than the API allows for the timeframe. */
export function intradayStart(end: string, tf: Intraday, days: number = INTRADAY_DEFAULT_DAYS[tf]): string {
  return shiftDays(end, -Math.min(days, INTRADAY_MAX_DAYS[tf]));
}

/** The chart library draws UTC; shifting an intraday bar's time by +05:30 makes its axis read in IST. */
export function barTime(b: Bar): string | number {
  return b.time !== undefined ? b.time + IST_OFFSET_S : b.date;
}

/** "2025-06-09 09:15" for an intraday bar (IST), the plain date for a daily one. */
export function barLabel(b: Bar): string {
  if (b.time === undefined) return b.date;
  return new Date((b.time + IST_OFFSET_S) * 1000).toISOString().slice(0, 16).replace("T", " ");
}
