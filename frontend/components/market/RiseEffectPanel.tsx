"use client";

import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import type { RiseEffect, RiseOdds } from "@/lib/schemas";

const KINDS = [
  { kind: "up", title: "Own direction", color: "#2563eb", ask: "closes higher in 5 sessions" },
  { kind: "rel", title: "Against other stocks", color: "#f59e0b", ask: "beats the median stock over 5 sessions" },
] as const;
const SHOWN = 120; // sessions in the small chart
const W = 600;
const H = 90;

const signed = (v: number | null) => (v === null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(2)}%`);

/** The two score lines of the last SHOWN scored days on one small chart, a dashed 50% line. The axis follows the data (the chance sits near 50%). */
function History({ data }: { data: (RiseOdds | undefined)[] }) {
  const lines = KINDS.map((k, i) => ({ ...k, pts: (data[i]?.history ?? []).slice(-SHOWN) })).filter((l) => l.pts.length > 1);
  if (lines.length === 0) return null;
  const all = lines.flatMap((l) => l.pts.map((p) => p.prob * 100));
  const lo = Math.min(45, ...all) - 1;
  const hi = Math.max(55, ...all) + 1;
  const y = (v: number) => H - ((v - lo) / (hi - lo)) * H;
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="h-24 w-full" role="img" aria-label="The rise odds of the last 120 scored days">
        <line x1="0" x2={W} y1={y(50)} y2={y(50)} stroke="#cbd5e1" strokeDasharray="4 4" />
        {lines.map((l) => (
          <polyline key={l.kind} fill="none" stroke={l.color} strokeWidth="2" points={l.pts.map((p, i) => `${(i / (l.pts.length - 1)) * W},${y(p.prob * 100)}`).join(" ")} />
        ))}
      </svg>
      <figcaption className="flex flex-wrap gap-x-4 text-xs text-ink-soft">
        {lines.map((l) => <span key={l.kind}><span style={{ color: l.color }}>●</span> {l.title}: {Math.round(l.pts[l.pts.length - 1]!.prob * 100)}% on {l.pts[l.pts.length - 1]!.day}</span>)}
        <span>axis {lo.toFixed(0)}% to {hi.toFixed(0)}%, dashed line 50%</span>
      </figcaption>
    </figure>
  );
}

function Effect({ title, ask, e }: { title: string; ask: string; e: RiseEffect["up"] }) {
  return (
    <div>
      <h3 className="text-xs font-semibold text-ink-soft">{title}: what the stock did in the 5 sessions after each day</h3>
      {!e.enough ? (
        <p className="mt-1 text-sm text-ink-soft">Only {e.days} scored days have a full 5 sessions after them: too few to say anything.</p>
      ) : (
        <>
          <table className="mt-1 w-full text-left text-sm">
            <caption className="sr-only">{title}: the stock&apos;s next 5 sessions by how high the chance was that it {ask}</caption>
            <thead className="border-b border-line text-xs text-ink-soft"><tr><th scope="col" className="py-1">The chance was in its</th><th scope="col" className="px-2 text-right">Range</th><th scope="col" className="px-2 text-right">Days</th><th scope="col" className="px-2 text-right">Average next 5 sessions</th><th scope="col" className="px-2 text-right">Rose</th></tr></thead>
            <tbody>
              {e.bands.map((b) => (
                <tr key={b.band} className="border-b border-line">
                  <th scope="row" className="py-1 font-medium">{b.band}</th>
                  <td className="px-2 text-right tabular-nums text-ink-soft">{(b.from * 100).toFixed(1)}–{(b.to * 100).toFixed(1)}%</td>
                  <td className="px-2 text-right tabular-nums">{b.n}</td>
                  <td className={`px-2 text-right tabular-nums ${b.mean === null ? "" : b.mean > 0 ? "text-emerald-700" : b.mean < 0 ? "text-red-700" : ""}`}>{signed(b.mean)}</td>
                  <td className="px-2 text-right tabular-nums">{b.up_share === null ? "–" : `${b.up_share.toFixed(0)}%`}</td>
                </tr>
              ))}
              <tr>
                <th scope="row" className="py-1 font-medium text-ink-soft">All days</th>
                <td />
                <td className="px-2 text-right tabular-nums text-ink-soft">{e.all.n}</td>
                <td className="px-2 text-right tabular-nums text-ink-soft">{signed(e.all.mean)}</td>
                <td className="px-2 text-right tabular-nums text-ink-soft">{e.all.up_share === null ? "–" : `${e.all.up_share.toFixed(0)}%`}</td>
              </tr>
            </tbody>
          </table>
          <p className="mt-1 text-xs text-ink-faint">Rank correlation between the chance and the next 5 sessions&apos; move: {e.rank_correlation === null ? "–" : e.rank_correlation.toFixed(2)} (0 means no link, 1 a perfect one).</p>
        </>
      )}
    </div>
  );
}

/** One stock's rise odds over time and what its price did after high and low days. A description of this stock's own past, not a forecast: it has a few hundred scored days at most, and overlapping 5-session windows count the same move several times. */
export function RiseEffectPanel({ symbol }: { symbol: string }) {
  const own = useQuery({ queryKey: ["market", "rise-odds", symbol, "up"], queryFn: () => api.marketRiseOdds(symbol, "up"), retry: false, staleTime: 10 * 60_000 });
  const rel = useQuery({ queryKey: ["market", "rise-odds", symbol, "rel"], queryFn: () => api.marketRiseOdds(symbol, "rel"), retry: false, staleTime: 10 * 60_000 });
  const effect = useQuery({ queryKey: ["market", "rise-effect", symbol], queryFn: () => api.marketRiseEffect(symbol), retry: false, staleTime: 10 * 60_000 });
  if (own.isLoading || rel.isLoading || effect.isLoading) return <div role="status" aria-label="Loading the rise odds"><Skeleton className="h-24 w-full" /></div>;
  if (effect.isError || (!own.data?.scored && !rel.data?.scored)) return null; // not a listed share, or never scored: nothing to say on a page about something else
  return (
    <Panel title="Rise odds over time, and the price after them">
      <div className="space-y-4 p-3">
        <History data={[own.data, rel.data]} />
        {effect.data ? KINDS.map((k) => <Effect key={k.kind} title={k.title} ask={k.ask} e={effect.data[k.kind]} />) : null}
      </div>
      <p className="border-t border-line px-3 py-2 text-xs text-ink-faint">The chance is a model&apos;s estimate, scored each night, and sits between about 40 and 60% (the rank, 0 to 100, is how it stands among all stocks that day). Each past day was scored by a model that had not seen that year. The table is only this stock&apos;s own history: a few hundred days, with neighbouring days overlapping, so a gap between the bands can be luck. Across all stocks the edge is a few tenths of a percent: a lean, not a signal.</p>
    </Panel>
  );
}
