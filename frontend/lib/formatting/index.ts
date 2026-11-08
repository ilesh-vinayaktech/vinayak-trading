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
