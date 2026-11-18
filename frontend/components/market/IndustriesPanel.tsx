"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Pct } from "@/components/market/LivePrice";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";

const pct = (v: number | null) => (v === null ? "–" : `${Math.round(v)}%`);
/** A share of stocks as a background that deepens with how many are on the right side (green above 60%, red below 40%). */
const shade = (v: number | null) => (v === null ? "" : v >= 75 ? "bg-emerald-200" : v >= 60 ? "bg-emerald-100" : v <= 25 ? "bg-red-200" : v <= 40 ? "bg-red-100" : "");

/** Breadth inside each industry group of the Nifty 500: how many of its stocks are in an uptrend, and which names score best. */
export function IndustriesPanel() {
  const q = useQuery({ queryKey: ["market", "industries"], queryFn: api.marketIndustries, refetchInterval: 10 * 60_000 });
  if (q.isError) return <Alert tone="error" title="Could not load the industries">Try again in a moment.</Alert>;
  if (q.isLoading || !q.data) return <div role="status" aria-label="Loading the industries"><Skeleton className="h-40 w-full" /></div>;
  const d = q.data;
  if (d.industries.length === 0) return <Alert tone="info" title="No industry breadth yet">The sector list or the stock table has not loaded.</Alert>;
  return (
    <Panel title="Inside each industry">
      <p className="px-3 pt-2 text-xs text-ink-soft">Nifty 500 stocks grouped by NSE industry, as of {d.as_of}. A strong sector index with a weak share of stocks above their averages is one or two big names carrying it.</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <caption className="sr-only">Industry breadth, best average score first</caption>
          <thead className="border-b border-line text-xs text-ink-soft">
            <tr>
              <th scope="col" className="px-3 py-2">Industry</th>
              <th scope="col" className="px-2 text-right">Stocks</th>
              <th scope="col" className="px-2 text-right" title="Average change today of its stocks, from live prices">Today</th>
              <th scope="col" className="px-2 text-right" title="Above their 50-day average">Above 50-day</th>
              <th scope="col" className="px-2 text-right" title="Above their 200-day average">Above 200-day</th>
              <th scope="col" className="px-2 text-right">Up today</th>
              <th scope="col" className="px-2 text-right" title="Median change over a month">1 month</th>
              <th scope="col" className="px-2 text-right" title="Average swing score of its scored stocks">Avg score</th>
              <th scope="col" className="px-2">Best scored</th>
            </tr>
          </thead>
          <tbody>
            {d.industries.map((g) => (
              <tr key={g.name} className="border-b border-line last:border-0">
                <th scope="row" className="px-3 py-1.5 font-medium"><Link href={`/market/index?industry=${encodeURIComponent(g.name)}`} className="text-brand hover:underline" title="Its stocks">{g.name}</Link></th>
                <td className="px-2 text-right tabular-nums">{g.stocks}</td>
                <td className="whitespace-nowrap px-2 text-right tabular-nums" title={g.live_change === null ? "No live prices yet" : `${g.live_up} up, ${g.live_down} down`}><Pct v={g.live_change} /></td>
                <td className={`px-2 text-right tabular-nums ${shade(g.above_50)}`}>{pct(g.above_50)}</td>
                <td className={`px-2 text-right tabular-nums ${shade(g.above_200)}`}>{pct(g.above_200)}</td>
                <td className={`px-2 text-right tabular-nums ${shade(g.up_today)}`}>{pct(g.up_today)}</td>
                <td className="px-2 text-right tabular-nums">{g.median_1m === null ? "–" : `${g.median_1m > 0 ? "+" : ""}${g.median_1m.toFixed(1)}%`}</td>
                <td className="px-2 text-right tabular-nums">{g.avg_score === null ? "–" : Math.round(g.avg_score)}{g.scored > 0 && g.scored < g.stocks ? <span className="text-xs text-ink-faint"> ({g.scored})</span> : null}</td>
                <td className="px-2 text-xs text-ink-soft">{g.top.join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
