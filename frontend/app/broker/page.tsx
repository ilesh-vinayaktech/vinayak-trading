"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, Skeleton, type Column } from "@/components/ui/DataTable";
import { Panel, RelativeTime, StatCard } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { api } from "@/lib/api/client";
import { fmtMoney } from "@/lib/formatting";
import type { BrokerAccount } from "@/lib/schemas";

type Holding = BrokerAccount["holdings"][number];
type Position = BrokerAccount["positions"][number];

const tone = (pnl: string) => (Number.parseFloat(pnl) < 0 ? "text-red-600" : Number.parseFloat(pnl) > 0 ? "text-emerald-700" : "");
const rupees = (s: string) => `₹${fmtMoney(s)}`;

/** The stock's name opens its detail page (chart, corporate actions, fundamentals) when we know the stock. */
function StockLink({ symbol, id }: { symbol: string; id: number | null }) {
  return id === null ? (
    <span className="font-medium" title="Not in our instrument list, so there is no detail page">{symbol}</span>
  ) : (
    <Link href={`/data/instruments?id=${id}`} className="font-medium text-brand hover:underline" aria-label={`Open ${symbol}`}>{symbol}</Link>
  );
}

const holdingColumns: Column<Holding>[] = [
  { key: "symbol", header: "Stock", cell: (h) => <StockLink symbol={h.symbol} id={h.instrument_id} /> },
  {
    key: "qty",
    header: "Shares",
    className: "text-right",
    cell: (h) => (
      <span>
        {fmtMoney(h.quantity, 0)}
        {Number.parseFloat(h.unsettled) > 0 ? <span className="block text-xs text-ink-soft">{fmtMoney(h.unsettled, 0)} not settled yet</span> : null}
      </span>
    ),
  },
  { key: "avg", header: "Average", className: "text-right", hideBelow: "sm", cell: (h) => rupees(h.average_price) },
  { key: "last", header: "Last", className: "text-right", hideBelow: "sm", cell: (h) => rupees(h.last_price) },
  { key: "value", header: "Value", className: "text-right", cell: (h) => rupees(h.value) },
  { key: "pnl", header: "Profit / loss", className: "text-right", cell: (h) => <span className={tone(h.pnl)}>{rupees(h.pnl)}</span> },
  {
    key: "owner",
    header: "Bought by",
    hideBelow: "md",
    cell: (h) => (
      <span className="text-ink-soft">
        {Number.parseFloat(h.platform_qty) > 0 ? `Platform ${fmtMoney(h.platform_qty, 0)}, ` : ""}
        {fmtMoney(h.outside_qty, 0)} outside the platform
      </span>
    ),
  },
];

const positionColumns: Column<Position>[] = [
  { key: "symbol", header: "Stock", cell: (p) => <StockLink symbol={p.symbol} id={p.instrument_id} /> },
  { key: "product", header: "Product", hideBelow: "sm", cell: (p) => p.product },
  { key: "qty", header: "Net shares", className: "text-right", cell: (p) => fmtMoney(p.quantity, 0) },
  { key: "avg", header: "Average", className: "text-right", hideBelow: "sm", cell: (p) => rupees(p.average_price) },
  { key: "pnl", header: "Profit / loss", className: "text-right", cell: (p) => <span className={tone(p.pnl)}>{rupees(p.pnl)}</span> },
];

const PROBLEM: Record<Exclude<BrokerAccount["state"], "ok">, { title: string; text: string; link: boolean }> = {
  not_connected: { title: "Kite is not connected", text: "Connect to Zerodha to see your account here.", link: true },
  expired: { title: "The Kite session has ended", text: "Zerodha sessions end at 06:00 IST. Connect again to read your account.", link: true },
  unavailable: { title: "Kite did not answer", text: "Nothing is shown rather than a guess. Try again in a moment.", link: false },
};

/** What the signed-in person's Kite account holds right now: read only, nothing here can place or cancel an order. */
export default function BrokerPage() {
  const q = useQuery({ queryKey: ["broker", "account"], queryFn: api.brokerAccount });
  const d = q.data;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Broker account"
        subtitle="Your Kite holdings, today's positions and cash. Read only."
        actions={
          <button type="button" className={buttonClass("secondary")} disabled={q.isFetching} onClick={() => void q.refetch()}>
            {q.isFetching ? "Reading..." : "Refresh"}
          </button>
        }
      />
      {q.isError ? <Alert tone="error" title="Could not load the account">Try again in a moment.</Alert> : null}
      {q.isLoading ? <Skeleton className="h-28 w-full" /> : null}
      {d && d.state !== "ok" ? (
        <Alert tone={d.state === "unavailable" ? "error" : "warn"} title={PROBLEM[d.state].title}>
          {d.message ?? PROBLEM[d.state].text}{" "}
          {PROBLEM[d.state].link ? <Link href="/kite" className="font-medium text-brand hover:underline">Open Kite connection</Link> : null}
        </Alert>
      ) : null}
      {d && d.state === "ok" ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Cash available" value={d.cash === null ? "-" : rupees(d.cash)} hint={d.kite_user_id ? `Kite user ${d.kite_user_id}` : undefined} />
            <StatCard label="Holdings value" value={rupees(d.totals.holdings_value)} hint={`${d.holdings.length} stock${d.holdings.length === 1 ? "" : "s"}`} />
            <StatCard label="Holdings profit / loss" value={rupees(d.totals.holdings_pnl)} tone={Number.parseFloat(d.totals.holdings_pnl) < 0 ? "bad" : undefined} />
            <StatCard label="Read from Kite" value={d.read_at ? <RelativeTime iso={d.read_at} /> : "-"} hint="Press Refresh to read again" />
          </div>
          <Alert tone="info" title="Shares you bought yourself are safe">
            The platform only ever sells shares it bought with its own orders. Shares and orders you place in the Kite app are listed here but never sold, cancelled or counted as a mismatch.
          </Alert>
          <Panel title="Holdings">
            <DataTable caption="Holdings" columns={holdingColumns} rows={d.holdings} rowKey={(h) => h.symbol} empty={<EmptyState icon="chart" title="No holdings">Nothing is held in the demat account.</EmptyState>} />
          </Panel>
          <Panel title="Today's positions">
            <DataTable caption="Today's positions" columns={positionColumns} rows={d.positions} rowKey={(p) => `${p.symbol}-${p.product}`} empty={<EmptyState icon="chart" title="No positions today">Delivery shares you buy today appear here and in holdings once settled.</EmptyState>} />
          </Panel>
        </>
      ) : null}
    </div>
  );
}
