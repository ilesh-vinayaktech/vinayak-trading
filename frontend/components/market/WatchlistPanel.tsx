"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { ApiError, api } from "@/lib/api/client";

const STATE_TONE: Record<string, "good" | "bad" | "warn" | "neutral" | "info"> = { Breakout: "good", Breakdown: "bad", "Breakout, weak volume": "warn", "Breakdown, weak volume": "warn", "Testing resistance": "info", "Testing support": "info" };

/** The stocks you keep an eye on, each with its swing score and where it sits against its levels. Yours alone; it never feeds an order. */
export function WatchlistPanel() {
  const qc = useQueryClient();
  const [symbol, setSymbol] = useState("");
  const matches = useQuery({ queryKey: ["search", symbol.trim()], queryFn: () => api.searchInstruments(symbol.trim()), enabled: symbol.trim().length >= 1, staleTime: 60_000 });
  const list = useQuery({ queryKey: ["watchlist"], queryFn: api.watchlist });
  const items = list.data?.items ?? [];
  const score = useQueries({ queries: items.map((w) => ({ queryKey: ["market", "score", w.symbol], queryFn: () => api.marketScore(w.symbol), retry: false, staleTime: 10 * 60_000 })) });
  const lv = useQueries({ queries: items.map((w) => ({ queryKey: ["market", "levels", w.symbol], queryFn: () => api.marketLevels(w.symbol), retry: false, staleTime: 10 * 60_000 })) });
  const add = useMutation({ mutationFn: (s: string) => api.watchAdd(s), onSuccess: () => { setSymbol(""); void qc.invalidateQueries({ queryKey: ["watchlist"] }); } });
  const remove = useMutation({ mutationFn: (id: number) => api.watchRemove(id), onSuccess: () => void qc.invalidateQueries({ queryKey: ["watchlist"] }) });
  if (list.isError) return null;
  return (
    <Panel title="Watchlist">
      <form className="flex gap-2 px-3 py-2" onSubmit={(e) => { e.preventDefault(); if (symbol.trim()) add.mutate(symbol.trim()); }}>
        <label className="sr-only" htmlFor="watch-symbol">Stock symbol</label>
        <input id="watch-symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="Add a stock, e.g. TANLA" list="watch-matches" autoComplete="off" className="w-56 rounded border border-line px-2 py-1 text-sm" />
        <datalist id="watch-matches">{(matches.data ?? []).filter((i) => i.status === "active").map((i) => <option key={i.id} value={i.symbol}>{i.name}</option>)}</datalist>
        <button type="submit" className="rounded border border-line px-3 py-1 text-sm font-medium hover:bg-slate-50" disabled={add.isPending}>Add</button>
        {add.isError ? <span role="alert" className="self-center text-sm text-red-700">{add.error instanceof ApiError && add.error.status === 404 ? "No such listed stock." : "Could not add it."}</span> : null}
      </form>
      {items.length === 0 ? <p className="px-3 pb-3 text-sm text-ink-soft">Nothing watched yet.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-left text-sm">
            <caption className="sr-only">Watched stocks with their score and breakout state</caption>
            <thead className="border-b border-line text-xs text-ink-soft"><tr><th scope="col" className="px-3 py-2">Stock</th><th scope="col" className="px-2 text-right">Score</th><th scope="col" className="px-2">Status</th><th scope="col" className="px-2"><span className="sr-only">Remove</span></th></tr></thead>
            <tbody>
              {items.map((w, i) => {
                const sc = score[i]?.data?.scored ? score[i]?.data?.score : null;
                const st = lv[i]?.data?.status?.state;
                return (
                  <tr key={w.instrument_id} className="border-b border-line last:border-0">
                    <th scope="row" className="whitespace-nowrap px-3 py-1.5 font-medium"><Link href={`/data/instruments?id=${w.instrument_id}`} className="text-brand hover:underline">{w.symbol}</Link></th>
                    <td className={`px-2 text-right tabular-nums ${sc == null ? "text-ink-faint" : sc < 40 ? "text-red-700" : sc > 70 ? "text-emerald-700" : ""}`}>{sc == null ? "–" : Math.round(sc)}</td>
                    <td className="px-2">{st ? <StatusPill tone={STATE_TONE[st] ?? "neutral"}>{st}</StatusPill> : <span className="text-ink-faint">–</span>}</td>
                    <td className="px-2 text-right"><button type="button" className="text-xs text-ink-soft hover:underline" aria-label={`Remove ${w.symbol}`} onClick={() => remove.mutate(w.instrument_id)}>Remove</button></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
