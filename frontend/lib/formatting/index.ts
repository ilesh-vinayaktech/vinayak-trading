/** Display helpers only. Numbers shown are the strings the API returned; nothing is recomputed. */

export function fmtInt(n: number): string {
  return n.toLocaleString("en-IN");
}

export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export function shortHash(h: string, n = 12): string {
  return h.length > n ? h.slice(0, n) : h;
}

export function humanize(code: string): string {
  return code.toLowerCase().replace(/_/g, " ");
}

/** Chart libraries need numbers; this is for plotting only and never for displayed figures. */
export function plotNumber(s: string): number {
  return Number.parseFloat(s);
}

/** A time in Indian Standard Time, for things that follow the exchange day (Kite tokens end at 06:00 IST). */
export function fmtIst(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : `${new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }).format(d)} IST`;
}

/** "just now", "5 min ago", "3 h ago", "2 d ago"; older than a month falls back to the date. */
export function fmtRelative(iso: string, now: number = Date.now()): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 31) return `${d} d ago`;
  return new Date(t).toISOString().slice(0, 10);
}
