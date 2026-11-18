"use client";

import { useQuery } from "@tanstack/react-query";
import { money } from "@/components/market/LivePrice";
import { api } from "@/lib/api/client";
import type { LiveIndices } from "@/lib/schemas";

type Card = LiveIndices["indices"][number];
const NAMES: Record<string, string> = { "NIFTY 50": "Nifty 50", SENSEX: "Sensex", "INDIA VIX": "India VIX", "NIFTY BANK": "Bank Nifty", "NIFTY FIN SERVICE": "Fin Services", "NIFTY IT": "Nifty IT", "NIFTY MIDCAP 100": "Midcap 100", "NIFTY SMLCAP 100": "Smallcap 100", "NIFTY 500": "Nifty 500" };

/** Today's minute-by-minute closes as a small line, coloured by whether the day is up or down. Needs two points; nothing otherwise. */
function Spark({ points, up }: { points: number[]; up: boolean }) {
  if (points.length < 2) return null;
  const lo = Math.min(...points), hi = Math.max(...points), span = hi - lo || 1;
  const d = points.map((v, i) => `${i === 0 ? "M" : "L"}${((i / (points.length - 1)) * 100).toFixed(1)},${(24 - ((v - lo) / span) * 22 - 1).toFixed(1)}`).join(" ");
  return (
    <svg viewBox="0 0 100 24" preserveAspectRatio="none" className="mt-1 h-6 w-full" role="img" aria-label={`Today's line, ${points.length} minutes`}>
      <path d={d} fill="none" strokeWidth="1.5" vectorEffect="non-scaling-stroke" className={up ? "stroke-emerald-600" : "stroke-red-600"} />
    </svg>
  );
}

function IndexCard({ c }: { c: Card }) {
  const vix = c.symbol === "INDIA VIX"; // a rising VIX is fear: shown in the opposite colour from a rising index
  const pct = c.change_pct;
  const up = (pct ?? 0) >= 0;
  const good = vix ? !up : up;
  return (
    <div className="min-w-[10.5rem] flex-1 rounded-xl border border-line bg-panel p-3 shadow-card" title={c.source === "live" ? `Live, as of ${c.as_of}` : `Last close, ${c.as_of}`}>
      <div className="text-xs font-medium text-ink-soft">{NAMES[c.symbol] ?? c.symbol}{c.source === "daily" ? <span className="ml-1 text-[10px] text-ink-faint">close</span> : null}</div>
      <div className="mt-0.5 text-lg font-semibold tabular-nums">{money(Number(c.ltp))}</div>
      <div className="text-xs tabular-nums">
        {c.change !== null ? <span className={good ? "text-emerald-700" : "text-red-700"}>{Number(c.change) > 0 ? "+" : ""}{money(Number(c.change))} ({pct === null ? "–" : `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`})</span> : <span className="text-ink-faint">–</span>}
      </div>
      <Spark points={c.spark} up={good} />
    </div>
  );
}

/** Nifty, Sensex, India VIX and the other tracked indices, live while the feed runs and at their last close otherwise. Nothing is shown when no index has any data. */
export function IndexStrip() {
  const q = useQuery({ queryKey: ["live", "indices"], queryFn: api.liveIndices, refetchInterval: 5_000, staleTime: 2_000, retry: false });
  const d = q.data;
  if (!d || d.indices.length === 0) return null;
  return (
    <section aria-label="Market indices" className="space-y-1">
      <div className="flex gap-3 overflow-x-auto pb-1">{d.indices.map((c) => <IndexCard key={c.symbol} c={c} />)}</div>
      <p className="text-xs text-ink-faint">{d.live ? "Live from the exchange feed, refreshed every few seconds." : "The live feed is off: showing the last close."}</p>
    </section>
  );
}
