"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, ErrorBox, Loading, Stat } from "@/components/status/LoadState";
import { DataTable, type Column } from "@/components/ui/DataTable";
import { api } from "@/lib/api/client";
import type { NseInstrument } from "@/lib/schemas";
import { cr, day, delta, inr, pct, signed, tone } from "./format";

type Holding = NseInstrument["holdings"][number];
type Delivery = NseInstrument["delivery"][number];
type Insider = NseInstrument["insider"][number];
type Deal = NseInstrument["deals"][number];

const HOLDERS = [
  ["promoter", "Promoter"],
  ["fii", "FII / FPI"],
  ["dii", "DII"],
  ["mf", "Mutual funds"],
  ["retail", "Retail"],
] as const;

/** Who holds the stock, quarter by quarter; the change column compares each filing with the one before it. */
function holdingColumns(rows: Holding[]): Column<Holding>[] {
  return [
    { key: "period", header: "Quarter end", cell: (h) => h.period_end },
    ...HOLDERS.map(([k, label]) => ({
      key: k,
      header: label,
      cell: (h: Holding) => {
        const i = rows.indexOf(h);
        const d = delta(h[k], rows[i + 1]?.[k]);
        return (
          <span className="tabular-nums">
            {pct(h[k])} {d !== null ? <span className={`text-xs ${tone(d)}`}>{signed(d)}</span> : null}
          </span>
        );
      },
    })),
  ];
}

const deliveryColumns: Column<Delivery>[] = [
  { key: "date", header: "Session", cell: (r) => r.date },
  { key: "close", header: "Close", cell: (r) => inr(r.close) },
  { key: "volume", header: "Volume", hideBelow: "sm", cell: (r) => inr(r.volume, 0) },
  { key: "dq", header: "Delivered", hideBelow: "sm", cell: (r) => inr(r.delivery_qty, 0) },
  {
    key: "pct",
    header: "Delivery %",
    cell: (r) => (
      <span className="flex items-center gap-2 tabular-nums">
        <span aria-hidden="true" className="h-1.5 w-20 rounded bg-slate-100">
          <span className="block h-1.5 rounded bg-brand" style={{ width: `${Math.min(100, r.delivery_pct ?? 0)}%` }} />
        </span>
        {pct(r.delivery_pct)}
      </span>
    ),
  },
];

const insiderColumns: Column<Insider>[] = [
  { key: "at", header: "Filed", cell: (r) => day(r.broadcast_at) },
  { key: "person", header: "Person", cell: (r) => <span>{r.person} <span className="text-xs text-ink-soft">{r.category ?? ""}</span></span> },
  { key: "type", header: "Type", cell: (r) => <span className={r.type === "Buy" ? "text-emerald-700" : r.type === "Sell" ? "text-red-700" : ""}>{r.type ?? "–"}</span> },
  { key: "qty", header: "Shares", hideBelow: "sm", cell: (r) => inr(r.quantity, 0) },
  { key: "value", header: "Value", cell: (r) => (r.value === null ? "–" : cr(r.value / 1e7)) },
  { key: "after", header: "Holding after", hideBelow: "md", cell: (r) => pct(r.pct_after) },
];

const dealColumns: Column<Deal>[] = [
  { key: "date", header: "Date", cell: (r) => r.date },
  { key: "kind", header: "Kind", cell: (r) => r.kind },
  { key: "client", header: "Client", cell: (r) => r.client },
  { key: "side", header: "Side", cell: (r) => <span className={r.side === "BUY" ? "text-emerald-700" : "text-red-700"}>{r.side}</span> },
  { key: "qty", header: "Shares", hideBelow: "sm", cell: (r) => inr(r.quantity, 0) },
  { key: "price", header: "Price", hideBelow: "sm", cell: (r) => inr(r.price) },
  { key: "value", header: "Value", cell: (r) => cr(r.value_cr) },
];

/** Smart-money view of one stock: delivery %, ownership by category, insider trades, bulk and block deals (NSE). */
export function SmartMoneyPanel({ instrumentId }: { instrumentId: number }) {
  const q = useQuery({ queryKey: ["nse-instrument", instrumentId], queryFn: () => api.nseInstrument(instrumentId) });
  if (q.isLoading) return <Loading what="smart-money data" />;
  if (q.error || !q.data) return <ErrorBox error={q.error} what="smart-money data" />;
  const d = q.data;
  const latest = d.delivery[0];
  const last20 = d.delivery.slice(0, 20).filter((r) => r.delivery_pct !== null);
  const avg = last20.length ? last20.reduce((s, r) => s + (r.delivery_pct ?? 0), 0) / last20.length : null;
  const h0 = d.holdings[0];
  const bought = d.insider.filter((r) => r.type === "Buy").length;
  const sold = d.insider.filter((r) => r.type === "Sell").length;
  return (
    <div className="space-y-4">
      <Card
        title={`${d.symbol}: smart money`}
        note="From NSE: delivery from the daily bhavcopy; holdings from each quarterly shareholding filing (the FII / DII split appears once its filing has been read); insider trades from SEBI insider-trading disclosures; deals from NSE bulk and block files (history starts when the daily job first ran)."
      >
        <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
          <Stat label="Delivery % (last session)" value={pct(latest?.delivery_pct)} hint={latest?.date} />
          <Stat label="Delivery %, 20-session avg" value={pct(avg)} />
          <Stat label="FII / FPI" value={pct(h0?.fii)} hint={h0?.period_end} />
          <Stat label="DII" value={pct(h0?.dii)} hint={h0 ? `MF ${pct(h0.mf)}` : undefined} />
          <Stat label="Promoter" value={pct(h0?.promoter)} />
        </div>
        <p className="mt-3 text-xs text-ink-soft">Insider filings listed: {bought} buys, {sold} sells.</p>
      </Card>
      <Card title="Ownership by quarter">
        <DataTable<Holding> caption="Shareholding pattern by quarter" columns={holdingColumns(d.holdings)} rows={d.holdings} rowKey={(h) => h.period_end} empty="No shareholding filing stored for this stock yet." />
      </Card>
      <Card title="Delivery % by session">
        <DataTable<Delivery> caption="Delivery percentage by session" columns={deliveryColumns} rows={d.delivery.slice(0, 20)} rowKey={(r) => r.date} empty="No delivery data for this stock." />
      </Card>
      <Card title="Insider trades">
        <DataTable<Insider> caption="Insider trades" columns={insiderColumns} rows={d.insider} rowKey={(r) => r.did} empty="No insider trades stored for this stock." />
      </Card>
      <Card title="Bulk and block deals">
        <DataTable<Deal> caption="Bulk and block deals" columns={dealColumns} rows={d.deals} rowKey={(r) => `${r.date}${r.kind}${r.client}${r.side}${r.quantity}${r.price}`} empty="No bulk or block deal stored for this stock yet." />
      </Card>
    </div>
  );
}
