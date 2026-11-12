/** Display helpers only. Numbers shown are the strings the API returned; nothing is recomputed. */

export function fmtInt(n: number): string {
  return n.toLocaleString("en-IN");
}

export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
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
  return Number.isNaN(d.getTime())
    ? iso
    : `${new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }).format(d)} IST`;
}

/** "just now", "5 min ago", "3 h ago", "2 d ago" - and for a time still ahead "in 5 min", "in 20 h", "in 2 d"; a month or more away falls back to the date. */
export function fmtRelative(iso: string, now: number = Date.now()): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = Math.round((now - t) / 1000);
  const s = Math.abs(diff);
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  const h = Math.round(m / 60);
  const d = Math.round(h / 24);
  const unit =
    m < 60 ? `${m} min` : h < 24 ? `${h} h` : d < 31 ? `${d} d` : null;
  if (unit === null) return new Date(t).toISOString().slice(0, 10);
  return diff < 0 ? `in ${unit}` : `${unit} ago`;
}

/** A rupee amount from a decimal STRING ("1234567.5" -> "12,34,567.50"), grouped the Indian way. String work only: nothing is
 * converted to a float, so no digit of a money figure is ever lost or invented in the browser. */
export function fmtMoney(s: string, places = 2): string {
  const m = /^(-?)(\d+)(?:\.(\d+))?$/.exec(s.trim());
  if (!m) return s;
  const [, sign, whole = "0", frac = ""] = m;
  const digits = frac.padEnd(places, "0").slice(0, places);
  const last3 = whole.slice(-3);
  const rest = whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",");
  const grouped = rest ? `${rest},${last3}` : last3;
  return `${sign}${grouped}${places > 0 ? `.${digits}` : ""}`;
}

/** A length of time in the two most useful units: "40 s", "12 min", "2 h 10 min", "1 d 3 h". */
export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 24) return m % 60 === 0 ? `${h} h` : `${h} h ${m % 60} min`;
  const d = Math.floor(h / 24);
  return h % 24 === 0 ? `${d} d` : `${d} d ${h % 24} h`;
}
