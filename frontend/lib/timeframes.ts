import type { Bars, Timeframe } from "@/lib/schemas";

export type Bar = Bars["bars"][number];
export type Intraday = Exclude<Timeframe, "1d" | "1w" | "1mo">;

export const TIMEFRAME_LABELS: Record<Timeframe, string> = {
  "1m": "1m", "3m": "3m", "5m": "5m", "10m": "10m", "15m": "15m", "30m": "30m", "45m": "45m",
  "1h": "1h", "2h": "2h", "3h": "3h", "4h": "4h", "1d": "1D", "1w": "1W", "1mo": "1M",
};

/** The picker's sections, as in a charting terminal: label shown in the menu per timeframe. */
export const TIMEFRAME_GROUPS: { title: string; items: { value: Timeframe; name: string }[] }[] = [
  { title: "MINUTES", items: (["1m", "3m", "5m", "10m", "15m", "30m", "45m"] as const).map((v) => ({ value: v, name: `${parseInt(v, 10)} minute${v === "1m" ? "" : "s"}` })) },
  { title: "HOURS", items: (["1h", "2h", "3h", "4h"] as const).map((v) => ({ value: v, name: `${parseInt(v, 10)} hour${v === "1h" ? "" : "s"}` })) },
  { title: "DAYS", items: [{ value: "1d", name: "1 day" }, { value: "1w", name: "1 week" }, { value: "1mo", name: "1 month" }] },
];

/** Longest span (calendar days) the API serves per request; it refuses more, so the UI never asks. */
export const INTRADAY_MAX_DAYS: Record<Intraday, number> = {
  "1m": 31, "3m": 93, "5m": 124, "10m": 248, "15m": 366, "30m": 366, "45m": 731, "1h": 731, "2h": 1461, "3h": 1461, "4h": 1461,
};
/** What a timeframe opens on when picked. */
export const INTRADAY_DEFAULT_DAYS: Record<Intraday, number> = {
  "1m": 5, "3m": 15, "5m": 30, "10m": 60, "15m": 90, "30m": 180, "45m": 270, "1h": 365, "2h": 730, "3h": 1095, "4h": 1095,
};
export const INTRADAY_PRESETS = [
  { key: "1D", days: 1 },
  { key: "5D", days: 5 },
  { key: "1M", days: 31 },
  { key: "3M", days: 92 },
  { key: "6M", days: 183 },
  { key: "1Y", days: 366 },
  { key: "2Y", days: 731 },
  { key: "4Y", days: 1461 },
] as const;

export const IST_OFFSET_S = 19800; // India has no daylight saving: a fixed +05:30

/** Today in India (the session day), from this browser's clock. */
export function todayIST(now: number = Date.now()): string {
  return new Date(now + IST_OFFSET_S * 1000).toISOString().slice(0, 10);
}

/** The last day an intraday chart should reach: today when the stored bars stop earlier (today's minutes come live). */
export function latestDay(lastStored: string, now: number = Date.now()): string {
  const today = todayIST(now);
  return today > lastStored ? today : lastStored;
}

/** Minute and hour bars: built from minutes, with a UTC `time`. 1d / 1w / 1mo use a plain date axis. */
export const isIntraday = (tf: Timeframe): tf is Intraday => tf !== "1d" && tf !== "1w" && tf !== "1mo";

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
