"use client";

import { UpcomingNote } from "@/components/paper/UpcomingNote";
import { useQuery } from "@tanstack/react-query";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, Skeleton, type Column } from "@/components/ui/DataTable";
import { Panel, StatCard } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import { fmtMoney, plotNumber } from "@/lib/formatting";
import type { LiveQuote, PaperSummary } from "@/lib/schemas";
import { PriceText, useLiveQuotes } from "@/components/market/LivePrice";
import { useVenue } from "@/lib/venue";

const sign = (s: string) => (s.startsWith("-") ? "bad" : /^0(\.0+)?$/.test(s) ? undefined : "good");
const rupees = (s: string) => (s.startsWith("-") ? `-₹${fmtMoney(s.slice(1))}` : `₹${fmtMoney(s)}`);

/** The account's value over time, drawn from the figures the API sent (plotting only: nothing displayed is computed here). */
function Curve({ points }: { points: PaperSummary["equity_curve"] }) {
  if (points.length < 2) return <p className="px-5 py-8 text-center text-sm text-ink-soft">The value chart appears after the second trading day.</p>;
  const ys = points.map((p) => plotNumber(p.equity));
  const lo = Math.min(...ys);
  const hi = Math.max(...ys);
  const span = hi - lo || 1;
  const path = ys.map((y, i) => `${i === 0 ? "M" : "L"}${(i / (ys.length - 1)) * 600},${110 - ((y - lo) / span) * 100}`).join(" ");
  const first = points[0];
  const last = points[points.length - 1];
  return (
    <figure className="px-5 py-4">
      <svg viewBox="0 0 600 120" preserveAspectRatio="none" role="img" aria-label={`Account value from ${first?.day} to ${last?.day}`} className="h-40 w-full">
        <path d={path} fill="none" stroke="currentColor" strokeWidth={2} className="text-brand" vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption className="mt-1 flex justify-between text-xs text-ink-soft">
        <span>{first?.day}</span>
        <span>{last?.day}</span>
      </figcaption>
    </figure>
  );
}

const columns = (quotes: Record<string, LiveQuote>): Column<PaperSummary["positions"][number]>[] => [
  { key: "symbol", header: "Stock", cell: (p) => <div><span className="font-medium">{p.symbol}</span><UpcomingNote items={p.upcoming} /></div> },
  { key: "qty", header: "Shares", className: "text-right", cell: (p) => fmtMoney(p.qty, 0) },
  { key: "avg", header: "Average cost", className: "text-right", hideBelow: "sm", cell: (p) => rupees(p.avg_cost) },
  { key: "last", header: "Live price", className: "text-right", cell: (p) => <PriceText quote={quotes[String(p.instrument_id)]} /> },
  { key: "value", header: "Value", className: "text-right", cell: (p) => rupees(p.value) },
  { key: "pnl", header: "Profit / loss", className: "text-right", cell: (p) => <span className={sign(p.unrealized) === "bad" ? "text-red-700" : sign(p.unrealized) === "good" ? "text-emerald-700" : ""}>{rupees(p.unrealized)}</span> },
];

export function Overview({ showPositions = true }: { showPositions?: boolean }) {
  const mode = useVenue();
  const q = useQuery({ queryKey: ["paper", mode, "summary"], queryFn: () => api.paperSummary(mode), refetchInterval: 60_000 });
  const d = q.data;
  const quotes = useLiveQuotes((d?.positions ?? []).map((p) => p.instrument_id));
  return (
    <div className="space-y-6">
      {q.isError ? <Alert tone="error" title="Could not load the account">Try again in a moment.</Alert> : null}
      {q.isLoading ? <div role="status" aria-label="Loading the account" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Skeleton className="h-28 w-full" /><Skeleton className="h-28 w-full" /><Skeleton className="h-28 w-full" /><Skeleton className="h-28 w-full" /></div> : null}
      {d ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Account value" value={rupees(d.equity)} hint={`${rupees(d.cash)} in cash`} />
            <StatCard label="Invested" value={rupees(d.invested)} hint={`${d.positions.length} position${d.positions.length === 1 ? "" : "s"}`} />
            <StatCard label="Net profit / loss" value={rupees(d.pnl.net)} tone={sign(d.pnl.net)} hint={`Fees ${rupees(d.pnl.fees)}`} />
            <StatCard label="Orders to answer" value={d.pending_orders} tone={d.pending_orders > 0 ? "warn" : undefined} hint={d.pending_orders > 0 ? "Open the Orders tab" : "Nothing waiting"} />
          </div>
          <Panel title="Account value over time">
            <Curve points={d.equity_curve} />
          </Panel>
          {showPositions ? (
            <Panel title="Positions">
              <DataTable caption="Positions" columns={columns(quotes)} rows={d.positions} rowKey={(p) => String(p.instrument_id)} empty={<EmptyState icon="chart" title="No positions yet">Positions appear once an approved order fills.</EmptyState>} />
            </Panel>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
