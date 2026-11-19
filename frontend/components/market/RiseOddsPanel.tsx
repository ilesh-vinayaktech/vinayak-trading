"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { PriceCell, money, useLiveQuotes } from "@/components/market/LivePrice";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, Tabs } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";

/** The stocks the model rates most likely to beat the median stock over the next 5 sessions, on the newest day scored, with the honest numbers behind that rating. */
export function RiseOddsPanel() {
  const [kind, setKind] = useState<"rel" | "up">("rel");
  const [side, setSide] = useState<"top" | "bottom">("top");
  const q = useQuery({ queryKey: ["market", "rise-odds-top", kind, side], queryFn: () => api.marketRiseTop(15, side, kind), staleTime: 5 * 60_000 });
  const d = q.data;
  const quotes = useLiveQuotes(d?.items.map((r) => r.instrument_id) ?? []);
  return (
    <Panel title="Rise odds: the model's calls">
      <div className="flex flex-wrap gap-x-6 px-3 pt-1">
        <Tabs label="Rise odds kind" tabs={[{ key: "rel", label: "Against other stocks" }, { key: "up", label: "Own direction" }]} value={kind} onChange={setKind} />
        <Tabs label="Rise odds side" tabs={kind === "rel" ? [{ key: "top", label: "Most likely to rise" }, { key: "bottom", label: "Most likely to lag" }] : [{ key: "top", label: "Most likely to go up" }, { key: "bottom", label: "Most likely to go down" }]} value={side} onChange={setSide} />
      </div>
      {q.isError ? <div className="p-3"><Alert tone="error" title="Could not load the rise odds">Try again in a moment.</Alert></div> : null}
      {q.isLoading ? <div role="status" aria-label="Loading the rise odds" className="p-3"><Skeleton className="h-32 w-full" /></div> : null}
      {d && d.items.length === 0 ? <p className="p-3 text-sm text-ink-soft">No stock has been scored yet. The scores are made each night once the day&apos;s prices are in.</p> : null}
      {d && d.items.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-left text-sm">
            <caption className="sr-only">{kind === "rel" ? (side === "top" ? "Stocks most likely to beat the median stock over the next 5 sessions, highest first" : "Stocks most likely to lag the median stock over the next 5 sessions, lowest first") : side === "top" ? "Stocks the model gives the best chance of closing higher in 5 sessions, highest first" : "Stocks the model gives the worst chance of closing higher in 5 sessions, lowest first"}</caption>
            <thead className="border-b border-line text-xs text-ink-soft"><tr><th scope="col" className="px-3 py-2">Stock</th><th scope="col" className="px-2">Name</th><th scope="col" className="px-2 text-right">Price, today</th><th scope="col" className="px-2 text-right">Previous day</th><th scope="col" className="px-2 text-right">{kind === "rel" ? "Chance to beat the median" : "Chance of closing higher"}</th><th scope="col" className="px-2 text-right">Rank</th></tr></thead>
            <tbody>
              {d.items.map((r) => (
                <tr key={r.instrument_id} className="border-b border-line last:border-0">
                  <th scope="row" className="whitespace-nowrap px-3 py-1.5 font-medium"><Link href={`/data/instruments?id=${r.instrument_id}`} className="text-brand hover:underline">{r.symbol}</Link></th>
                  <td className="max-w-56 truncate px-2 text-xs text-ink-soft">{r.name ?? ""}</td>
                  <PriceCell quote={quotes[String(r.instrument_id)]} />
                  <td className="px-2 text-right tabular-nums text-ink-soft">{quotes[String(r.instrument_id)]?.prev_close ? money(Number(quotes[String(r.instrument_id)]!.prev_close)) : "–"}</td>
                  <td className="px-2 text-right font-semibold tabular-nums">{Math.round(r.prob * 100)}%</td>
                  <td className="px-2 text-right tabular-nums text-ink-soft">{Math.round(r.pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="border-t border-line px-3 py-2 text-xs text-ink-faint">
        As of {d?.day ?? "–"}. {kind === "rel"
          ? "Against other stocks: a model learned from seven years of prices, volume and delivery which stocks tend to beat, or lag, the median stock over the next 5 sessions. Judged on 2024 to 2026, with each year scored by a model that had not seen it: the top 1% beat the median stock 57.1% of the time, while the bottom 1% lagged it 64.6% of the time (68% in the bottom 0.1%), averaging 1.3% below it. The lagging call is the sharper one."
          : "Own direction: the model's chance that the stock itself closes higher 5 sessions on, from its own recent moves, volume and delivery alone (no market state, which only taught it to guess the market). Judged on 2024 to 2026: when it gave 65% or more the stock rose 64.3% of the time (averaging +2.5%); under 40%, only 42 to 43% rose. Its chance runs a few points high on those years, a weaker market than the ones it learned from."}{" "}
        These are hit rates near 57 to 65%, not 70 to 80%, before costs: a place to start looking, or to stop looking, not a signal to trade on.
      </p>
    </Panel>
  );
}
