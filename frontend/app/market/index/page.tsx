"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { IndexChart } from "@/components/charts/IndexChart";
import { Pct, PriceText, useLiveQuotes } from "@/components/market/LivePrice";
import { NoteChips, useNotes } from "@/components/market/NoteChips";
import { Alert } from "@/components/ui/Alert";
import { type Column, DataTable, Skeleton } from "@/components/ui/DataTable";
import { Panel } from "@/components/ui/Layout";
import { ApiError, api } from "@/lib/api/client";
import type { IndexMembers } from "@/lib/schemas";

type Member = IndexMembers["members"][number];
type SortKey = "change" | "symbol";

/** Every stock inside one index or industry group, with its live price and change, strongest mover first. Reached by clicking an index card or a sector row. */
function Members() {
  const params = useSearchParams();
  const symbol = params.get("symbol") ?? undefined;
  const industry = params.get("industry") ?? undefined;
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "change", desc: true });
  const q = useQuery({ queryKey: ["market", "members", symbol ?? "", industry ?? ""], queryFn: () => api.indexMembers({ symbol, industry }), enabled: Boolean(symbol || industry), retry: false });
  const members = useMemo(() => q.data?.members ?? [], [q.data]);
  const quotes = useLiveQuotes(members.map((m) => m.instrument_id));
  const notes = useNotes(members.map((m) => m.instrument_id));
  const rows = useMemo(() => {
    const change = (m: Member) => quotes[String(m.instrument_id)]?.change_pct ?? null;
    return [...members].sort((a, b) => {
      if (sort.key === "symbol") return sort.desc ? b.symbol.localeCompare(a.symbol) : a.symbol.localeCompare(b.symbol);
      const x = change(a), y = change(b);
      if (x === null && y === null) return a.symbol.localeCompare(b.symbol);
      if (x === null) return 1; // a stock with no price goes last whichever way it is sorted
      if (y === null) return -1;
      return sort.desc ? y - x : x - y;
    });
  }, [members, quotes, sort]);
  const moves = members.map((m) => quotes[String(m.instrument_id)]?.change_pct).filter((v): v is number => typeof v === "number");
  const up = moves.filter((v) => v > 0).length, down = moves.filter((v) => v < 0).length;
  const mean = moves.length ? moves.reduce((a, b) => a + b, 0) / moves.length : null;
  const toggle = (key: SortKey) => setSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: key === "change" }));
  const sorter = (key: SortKey, label: string) => (
    <button type="button" onClick={() => toggle(key)} aria-pressed={sort.key === key} className={`rounded border px-2 py-0.5 text-xs ${sort.key === key ? "border-brand bg-brand/10 font-semibold" : "border-line"}`}>
      {label}{sort.key === key ? (sort.desc ? " ↓" : " ↑") : ""}
    </button>
  );
  const columns: Column<Member>[] = [
    { key: "symbol", header: "Stock", cell: (m) => <Link href={`/data/instruments?id=${m.instrument_id}`} className="font-medium text-brand hover:underline">{m.symbol}</Link> },
    { key: "name", header: "Name", hideBelow: "sm", cell: (m) => <span className="text-ink-soft">{m.name}</span> },
    { key: "industry", header: "Industry", hideBelow: "md", cell: (m) => <span className="text-ink-soft">{m.industry}</span> },
    { key: "price", header: "Live price and change", className: "text-right", cell: (m) => <PriceText quote={quotes[String(m.instrument_id)]} /> },
    { key: "notes", header: "Notes", cell: (m) => <NoteChips notes={notes[String(m.instrument_id)]} /> },
  ];
  if (!symbol && !industry) return <Alert tone="info" title="Nothing chosen">Open an index or sector from the Overview.</Alert>;
  const d = q.data;
  const none = q.isError && q.error instanceof ApiError && q.error.status === 404; // NSE publishes no list for it: the chart is still worth showing
  const subtitle = d ? (d.kind === "index" ? `The ${members.length} stocks in this index, from NSE's list of ${d.as_of}.` : `The ${members.length} Nifty 500 stocks NSE files under this industry.`) : none ? "Its chart is below. NSE publishes no list of stocks for it." : undefined;
  return (
    <div className="space-y-4">
      <PageHeader title={d?.name ?? symbol ?? industry ?? ""} subtitle={subtitle} />
      {d ? (
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm" aria-label="Summary">
          <span><span className="font-semibold text-emerald-700">{up}</span> up</span>
          <span><span className="font-semibold text-red-700">{down}</span> down</span>
          <span>Average move <span className="font-semibold"><Pct v={mean} /></span></span>
          {d.unmatched > 0 ? <span className="text-ink-faint">{d.unmatched} on the list not in our stock master</span> : null}
        </div>
      ) : null}
      {symbol ? <IndexChart symbol={symbol} /> : null}
      {q.isError ? (
        <Alert tone={none ? "info" : "error"} title={none ? "No list of stocks for this one" : "Could not load the stocks"}>{none ? "NSE publishes no constituent list for it (the BSE Sensex and India VIX, for instance), so there are no stocks to list; the chart above is its own price history." : "Try again in a moment."}</Alert>
      ) : q.isLoading || !d ? (
        <div role="status" aria-label="Loading the stocks"><Skeleton className="h-48 w-full" /></div>
      ) : (
        <Panel title="Stocks" actions={<div className="flex items-center gap-2 text-xs text-ink-soft">Sort by {sorter("change", "Change")} {sorter("symbol", "Name")}</div>}>
          <DataTable caption="Stocks in the index with their live price and change" columns={columns} rows={rows} rowKey={(m) => String(m.instrument_id)} empty="No stocks matched our instruments." />
        </Panel>
      )}
    </div>
  );
}

export default function IndexMembersPage() {
  return <Suspense fallback={null}><Members /></Suspense>;
}
