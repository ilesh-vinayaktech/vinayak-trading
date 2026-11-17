"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { ApiError, api } from "@/lib/api/client";
import type { StockLevels as Levels } from "@/lib/schemas";

const STATE_TONE: Record<string, "good" | "bad" | "warn" | "neutral" | "info"> = {
  Breakout: "good",
  "Breakout, weak volume": "warn",
  Breakdown: "bad",
  "Breakdown, weak volume": "warn",
  "Testing resistance": "info",
  "Testing support": "info",
};
const money = (n: number) => n.toLocaleString("en-IN", { maximumFractionDigits: 2 });

/** The price over the last year with its support and resistance lines, and the volume traded at each price beside it. */
function Chart({ d }: { d: Required<Pick<Levels, "series" | "supports" | "resistances" | "profile">> & Levels }) {
  const W = 560, H = 240, PW = 90; // the profile takes the right-hand strip
  const lv = [...d.supports.slice(0, 3), ...d.resistances.slice(0, 3)];
  const prices = [...d.series.map((p) => p.close), ...lv.map((l) => l.price)];
  const lo = Math.min(...prices), hi = Math.max(...prices);
  const y = (v: number) => H - ((v - lo) / (hi - lo || 1)) * (H - 8) - 4;
  const x = (i: number) => (i / Math.max(1, d.series.length - 1)) * (W - PW - 6);
  const line = d.series.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.close).toFixed(1)}`).join(" ");
  const maxShare = d.profile ? Math.max(...d.profile.bins.map((b) => b.share)) : 1;
  const [b0, b1] = d.profile?.bins ?? [];
  const bin = b0 && b1 ? Math.abs(b1.price - b0.price) : 0;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-60 w-full" role="img" aria-label={`${d.symbol} price over the last ${d.series.length} days with support, resistance and volume by price`}>
      {d.profile && <rect x={0} y={y(d.profile.value_high)} width={W - PW - 6} height={Math.max(1, y(d.profile.value_low) - y(d.profile.value_high))} className="fill-slate-400" opacity={0.1}><title>Where 70% of the volume traded</title></rect>}
      {d.supports.slice(0, 3).map((l) => <line key={`s${l.price}`} x1={0} x2={W - PW - 6} y1={y(l.price)} y2={y(l.price)} className="stroke-emerald-600" strokeDasharray="4 3" opacity={0.8}><title>{`Support ${money(l.price)}, touched ${l.touches} times`}</title></line>)}
      {d.resistances.slice(0, 3).map((l) => <line key={`r${l.price}`} x1={0} x2={W - PW - 6} y1={y(l.price)} y2={y(l.price)} className="stroke-red-600" strokeDasharray="4 3" opacity={0.8}><title>{`Resistance ${money(l.price)}, touched ${l.touches} times`}</title></line>)}
      <path d={line} fill="none" stroke="currentColor" strokeWidth={1.5} className="text-ink" vectorEffect="non-scaling-stroke" />
      {d.profile?.bins.map((b) => <rect key={b.price} x={W - PW} y={y(b.price + bin / 2)} width={Math.max(1, (b.share / maxShare) * PW)} height={Math.max(1, y(b.price - bin / 2) - y(b.price + bin / 2) - 1)} className={Math.abs(b.price - (d.profile?.poc ?? 0)) < bin / 2 ? "fill-brand" : "fill-slate-300"}><title>{`${money(b.price)}: ${(b.share * 100).toFixed(1)}% of the volume`}</title></rect>)}
    </svg>
  );
}

function Histogram({ r }: { r: NonNullable<Levels["returns"]> }) {
  const max = Math.max(...r.bins.map((b) => b.count), 1);
  return (
    <div role="img" aria-label="Distribution of daily returns over the last year" className="flex h-20 items-end gap-0.5">
      {r.bins.map((b) => {
        const mid = (b.low + b.high) / 2;
        return <div key={b.low} className={`flex-1 ${mid >= 0 ? "bg-emerald-400" : "bg-red-400"}`} style={{ height: `${(b.count / max) * 100}%` }} title={`${b.low.toFixed(1)}% to ${b.high.toFixed(1)}%: ${b.count} days`} />;
      })}
    </div>
  );
}

const LevelRows = ({ rows, kind }: { rows: Levels["supports"]; kind: string }) => (
  <ul className="space-y-1 text-sm">
    {(rows ?? []).slice(0, 3).map((l) => (
      <li key={l.price} className="flex justify-between gap-3"><span className="tabular-nums">{money(l.price)}</span><span className="text-xs text-ink-soft">{l.distance_pct > 0 ? "+" : ""}{l.distance_pct.toFixed(1)}%, touched {l.touches}×</span></li>
    ))}
    {(rows ?? []).length === 0 && <li className="text-xs text-ink-faint">No {kind} in range</li>}
  </ul>
);

/** Support, resistance, breakout status and the two histograms for one stock. */
export function LevelsPanel({ symbol }: { symbol: string }) {
  const q = useQuery({
    queryKey: ["market", "levels", symbol],
    queryFn: () => api.marketLevels(symbol),
    retry: false,
  });
  if (q.isLoading) return <div role="status" aria-label="Loading the levels"><Skeleton className="h-40 w-full" /></div>;
  if (q.isError) return q.error instanceof ApiError && q.error.status === 404 ? null : <Alert tone="error" title="Could not load the levels">Try again in a moment.</Alert>;
  const d = q.data;
  if (!d) return null;
  if (!d.enough_history || !d.series || !d.supports || !d.resistances || !d.status) return <Alert tone="info" title="Not enough history for levels">{d.symbol} has too few bars since its last split or bonus.</Alert>;
  const st = d.status;
  return (
    <Panel title="Support, resistance and volume by price">
      <div className="flex flex-wrap items-center gap-3 px-3 pt-2 text-sm">
        <StatusPill tone={STATE_TONE[st.state] ?? "neutral"}>{st.state}</StatusPill>
        {st.level !== null && <span className="text-ink-soft">level {money(st.level)}</span>}
        {st.volume_ratio !== null && <span className="text-ink-soft">volume {st.volume_ratio.toFixed(1)}× its norm</span>}
        {st.delivery_vs_avg !== null && <span className="text-ink-soft">delivery {st.delivery_vs_avg.toFixed(1)}× its norm</span>}
        <span className="text-xs text-ink-faint">as of {d.as_of}</span>
      </div>
      <div className="p-3"><Chart d={{ ...d, series: d.series, supports: d.supports, resistances: d.resistances, profile: d.profile ?? null }} /></div>
      <div className="grid gap-4 px-3 pb-3 sm:grid-cols-3">
        <div><h3 className="mb-1 text-xs font-semibold text-ink-soft">Resistance above</h3><LevelRows rows={d.resistances} kind="resistance" /></div>
        <div><h3 className="mb-1 text-xs font-semibold text-ink-soft">Support below</h3><LevelRows rows={d.supports} kind="support" /></div>
        <div>
          <h3 className="mb-1 text-xs font-semibold text-ink-soft">Daily returns, last year</h3>
          {d.returns ? <><Histogram r={d.returns} /><p className="mt-1 text-xs text-ink-soft">Last move {d.returns.last.toFixed(1)}%, bigger than {Math.round(d.returns.last_percentile)}% of days. Range {d.returns.worst.toFixed(1)}% to +{d.returns.best.toFixed(1)}%.</p></> : <p className="text-xs text-ink-faint">Not enough days</p>}
        </div>
      </div>
      <p className="border-t border-line px-3 py-2 text-xs text-ink-faint">Levels are swing highs and lows within 1.5% of each other (a broken resistance becomes support); a swing is only known 5 days after it. The bars on the right are the volume traded at each price over the last 120 days; the filled one is where most traded{d.profile ? ` (${money(d.profile.poc)})` : ""}. A breakout is a close more than 0.5% beyond the nearest level; it is confirmed on volume at 1.5× its norm and, where known, delivery at 1.2×.</p>
    </Panel>
  );
}
