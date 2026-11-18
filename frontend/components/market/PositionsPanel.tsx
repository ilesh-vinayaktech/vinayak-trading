"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { PriceCell, useLiveQuotes } from "@/components/market/LivePrice";
import { NoteChips, useNotes } from "@/components/market/NoteChips";
import { Panel } from "@/components/ui/Layout";
import { ApiError, api } from "@/lib/api/client";

const money = (n: number) => n.toLocaleString("en-IN", { maximumFractionDigits: 2 });

/** The nearest support and resistance and the breakout state of one holding. */
function Levels({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ["market", "levels", symbol], queryFn: () => api.marketLevels(symbol), retry: false, staleTime: 10 * 60_000 });
  const d = q.data;
  if (!d || !d.enough_history || !d.status) return <><td className="px-2 text-ink-faint">–</td><td className="px-2 text-ink-faint">–</td></>;
  const sup = d.supports?.[0], res = d.resistances?.[0];
  return (
    <>
      <td className="px-2 text-right tabular-nums">{sup ? <span title={`${sup.distance_pct.toFixed(1)}% below`}>{money(sup.price)}</span> : "–"}</td>
      <td className="px-2 text-right tabular-nums">{res ? <span title={`${res.distance_pct.toFixed(1)}% above`}>{money(res.price)}</span> : "–"}</td>
    </>
  );
}

/** The swing score of one holding (0 to 100), coloured like the order caution: under 40 is weak, over 70 strong. */
function Score({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ["market", "score", symbol], queryFn: () => api.marketScore(symbol), retry: false, staleTime: 10 * 60_000 });
  const v = q.data?.scored ? q.data.score : null;
  if (v === null || v === undefined) return <td className="px-2 text-right text-ink-faint">–</td>;
  return <td className={`px-2 text-right tabular-nums ${v < 40 ? "text-red-700" : v > 70 ? "text-emerald-700" : ""}`}>{Math.round(v)}</td>;
}

/** What you hold in the paper account, with where each sits against its levels. Nothing is shown without an account. */
export function PositionsPanel() {
  const q = useQuery({ queryKey: ["paper", "summary", "paper"], queryFn: () => api.paperSummary("paper"), retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 1 });
  const rows = q.data?.positions ?? [];
  const quotes = useLiveQuotes(rows.map((p) => p.instrument_id));
  const notes = useNotes(rows.map((p) => p.instrument_id));
  if (q.isError || !q.data || rows.length === 0) return null;
  return (
    <Panel title="Your positions and their levels" actions={<Link href="/paper" className="text-sm font-medium text-brand hover:underline">Paper trading</Link>}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[900px] text-left text-sm">
          <caption className="sr-only">Positions with the nearest support and resistance</caption>
          <thead className="border-b border-line text-xs text-ink-soft"><tr><th scope="col" className="px-3 py-2">Stock</th><th scope="col" className="px-2 text-right">Qty</th><th scope="col" className="px-2 text-right">Live price</th><th scope="col" className="px-2 text-right">Unrealised</th><th scope="col" className="px-2 text-right">Score</th><th scope="col" className="px-2 text-right">Support</th><th scope="col" className="px-2 text-right">Resistance</th><th scope="col" className="px-2">Notes</th></tr></thead>
          <tbody>
            {rows.map((p) => {
              const u = Number(p.unrealized);
              return (
                <tr key={p.instrument_id} className="border-b border-line last:border-0">
                  <th scope="row" className="whitespace-nowrap px-3 py-1.5 font-medium"><Link href={`/data/instruments?id=${p.instrument_id}`} className="text-brand hover:underline">{p.symbol}</Link></th>
                  <td className="px-2 text-right tabular-nums">{p.qty}</td>
                  <PriceCell quote={quotes[String(p.instrument_id)]} />
                  <td className={`px-2 text-right tabular-nums ${u > 0 ? "text-emerald-700" : u < 0 ? "text-red-700" : ""}`}>{u > 0 ? "+" : ""}{money(u)}</td>
                  <Score symbol={p.symbol} />
                  <Levels symbol={p.symbol} />
                  <td className="px-2"><NoteChips notes={notes[String(p.instrument_id)]} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
