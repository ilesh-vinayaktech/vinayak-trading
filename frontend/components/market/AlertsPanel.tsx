"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Alert } from "@/components/ui/Alert";
import { ApiError, api } from "@/lib/api/client";

/** What needs a look today, worked out from data the page already loads: a holding or watched stock that broke a level (confirmed or not) and a change of the market trend since the last reading. Shows nothing when there is nothing. */
export function AlertsPanel() {
  const summary = useQuery({ queryKey: ["paper", "summary", "paper"], queryFn: () => api.paperSummary("paper"), retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 1 });
  const zone = useQuery({ queryKey: ["market", "zone"], queryFn: api.marketZone });
  const watch = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist });
  const held = (summary.data?.positions ?? []).map((p) => ({ symbol: p.symbol, instrument_id: p.instrument_id }));
  const positions = [...held, ...(watch.data?.items ?? []).filter((w) => !held.some((h) => h.symbol === w.symbol)).map((w) => ({ symbol: w.symbol, instrument_id: w.instrument_id }))];
  const lv = useQueries({ queries: positions.map((p) => ({ queryKey: ["market", "levels", p.symbol], queryFn: () => api.marketLevels(p.symbol), retry: false, staleTime: 10 * 60_000 })) });
  const items: { key: string; id?: number; tone: "warn" | "error" | "info"; title: string; text: string }[] = [];
  positions.forEach((p, i) => {
    const st = lv[i]?.data?.status?.state;
    if (st?.startsWith("Breakdown")) items.push({ key: p.symbol, id: p.instrument_id, tone: "error", title: `${p.symbol}: ${st.toLowerCase()}`, text: "Closed below support." });
    else if (st?.startsWith("Breakout")) items.push({ key: p.symbol, id: p.instrument_id, tone: "info", title: `${p.symbol}: ${st.toLowerCase()}`, text: "Closed above resistance." });
  });
  const h = zone.data?.history ?? [];
  const [prev, last] = [h[h.length - 2], h[h.length - 1]];
  if (prev && last && prev.trend !== last.trend) items.push({ key: "trend", tone: "warn", title: `Market trend changed to ${last.trend}`, text: `It was ${prev.trend} on ${prev.day}.` });
  if (items.length === 0) return null;
  return (
    <section aria-label="Alerts" className="space-y-2">
      {items.map((a) => (
        <Alert key={a.key} tone={a.tone} title={a.title}>{a.text} {a.id ? <Link href={`/data/instruments?id=${a.id}`} className="font-medium underline">Open</Link> : null}</Alert>
      ))}
    </section>
  );
}
