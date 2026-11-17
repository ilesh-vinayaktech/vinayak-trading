"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import type { Forecast } from "@/lib/schemas";

const LEAN = 0.03; // within 3 points of 50% there is no lean worth stating
const pct = (p: number) => `${Math.round(p * 100)}%`;
const lean = (p: number) => (p >= 0.5 + LEAN ? "Leans up" : p <= 0.5 - LEAN ? "Leans down" : "No clear lean");
const tone = (p: number) => (p >= 0.5 + LEAN ? "good" : p <= 0.5 - LEAN ? "bad" : "neutral");
const WHEN: Record<number, string> = { 1: "Tomorrow", 5: "Next 5 days" };

function why(ev: Forecast["market"][number]["evidence"], labels: Record<string, string>) {
  return ev.map((e) => `${labels[e.feature] ?? e.feature} ${e.effect >= 0 ? "supports up" : "supports down"}`).join("; ");
}

/** Tomorrow and next week for the market and each sector, with the evidence, and, always shown next to it, how the model has done against plain guessing. */
export function ForecastPanel() {
  const q = useQuery({ queryKey: ["market", "forecast"], queryFn: api.marketForecast, refetchInterval: 10 * 60_000 });
  if (q.isError) return <Alert tone="error" title="Could not load the forecast">Try again in a moment.</Alert>;
  if (q.isLoading || !q.data) return <div role="status" aria-label="Loading the forecast"><Skeleton className="h-40 w-full" /></div>;
  const d = q.data;
  if (!d.as_of) return <Alert tone="info" title="No forecast yet">The nightly job has not made one.</Alert>;
  const labels = d.labels ?? {};
  const walk = d.record.filter((r) => !r.live);
  const live = d.record.filter((r) => r.live);
  const beats = d.record.some((r) => r.beats_guessing);
  return (
    <Panel title="Outlook">
      <p className="px-3 pt-2 text-xs text-ink-soft">The chance the Nifty 500 and each sector close higher, made after the close of {d.as_of}. A statistical estimate from the zone, the index trend and sector rotation, not advice.</p>
      {!beats && walk.length > 0 && (
        <div className="px-3 pt-2">
          <Alert tone="warn" title="This forecast has not beaten plain guessing">
            {walk.map((r) => `${WHEN[r.horizon_days] ?? `${r.horizon_days} days`}: right ${pct(r.hit_rate)} of ${r.n} days, always saying ${r.base_rate >= 0.5 ? "up" : "down"} would be right ${pct(r.base_hit)}`).join(". ")}. Treat the numbers below as a reading of the evidence, not an edge.
          </Alert>
        </div>
      )}
      <div className="grid gap-3 p-3 sm:grid-cols-2">
        {d.market.map((m) => (
          <div key={m.horizon_days} className="rounded border border-line p-3">
            <div className="flex items-center justify-between text-sm"><span className="font-medium">{WHEN[m.horizon_days] ?? `${m.horizon_days} days`}</span><StatusPill tone={tone(m.p_up)}>{lean(m.p_up)}</StatusPill></div>
            <div className="mt-1 text-2xl font-semibold tabular-nums" aria-label={`${pct(m.p_up)} chance up`}>{pct(m.p_up)} <span className="text-sm font-normal text-ink-soft">chance up</span></div>
            <div className="mt-2 h-1.5 rounded-full bg-slate-100" aria-hidden><div className={`h-1.5 rounded-full ${m.p_up >= 0.5 ? "bg-emerald-500" : "bg-red-500"}`} style={{ width: `${m.p_up * 100}%` }} /></div>
            {m.evidence.length > 0 && <p className="mt-2 text-xs text-ink-soft">{why(m.evidence, labels)}</p>}
          </div>
        ))}
      </div>
      {d.sectors.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-sm">
            <caption className="sr-only">Chance each sector closes higher, most bullish first</caption>
            <thead className="border-y border-line text-xs text-ink-soft"><tr><th scope="col" className="px-3 py-2">Sector</th><th scope="col" className="px-2 text-right">Tomorrow</th><th scope="col" className="px-2 text-right">Next 5 days</th><th scope="col" className="px-2">Main reason</th></tr></thead>
            <tbody>
              {d.sectors.map((s) => (
                <tr key={s.name} className="border-b border-line last:border-0">
                  <th scope="row" className="whitespace-nowrap px-3 py-1.5 font-medium">{s.name}</th>
                  <td className="px-2 text-right tabular-nums">{s.p_1d === null ? "–" : pct(s.p_1d)}</td>
                  <td className="px-2 text-right tabular-nums">{s.p_5d === null ? "–" : pct(s.p_5d)}</td>
                  <td className="px-2 text-xs text-ink-soft">{why(s.evidence.slice(0, 1), labels)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <details className="border-t border-line px-3 py-2 text-xs text-ink-soft">
        <summary className="cursor-pointer font-medium">How it has done, and its biggest misses</summary>
        <ul className="mt-2 space-y-1">
          {[...walk, ...live].map((r) => (
            <li key={`${r.horizon_days}-${r.live}`}>{WHEN[r.horizon_days] ?? `${r.horizon_days} days`}, {r.live ? "live" : "tested on past days it had not seen"}: right {pct(r.hit_rate)} of {r.n} days; always saying {r.base_rate >= 0.5 ? "up" : "down"} {pct(r.base_hit)}; probability score {r.brier_skill >= 0 ? "better" : "worse"} than guessing by {(Math.abs(r.brier_skill) * 100).toFixed(1)}%.</li>
          ))}
        </ul>
        {d.misses.length > 0 && (
          <>
            <p className="mt-2 font-medium">Most confident wrong calls (market, 1 day)</p>
            <ul className="mt-1 space-y-1">
              {d.misses.map((m) => <li key={m.as_of}>{m.as_of}: said {pct(m.p_up)} up, the market {m.went_up ? "rose" : "fell"} {(Math.abs(m.realized) * 100).toFixed(1)}%.</li>)}
            </ul>
          </>
        )}
        <p className="mt-2">The model is refitted as every outcome becomes known and never scored on days it was trained on.</p>
      </details>
    </Panel>
  );
}
