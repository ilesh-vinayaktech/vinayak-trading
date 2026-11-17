"use client";

import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import type { StockScore } from "@/lib/schemas";

const PARTS = [
  { key: "trend", label: "Trend", weight: 35, hint: "1 and 3-month change, price against its 50-day average, nearness to the 52-week high, ADX" },
  { key: "participation", label: "Volume and delivery", weight: 20, hint: "Volume and delivery % against their norms" },
  { key: "smart_money", label: "Smart money", weight: 30, hint: "Bulk and block deals, insider buying, change in FII, DII and promoter holding" },
  { key: "quality", label: "Quality", weight: 15, hint: "ROE, ROCE, profit growth, low debt" },
] as const;
const colour = (n: number) => (n >= 60 ? "bg-emerald-500" : n >= 40 ? "bg-slate-400" : "bg-red-500");

function History({ points }: { points: StockScore["history"] }) {
  if (points.length < 2) return null;
  const W = 520, H = 60;
  const x = (i: number) => (i / (points.length - 1)) * W;
  const y = (v: number) => H - (v / 100) * H;
  const line = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.score).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-16 w-full" role="img" aria-label={`Score over the last ${points.length} readings, from ${points[0]?.day ?? ""}`} preserveAspectRatio="none">
      <line x1={0} x2={W} y1={y(50)} y2={y(50)} className="stroke-slate-300" strokeDasharray="3 3" />
      <path d={line} fill="none" stroke="currentColor" strokeWidth={1.6} className="text-ink" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** One stock's swing score: the number, its four parts, why, and how it has moved. Nothing is shown for a stock that is not a listed share. */
export function ScorePanel({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ["market", "score", symbol], queryFn: () => api.marketScore(symbol), retry: false });
  if (q.isLoading) return <div role="status" aria-label="Loading the score"><Skeleton className="h-24 w-full" /></div>;
  if (q.isError) return null; // not a listed share (404) or not available: show nothing rather than an error on a page about something else
  const d = q.data;
  if (!d) return null;
  return (
    <Panel title="Swing score">
      {!d.scored || d.score === null ? (
        <p className="p-3 text-sm text-ink-soft">{d.symbol} has no score today: it trades under ₹5 crore a day, or too little is known about it. A thinly traded stock is left unscored rather than ranked.</p>
      ) : (
        <div className="grid gap-4 p-3 md:grid-cols-[10rem_1fr]">
          <div>
            <div className="text-4xl font-semibold tabular-nums" aria-label={`Score ${Math.round(d.score)} out of 100`}>{Math.round(d.score)}<span className="text-base font-normal text-ink-soft"> / 100</span></div>
            {d.setup ? <p className="mt-1 text-sm font-medium">{d.setup}</p> : null}
            {d.why ? <p className="mt-1 text-xs text-ink-soft">{d.why}</p> : null}
            <p className="mt-1 text-xs text-ink-faint">as of {d.as_of}</p>
          </div>
          <div>
            <ul className="space-y-2">
              {PARTS.map((p) => {
                const v = d.components[p.key];
                return (
                  <li key={p.key} title={p.hint}>
                    <div className="flex justify-between text-xs"><span>{p.label} <span className="text-ink-faint">({p.weight}%)</span></span><span className="tabular-nums">{v === null ? "no data" : Math.round(v)}</span></div>
                    <div className="mt-0.5 h-1.5 rounded-full bg-slate-100" aria-hidden>{v !== null ? <div className={`h-1.5 rounded-full ${colour(v)}`} style={{ width: `${v}%` }} /> : null}</div>
                  </li>
                );
              })}
            </ul>
            <History points={d.history} />
          </div>
        </div>
      )}
      <p className="border-t border-line px-3 py-2 text-xs text-ink-faint">Each part ranks this stock against every liquid stock; 50 is the middle. A part with no data is left out and the others are re-weighted, never counted as zero. On past data the score had a modest edge (top fifth ahead of the bottom fifth by about 1% over four weeks), mostly from volume and delivery; smart money has not yet earned its weight.</p>
    </Panel>
  );
}
