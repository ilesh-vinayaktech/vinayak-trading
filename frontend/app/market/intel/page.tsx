"use client";

import { PriceText, useLiveQuotes } from "@/components/market/LivePrice";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type ReactNode } from "react";
import { cr, day, inr, pct, signed, tone } from "@/components/market/format";
import { PageHeader } from "@/components/layout/PageHeader";
import { ErrorBox, Stat } from "@/components/status/LoadState";
import { type Column, DataTable } from "@/components/ui/DataTable";
import { Panel, Tabs } from "@/components/ui/Layout";
import { inputClass } from "@/components/ui/styles";
import { api } from "@/lib/api/client";
import type { NseFlows } from "@/lib/schemas";

type Tab = "flows" | "active" | "delivery" | "deals" | "insider";
type Flow = NseFlows["rows"][number];

/** A symbol that opens the stock's own page (Data Explorer) when we know its instrument id. */
const Sym = ({ id, symbol }: { id?: number | null; symbol: string }): ReactNode =>
  id ? (
    <Link className="font-medium text-brand-dark hover:underline" href={`/data/instruments?id=${id}`}>
      {symbol}
    </Link>
  ) : (
    symbol
  );

const net = (rows: Flow[], key: "fii_net" | "dii_net", n: number) => rows.slice(0, n).reduce((s, r) => s + (r[key] ?? 0), 0);

const flowColumns: Column<Flow>[] = [
  { key: "date", header: "Session", cell: (r) => r.date },
  { key: "fb", header: "FII buy", hideBelow: "md", cell: (r) => cr(r.fii_buy) },
  { key: "fs", header: "FII sell", hideBelow: "md", cell: (r) => cr(r.fii_sell) },
  { key: "fn", header: "FII net", cell: (r) => <span className={`tabular-nums ${tone(r.fii_net)}`}>{cr(r.fii_net)}</span> },
  { key: "db", header: "DII buy", hideBelow: "md", cell: (r) => cr(r.dii_buy) },
  { key: "ds", header: "DII sell", hideBelow: "md", cell: (r) => cr(r.dii_sell) },
  { key: "dn", header: "DII net", cell: (r) => <span className={`tabular-nums ${tone(r.dii_net)}`}>{cr(r.dii_net)}</span> },
];

function Flows() {
  const q = useQuery({ queryKey: ["nse-flows"], queryFn: () => api.nseFlows(120) });
  if (q.error) return <ErrorBox error={q.error} what="FII / DII flows" />;
  const rows = q.data?.rows ?? [];
  return (
    <>
      <div className="grid grid-cols-2 gap-4 border-b border-line p-5 md:grid-cols-4">
        <Stat label="FII net, last session" value={<span className={tone(rows[0]?.fii_net ?? null)}>{cr(rows[0]?.fii_net)}</span>} hint={rows[0]?.date} />
        <Stat label="DII net, last session" value={<span className={tone(rows[0]?.dii_net ?? null)}>{cr(rows[0]?.dii_net)}</span>} />
        <Stat label={`FII net, ${Math.min(5, rows.length)} sessions`} value={<span className={tone(net(rows, "fii_net", 5))}>{cr(net(rows, "fii_net", 5))}</span>} />
        <Stat label={`DII net, ${Math.min(20, rows.length)} sessions`} value={<span className={tone(net(rows, "dii_net", 20))}>{cr(net(rows, "dii_net", 20))}</span>} />
      </div>
      <DataTable<Flow> caption="FII and DII cash market flows" columns={flowColumns} rows={q.data?.rows} loading={q.isLoading} rowKey={(r) => r.date} empty="No flows stored yet: NSE publishes only the latest session, so history builds from the first daily run." />
      <p className="px-5 py-3 text-xs text-ink-soft">Cash market, ₹ crore, as NSE publishes them each evening. These are market-wide; for one stock see its FII / DII holding on its page or in the screener.</p>
    </>
  );
}

function Active() {
  const [by, setBy] = useState<"value" | "volume">("value");
  const q = useQuery({ queryKey: ["nse-active", by], queryFn: () => api.nseMostActive(by) });
  const quotes = useLiveQuotes((q.data?.rows ?? []).flatMap((r) => (r.id ? [r.id] : [])));
  if (q.error) return <ErrorBox error={q.error} what="most active stocks" />;
  type R = NonNullable<typeof q.data>["rows"][number];
  const cols: Column<R>[] = [
    { key: "s", header: "Stock", cell: (r) => Sym({ id: r.id, symbol: r.symbol }) },
    { key: "live", header: "Live price", className: "text-right", hideBelow: "sm", cell: (r) => <PriceText quote={r.id ? quotes[String(r.id)] : undefined} /> },
    { key: "c", header: "Close", cell: (r) => inr(r.close) },
    { key: "v", header: "Volume", cell: (r) => inr(r.volume, 0) },
    { key: "t", header: "Traded value", cell: (r) => cr(r.traded_value / 1e7) },
  ];
  return (
    <>
      <div className="flex items-center gap-3 border-b border-line p-4 text-sm">
        <label htmlFor="by">Rank by</label>
        <select id="by" className={inputClass} value={by} onChange={(e) => setBy(e.target.value as "value" | "volume")}>
          <option value="value">Traded value</option>
          <option value="volume">Volume</option>
        </select>
        <span className="text-ink-soft">Session {q.data?.day ?? "–"}</span>
      </div>
      <DataTable<R> caption="Most active stocks" columns={cols} rows={q.data?.rows} loading={q.isLoading} rowKey={(r) => r.symbol} empty="No daily bars loaded." />
    </>
  );
}

function Delivery() {
  const [minVol, setMinVol] = useState(100000);
  const q = useQuery({ queryKey: ["nse-delivery", minVol], queryFn: () => api.nseDelivery(minVol) });
  const quotes = useLiveQuotes((q.data?.rows ?? []).flatMap((r) => (r.id ? [r.id] : [])));
  if (q.error) return <ErrorBox error={q.error} what="delivery %" />;
  type R = NonNullable<typeof q.data>["rows"][number];
  const cols: Column<R>[] = [
    { key: "s", header: "Stock", cell: (r) => Sym({ id: r.id, symbol: r.symbol }) },
    { key: "live", header: "Live price", className: "text-right", hideBelow: "sm", cell: (r) => <PriceText quote={r.id ? quotes[String(r.id)] : undefined} /> },
    { key: "c", header: "Close", cell: (r) => inr(r.close) },
    { key: "v", header: "Volume", hideBelow: "sm", cell: (r) => inr(r.volume, 0) },
    { key: "d", header: "Delivered", hideBelow: "sm", cell: (r) => inr(r.delivery_qty, 0) },
    { key: "p", header: "Delivery %", cell: (r) => <span className="font-medium tabular-nums">{pct(r.delivery_pct)}</span> },
  ];
  return (
    <>
      <div className="flex items-center gap-3 border-b border-line p-4 text-sm">
        <label htmlFor="mv">Minimum volume</label>
        <select id="mv" className={inputClass} value={minVol} onChange={(e) => setMinVol(Number(e.target.value))}>
          {[0, 100000, 500000, 1000000].map((v) => (
            <option key={v} value={v}>{inr(v, 0)}</option>
          ))}
        </select>
        <span className="text-ink-soft">Session {q.data?.day ?? "–"}. For a full screen on delivery, ownership and insiders use the <Link className="text-brand-dark hover:underline" href="/screener">screener</Link>.</span>
      </div>
      <DataTable<R> caption="Highest delivery percentage" columns={cols} rows={q.data?.rows} loading={q.isLoading} rowKey={(r) => r.symbol} empty="No delivery data loaded." />
    </>
  );
}

function Deals() {
  const [days, setDays] = useState(7);
  const q = useQuery({ queryKey: ["nse-deals", days], queryFn: () => api.nseDeals(days) });
  const quotes = useLiveQuotes((q.data?.rows ?? []).flatMap((r) => (r.id ? [r.id] : [])));
  if (q.error) return <ErrorBox error={q.error} what="bulk and block deals" />;
  type R = NonNullable<typeof q.data>["rows"][number];
  const cols: Column<R>[] = [
    { key: "d", header: "Date", cell: (r) => r.date },
    { key: "s", header: "Stock", cell: (r) => Sym({ id: r.id, symbol: r.symbol }) },
    { key: "live", header: "Live price", className: "text-right", hideBelow: "sm", cell: (r) => <PriceText quote={r.id ? quotes[String(r.id)] : undefined} /> },
    { key: "k", header: "Kind", hideBelow: "sm", cell: (r) => r.kind },
    { key: "c", header: "Client", cell: (r) => r.client },
    { key: "side", header: "Side", cell: (r) => <span className={r.side === "BUY" ? "text-emerald-700" : "text-red-700"}>{r.side}</span> },
    { key: "q", header: "Shares", hideBelow: "md", cell: (r) => inr(r.quantity, 0) },
    { key: "p", header: "Price", hideBelow: "md", cell: (r) => inr(r.price) },
    { key: "v", header: "Value", cell: (r) => cr(r.value_cr) },
  ];
  return (
    <>
      <div className="flex items-center gap-3 border-b border-line p-4 text-sm">
        <label htmlFor="dd">Window</label>
        <select id="dd" className={inputClass} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[1, 7, 30, 90].map((v) => (
            <option key={v} value={v}>{v === 1 ? "latest session" : `${v} days`}</option>
          ))}
        </select>
      </div>
      <DataTable<R> caption="Bulk and block deals" columns={cols} rows={q.data?.rows} loading={q.isLoading} rowKey={(r) => `${r.date}${r.kind}${r.symbol}${r.client}${r.side}${r.quantity}${r.price}`} empty="No deals stored for this window." />
    </>
  );
}

function Insider() {
  const [days, setDays] = useState(30);
  const q = useQuery({ queryKey: ["nse-insider", days], queryFn: () => api.nseInsider(days) });
  const quotes = useLiveQuotes((q.data?.rows ?? []).flatMap((r) => (r.id ? [r.id] : [])));
  if (q.error) return <ErrorBox error={q.error} what="insider trades" />;
  type R = NonNullable<typeof q.data>["rows"][number];
  const cols: Column<R>[] = [
    { key: "at", header: "Filed", cell: (r) => day(r.broadcast_at) },
    { key: "s", header: "Stock", cell: (r) => Sym({ id: r.id, symbol: r.symbol }) },
    { key: "live", header: "Live price", className: "text-right", hideBelow: "sm", cell: (r) => <PriceText quote={r.id ? quotes[String(r.id)] : undefined} /> },
    { key: "p", header: "Person", cell: (r) => <span>{r.person} <span className="text-xs text-ink-soft">{r.category ?? ""}</span></span> },
    { key: "t", header: "Type", cell: (r) => <span className={r.type === "Buy" ? "text-emerald-700" : r.type === "Sell" ? "text-red-700" : ""}>{r.type ?? "–"}</span> },
    { key: "q", header: "Shares", hideBelow: "md", cell: (r) => inr(r.quantity, 0) },
    { key: "v", header: "Value", cell: (r) => (r.value === null ? "–" : cr(r.value / 1e7)) },
    { key: "a", header: "Holding after", hideBelow: "md", cell: (r) => (r.pct_after === null ? "–" : `${signed(r.pct_after)}%`) },
  ];
  return (
    <>
      <div className="flex items-center gap-3 border-b border-line p-4 text-sm">
        <label htmlFor="id">Window</label>
        <select id="id" className={inputClass} value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90, 365].map((v) => (
            <option key={v} value={v}>{v} days</option>
          ))}
        </select>
        <span className="text-ink-soft">Counted back from the newest disclosure NSE has served.</span>
      </div>
      <DataTable<R> caption="Insider trades" columns={cols} rows={q.data?.rows} loading={q.isLoading} rowKey={(r) => r.did} empty="No insider trades stored for this window." />
    </>
  );
}

export default function MarketIntelPage() {
  const [tab, setTab] = useState<Tab>("flows");
  return (
    <>
      <PageHeader title="FII / DII, deals and insiders" subtitle="What institutions and insiders are doing, from NSE. Open any stock from a list to see its own smart-money page." />
      <Panel
        actions={
          <Tabs<Tab>
            label="Smart money view"
            value={tab}
            onChange={setTab}
            tabs={[
              { key: "flows", label: "FII / DII flows" },
              { key: "active", label: "Most active" },
              { key: "delivery", label: "High delivery" },
              { key: "deals", label: "Bulk / block deals" },
              { key: "insider", label: "Insider trades" },
            ]}
          />
        }
      >
        {tab === "flows" ? <Flows /> : tab === "active" ? <Active /> : tab === "delivery" ? <Delivery /> : tab === "deals" ? <Deals /> : <Insider />}
      </Panel>
    </>
  );
}
