"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";

const QUADRANT_TONE = { Leading: "good", Improving: "info", Weakening: "warn", Lagging: "bad" } as const;
const QUADRANT_HINT: Record<string, string> = {
  Leading: "ahead of the market and holding",
  Improving: "behind, but turning up",
  Weakening: "ahead, but fading",
  Lagging: "behind and not improving",
};

/** A return as a percentage with a background that deepens with its size (green up, red down). */
function Heat({ v }: { v: number | null }) {
  if (v === null) return <td className="px-2 py-1.5 text-right text-ink-faint">–</td>;
  const pct = v * 100;
  const a = Math.abs(pct);
  const cls = a < 0.5 ? "" : pct > 0 ? (a < 2 ? "bg-emerald-50" : a < 6 ? "bg-emerald-100" : "bg-emerald-200") : a < 2 ? "bg-red-50" : a < 6 ? "bg-red-100" : "bg-red-200";
  return <td className={`px-2 py-1.5 text-right tabular-nums ${cls}`}>{pct > 0 ? "+" : ""}{pct.toFixed(1)}%</td>;
}

function Trend({ above50, above200 }: { above50: boolean; above200: boolean }) {
  const label = above50 && above200 ? "Above its 50 and 200-day averages" : above200 ? "Above its 200-day average, below its 50-day" : above50 ? "Above its 50-day average, below its 200-day" : "Below both averages";
  const dot = (on: boolean) => <span className={`inline-block h-2 w-2 rounded-full ${on ? "bg-emerald-500" : "bg-slate-300"}`} />;
  return <span role="img" aria-label={label} title={label} className="inline-flex items-center gap-1">{dot(above50)}{dot(above200)}</span>;
}

/** Where money is flowing: every sector index against the Nifty 500, strongest first. */
export function SectorPanel() {
  const q = useQuery({ queryKey: ["market", "sectors"], queryFn: api.marketSectors, refetchInterval: 5 * 60_000 });
  if (q.isError) return <Alert tone="error" title="Could not load the sectors">Try again in a moment.</Alert>;
  if (q.isLoading || !q.data) return <div role="status" aria-label="Loading the sectors"><Skeleton className="h-48 w-full" /></div>;
  const d = q.data;
  if (d.sectors.length === 0) return <Alert tone="info" title="No sector data yet">The sector indices have not loaded.</Alert>;
  return (
    <Panel title="Sector rotation">
      <p className="px-3 pt-2 text-xs text-ink-soft">Against the {d.benchmark}, as of {d.as_of}.</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <caption className="sr-only">Sector rotation, strongest first</caption>
          <thead className="border-b border-line text-xs text-ink-soft">
            <tr>
              <th scope="col" className="px-3 py-2">Sector</th>
              <th scope="col" className="px-2 text-right">Score</th>
              <th scope="col" className="px-2 text-right">1 day</th>
              <th scope="col" className="px-2 text-right">1 month</th>
              <th scope="col" className="px-2 text-right">3 months</th>
              <th scope="col" className="px-2 text-right">1 year</th>
              <th scope="col" className="px-2 text-right" title="Relative strength against the benchmark, 100 is its recent norm">Strength</th>
              <th scope="col" className="px-2">Rotation</th>
              <th scope="col" className="px-2" title="Above its 50-day and 200-day average">Trend</th>
            </tr>
          </thead>
          <tbody>
            {d.sectors.map((s) => (
              <tr key={s.name} className="border-b border-line last:border-0">
                <th scope="row" className="whitespace-nowrap px-3 py-1.5 font-medium">{s.name}</th>
                <td className="px-2 text-right tabular-nums">
                  <span className="inline-flex items-center justify-end gap-2"><span className="h-1.5 w-12 rounded-full bg-slate-100"><span className={`block h-1.5 rounded-full ${s.score >= 60 ? "bg-emerald-500" : s.score >= 40 ? "bg-slate-400" : "bg-red-500"}`} style={{ width: `${s.score}%` }} /></span>{Math.round(s.score)}</span>
                </td>
                <Heat v={s.ret_1d} />
                <Heat v={s.ret_21d} />
                <Heat v={s.ret_63d} />
                <Heat v={s.ret_252d} />
                <td className="px-2 text-right tabular-nums">{s.rs_ratio.toFixed(1)}</td>
                <td className="px-2"><span title={QUADRANT_HINT[s.quadrant]}><StatusPill tone={QUADRANT_TONE[s.quadrant as keyof typeof QUADRANT_TONE] ?? "neutral"}>{s.quadrant}</StatusPill></span></td>
                <td className="px-2"><Trend above50={s.above_50} above200={s.above_200} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-line px-3 py-2 text-xs text-ink-faint">Strength is the sector against the {d.benchmark} compared with its own 50-day norm; the rotation says whether that is improving. Leading: ahead and holding. Improving: behind but turning up. Weakening: ahead but fading. Lagging: behind and not improving.</p>
    </Panel>
  );
}
