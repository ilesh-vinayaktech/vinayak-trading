"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { RiseOddsLatest } from "@/lib/schemas";

type Item = RiseOddsLatest["items"][string];

/** The newest rise odds of every stock in a list, in one request (the scores change once a night, so they are kept for ten minutes). A stock never scored is simply absent. */
export function useRiseOdds(ids: number[]): Record<string, Item> {
  const key = [...new Set(ids)].sort((a, b) => a - b).slice(0, 300);
  const q = useQuery({ queryKey: ["market", "rise-latest", key.join(",")], queryFn: () => api.marketRiseLatest(key), enabled: key.length > 0, staleTime: 10 * 60_000, retry: false, placeholderData: (prev) => prev });
  return q.data?.items ?? {};
}

export const RISE_HEADER = "Rise odds";
export const RISE_HELP = "The model's chance (%) that the stock closes higher in 5 sessions, from its own history, scored each night. Colour follows its rank among all stocks scored that day. A lean, not a signal: the chance sits between about 40 and 60%";

/** The own-direction chance as plain text, coloured by its rank among the stocks scored the same day (top fifth green, bottom fifth red); the title spells out both models. */
export function RiseText({ odds }: { odds: Item | undefined }) {
  if (!odds?.up && !odds?.rel) return <span className="text-ink-faint" title="Not scored (too little trading or history)">–</span>;
  const up = odds.up;
  const tone = !up ? "" : up.pct >= 80 ? "text-emerald-700" : up.pct <= 20 ? "text-red-700" : "";
  const title = [up ? `Chance of closing higher in 5 sessions: ${(up.prob * 100).toFixed(1)}% (rank ${Math.round(up.pct)} of 100)` : null, odds.rel ? `Chance of beating the median stock: ${(odds.rel.prob * 100).toFixed(1)}% (rank ${Math.round(odds.rel.pct)} of 100)` : null, `Scored ${(up ?? odds.rel)!.day}`].filter(Boolean).join(" · ");
  return (
    <span className={`whitespace-nowrap tabular-nums ${tone}`} title={title}>
      {up ? `${Math.round(up.prob * 100)}%` : "–"}
      {odds.rel ? <span className="ml-1 text-[10px] text-ink-faint">r{Math.round(odds.rel.pct)}</span> : null}
    </span>
  );
}

/** The same for a plain table row. */
export function RiseCell({ odds }: { odds: Item | undefined }) {
  return <td className="px-2 text-right"><RiseText odds={odds} /></td>;
}
