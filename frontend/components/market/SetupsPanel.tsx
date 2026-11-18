"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { PriceCell, useLiveQuotes } from "@/components/market/LivePrice";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, Tabs } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";

const LISTS = [
  { key: "top-swing-scores", label: "Highest scores" },
  { key: "money-and-trend", label: "Money and trend agree" },
  { key: "early-accumulation", label: "Smart money first" },
] as const;
type Key = (typeof LISTS)[number]["key"];
const num = (v: unknown, d = 1) => (typeof v === "number" ? v.toFixed(d) : "–");
const tone = (v: unknown) => (typeof v !== "number" ? "" : v > 0 ? "text-emerald-700" : v < 0 ? "text-red-700" : "");

/** The best-scoring liquid stocks today, three ways to cut them, each with the reasons behind its score. */
export function SetupsPanel() {
  const [key, setKey] = useState<Key>("top-swing-scores");
  const q = useQuery({ queryKey: ["screener", "setups", key], queryFn: () => api.runScreener({ preset: key, conditions: [], match: "all", limit: 8 }), staleTime: 5 * 60_000 });
  const quotes = useLiveQuotes((q.data?.rows ?? []).map((r) => Number(r.instrument_id)));
  return (
    <Panel title="Setups today">
      <div className="flex px-3 pt-1"><Tabs label="Setup lists" tabs={LISTS.map((l) => ({ key: l.key, label: l.label }))} value={key} onChange={setKey} /></div>
      {q.isError ? <div className="p-3"><Alert tone="error" title="Could not load the setups">Try again in a moment.</Alert></div> : null}
      {q.isLoading ? <div role="status" aria-label="Loading the setups" className="p-3"><Skeleton className="h-32 w-full" /></div> : null}
      {q.data && q.data.rows.length === 0 ? <p className="p-3 text-sm text-ink-soft">Nothing matches today.</p> : null}
      {q.data && q.data.rows.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-left text-sm">
            <caption className="sr-only">Stocks that match, best first</caption>
            <thead className="border-b border-line text-xs text-ink-soft"><tr><th scope="col" className="px-3 py-2">Stock</th><th scope="col" className="px-2 text-right">Price</th><th scope="col" className="px-2 text-right">Score</th><th scope="col" className="px-2 text-right">1 month</th><th scope="col" className="px-2">Setup</th><th scope="col" className="px-2">Why</th></tr></thead>
            <tbody>
              {q.data.rows.map((r) => (
                <tr key={String(r.instrument_id)} className="border-b border-line last:border-0">
                  <th scope="row" className="whitespace-nowrap px-3 py-1.5 font-medium"><Link href={`/data/instruments?id=${r.instrument_id}`} className="text-brand hover:underline">{String(r.symbol)}</Link></th>
                  <PriceCell quote={quotes[String(r.instrument_id)]} />
                  <td className="px-2 text-right font-semibold tabular-nums">{num(r.score, 0)}</td>
                  <td className={`px-2 text-right tabular-nums ${tone(r.chg_1m)}`}>{typeof r.chg_1m === "number" ? `${r.chg_1m > 0 ? "+" : ""}${r.chg_1m.toFixed(1)}%` : "–"}</td>
                  <td className="px-2 text-xs">{typeof r.setup === "string" ? r.setup : ""}</td>
                  <td className="px-2 text-xs text-ink-soft">{typeof r.score_why === "string" ? r.score_why : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="border-t border-line px-3 py-2 text-xs text-ink-faint">Liquid stocks only (₹5 crore a day or more). The score ranks each stock against the others on trend, volume and delivery, smart money and quality. It had a modest edge on past data (top fifth ahead of the bottom fifth by about 1% over four weeks, mostly from volume and delivery); it is a place to start looking, not a signal to trade on. <Link href="/screener" className="text-brand hover:underline">Open the screener</Link>.</p>
    </Panel>
  );
}
