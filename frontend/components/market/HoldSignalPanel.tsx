"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Alert } from "@/components/ui/Alert";
import { money } from "@/components/market/LivePrice";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";

/** The day's recommendation from the frozen hold rule: what to buy at the next open (best chance first, at most as many as the rule's position limit), what to sell, and how many the rule holds. The rule's own calls, long only: never an order. */
export function HoldSignalPanel() {
  const q = useQuery({ queryKey: ["market", "hold-today"], queryFn: () => api.marketHoldToday(20), staleTime: 5 * 60_000 });
  const d = q.data;
  const slots = d?.max_positions ?? 10;
  const buys = d?.buy.slice(0, slots) ?? [];
  const moreBuys = d ? Math.max(0, d.counts.buy - buys.length) : 0;
  return (
    <Panel title="Hold signal: today's recommendation">
      {q.isError ? <div className="p-3"><Alert tone="error" title="Could not load the hold signal">Try again in a moment.</Alert></div> : null}
      {q.isLoading ? <div role="status" aria-label="Loading the hold signal" className="p-3"><Skeleton className="h-32 w-full" /></div> : null}
      {d && d.day === null ? <p className="p-3 text-sm text-ink-soft">No stock has been scored yet. The signal is made each night once the day&apos;s prices are in.</p> : null}
      {d && d.day !== null ? (
        <>
          <p className="px-3 pt-2 text-sm" data-testid="hold-summary">
            As of <strong>{d.day}</strong>: <strong>{d.counts.buy}</strong> to buy at the next open, <strong>{d.counts.sell}</strong> to sell, <strong>{d.counts.in_position}</strong> held by the rule, out of {d.scored} stocks ranked.
          </p>
          <div className="grid gap-4 p-3 md:grid-cols-2">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[300px] text-left text-sm">
                <caption className="pb-1 text-left text-xs font-medium text-ink-soft">Buy at the next open, best chance first{moreBuys > 0 ? ` (${buys.length} of ${d.counts.buy} shown: the rule holds at most ${slots} at a time)` : ""}</caption>
                <thead className="border-b border-line text-xs text-ink-soft"><tr><th scope="col" className="py-1.5 pr-2">Stock</th><th scope="col" className="px-2 text-right">Last close</th><th scope="col" className="px-2 text-right">Rank</th><th scope="col" className="px-2 text-right">Chance</th></tr></thead>
                <tbody>
                  {buys.length === 0 ? <tr><td colSpan={4} className="py-2 text-xs text-ink-soft">Nothing to buy today.</td></tr> : null}
                  {buys.map((r) => (
                    <tr key={r.instrument_id} className="border-b border-line last:border-0">
                      <th scope="row" className="whitespace-nowrap py-1.5 pr-2 font-medium"><Link href={`/data/instruments?id=${r.instrument_id}`} className="text-brand hover:underline">{r.symbol}</Link></th>
                      <td className="px-2 text-right tabular-nums">{r.close !== null ? money(r.close) : "–"}</td>
                      <td className="px-2 text-right tabular-nums text-emerald-700">{Math.round(r.rank_pct)}</td>
                      <td className="px-2 text-right tabular-nums text-ink-soft">{(r.prob * 100).toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[300px] text-left text-sm">
                <caption className="pb-1 text-left text-xs font-medium text-ink-soft">Sell at the next open (held and ranked {d.sell_at} or lower), weakest first</caption>
                <thead className="border-b border-line text-xs text-ink-soft"><tr><th scope="col" className="py-1.5 pr-2">Stock</th><th scope="col" className="px-2 text-right">Held since</th><th scope="col" className="px-2 text-right">Last close</th><th scope="col" className="px-2 text-right">Rank</th></tr></thead>
                <tbody>
                  {d.sell.length === 0 ? <tr><td colSpan={4} className="py-2 text-xs text-ink-soft">Nothing to sell today.</td></tr> : null}
                  {d.sell.map((r) => (
                    <tr key={r.instrument_id} className="border-b border-line last:border-0">
                      <th scope="row" className="whitespace-nowrap py-1.5 pr-2 font-medium"><Link href={`/data/instruments?id=${r.instrument_id}`} className="text-brand hover:underline">{r.symbol}</Link></th>
                      <td className="px-2 text-right tabular-nums text-ink-soft">{r.entry_day ?? "–"}</td>
                      <td className="px-2 text-right tabular-nums">{r.close !== null ? money(r.close) : "–"}</td>
                      <td className="px-2 text-right tabular-nums text-red-700">{Math.round(r.rank_pct)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      ) : null}
      <p className="border-t border-line px-3 py-2 text-xs text-ink-faint">
        A frozen rule (model {d?.model_version ?? "–"}): a model ranks the liquid stocks each night by their chance of beating the median stock over the next 5 sessions; a stock ranked {d?.buy_at ?? 90} or more that is not held is bought at the next open, a held one ranked {d?.sell_at ?? 20} or lower is sold, in between it is held. No stop, long only, at most {slots} positions.
        Tested on 2022 to 2024: +0.29% per trade over the market after real costs (about 22 sessions held, a win rate near 55%). Read once on 2025 to 2026, outside the formal holdout route and so not confirmatory: +0.81% per trade while the market fell, much of it from which stocks the model keeps and not from timing. A lean from past prices, not advice and not an order.
      </p>
    </Panel>
  );
}
