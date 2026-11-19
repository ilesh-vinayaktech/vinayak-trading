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

const HOLDER_FILL = ["fill-brand", "fill-sky-400", "fill-emerald-400", "fill-amber-400", "fill-slate-300"];
const HOLDER_DOT = ["bg-brand", "bg-sky-400", "bg-emerald-400", "bg-amber-400", "bg-slate-300"];

/** Who holds the stock, quarter by quarter, as stacked columns (oldest left); the legend gives the latest share and its change from the quarter before. A quarter whose FII / DII split has not been read shows the promoter and the rest of the public as one grey block. */
function OwnershipChart({ rows }: { rows: Holding[] }) {
  const cols = rows.slice(0, 8).reverse();
  if (cols.length === 0) return <p className="text-sm text-ink-soft">No shareholding filing stored for this stock yet.</p>;
  const W = 640, H = 200, T = 8, B = 20, L = 34, slot = (W - L) / cols.length, bw = Math.min(56, slot * 0.7);
  const y = (v: number) => T + (1 - v / 100) * (H - T - B);
  const x = (i: number) => L + i * slot + (slot - bw) / 2;
  const split = (c: Holding) => HOLDERS.slice(1).some(([k]) => c[k] != null);
  const anyUnsplit = cols.some((c) => !split(c));
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Ownership by quarter, stacked by holder category">
        {[0, 50, 100].map((g) => <g key={g}><line x1={L} x2={W} y1={y(g)} y2={y(g)} className="stroke-slate-200" /><text x={0} y={y(g) + 3} fontSize={10} className="fill-slate-500">{g}%</text></g>)}
        {cols.map((c, i) => {
          let top = 0;
          const parts: { key: string; v: number; cls: string; label: string }[] = split(c)
            ? HOLDERS.map(([k, label], j) => ({ key: k, v: c[k] ?? 0, cls: HOLDER_FILL[j] ?? "", label }))
            : [{ key: "promoter", v: c.promoter ?? 0, cls: HOLDER_FILL[0] ?? "", label: "Promoter" }, { key: "public", v: c.public ?? Math.max(0, 100 - (c.promoter ?? 0)), cls: "fill-slate-200", label: "Public (FII / DII split not read)" }];
          return (
            <g key={c.period_end}>
              {parts.map((p) => {
                const y0 = y(top + p.v);
                top += p.v;
                return p.v > 0 ? <rect key={p.key} x={x(i)} y={y0} width={bw} height={y(top - p.v) - y0} className={p.cls}><title>{`${c.period_end} ${p.label} ${pct(p.v)}`}</title></rect> : null;
              })}
              <text x={x(i) + bw / 2} y={H - 5} textAnchor="middle" className="fill-slate-500" fontSize={10}>{c.period_end.slice(0, 7)}</text>
            </g>
          );
        })}
      </svg>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {HOLDERS.map(([k, label], j) => {
          const d = delta(rows[0]?.[k], rows[1]?.[k]);
          return (
            <li key={k} className="flex items-center gap-1.5">
              <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-sm ${HOLDER_DOT[j]}`} />
              {label} <span className="tabular-nums">{pct(rows[0]?.[k])}</span>
              {d !== null ? <span className={`tabular-nums ${tone(d)}`}>{signed(d)}</span> : null}
            </li>
          );
        })}
        {anyUnsplit ? <li className="flex items-center gap-1.5 text-ink-soft"><span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm bg-slate-200" />Public, split not filed or read</li> : null}
      </ul>
    </div>
  );
}

const shares = (v: number) => (v >= 1e7 ? `${(v / 1e7).toFixed(1)} Cr` : v >= 1e5 ? `${(v / 1e5).toFixed(1)} L` : inr(v, 0));
const avgOf = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null);

/** Shares traded each session (light bar) with the part taken for delivery (dark bar inside it) and the delivery % as a line; below it, what the numbers say. */
function DeliveryChart({ rows }: { rows: Delivery[] }) {
  const cols = rows.slice(0, 20).reverse();
  if (cols.length === 0) return <p className="text-sm text-ink-soft">No delivery data for this stock.</p>;
  const W = 640, H = 200, T = 8, B = 20, L = 44, R = 34, slot = (W - L - R) / cols.length, bw = slot * 0.7;
  const maxV = Math.max(...cols.map((r) => r.volume), 1);
  const yv = (v: number) => T + (1 - v / maxV) * (H - T - B);
  const yp = (p: number) => T + (1 - p / 100) * (H - T - B);
  const x = (i: number) => L + i * slot + (slot - bw) / 2;
  const avgVol = avgOf(cols.map((r) => r.volume)) ?? 0;
  const line = cols.flatMap((r, i) => (r.delivery_pct === null ? [] : [`${x(i) + bw / 2},${yp(r.delivery_pct)}`])).join(" ");
  const last = rows[0];
  const prior = rows.slice(1, 21);
  const volRatio = last && prior.length ? last.volume / (avgOf(prior.map((r) => r.volume)) ?? 1) : null;
  const upDays: number[] = [], downDays: number[] = [];
  rows.slice(0, 20).forEach((r, i) => {
    const prev = rows[i + 1];
    if (!prev || r.delivery_pct === null || r.close === prev.close) return;
    (r.close > prev.close ? upDays : downDays).push(r.delivery_pct);
  });
  const up = avgOf(upDays), down = avgOf(downDays);
  const tilt = up === null || down === null ? null : up - down >= 3 ? "Buyers have been keeping more of the shares than sellers have: the rises came on more delivery than the falls." : down - up >= 3 ? "More delivery on the falling days than the rising days: the falls were the more committed moves." : "No clear tilt between the rising and falling days.";
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Shares traded and delivered by session, with delivery percentage">
        {[0, 50, 100].map((g) => <g key={g}><line x1={L} x2={W - R} y1={yp(g)} y2={yp(g)} className="stroke-slate-200" /><text x={W} y={yp(g) + 3} textAnchor="end" fontSize={10} className="fill-slate-500">{g}%</text></g>)}
        {[0, 0.5, 1].map((f) => <text key={f} x={L - 4} y={yv(maxV * f) + 3} textAnchor="end" fontSize={10} className="fill-slate-500">{f === 0 ? "0" : shares(maxV * f)}</text>)}
        {cols.map((r, i) => (
          <g key={r.date}>
            <rect x={x(i)} y={yv(r.volume)} width={bw} height={H - B - yv(r.volume)} className="fill-slate-200"><title>{`${r.date}: ${inr(r.volume, 0)} shares traded, ${inr(r.delivery_qty, 0)} delivered (${pct(r.delivery_pct)}), close ${inr(r.close)}`}</title></rect>
            <rect x={x(i)} y={yv(r.delivery_qty)} width={bw} height={H - B - yv(r.delivery_qty)} className="fill-brand" opacity={0.85} />
          </g>
        ))}
        <line x1={L} x2={W - R} y1={yv(avgVol)} y2={yv(avgVol)} className="stroke-slate-500" strokeDasharray="4 3"><title>{`Average volume ${shares(avgVol)}`}</title></line>
        {line ? <polyline points={line} fill="none" className="stroke-amber-500" strokeWidth={2} /> : null}
        {cols.map((r, i) => (r.delivery_pct === null ? null : <circle key={r.date} cx={x(i) + bw / 2} cy={yp(r.delivery_pct)} r={2.5} className="fill-amber-500" />))}
        <text x={L} y={H - 5} fontSize={10} className="fill-slate-500">{cols[0]?.date.slice(5)}</text>
        <text x={W - R} y={H - 5} textAnchor="end" fontSize={10} className="fill-slate-500">{cols[cols.length - 1]?.date.slice(5)}</text>
      </svg>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <li className="flex items-center gap-1.5"><span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm bg-brand" />Delivered shares</li>
        <li className="flex items-center gap-1.5"><span aria-hidden="true" className="h-2.5 w-2.5 rounded-sm bg-slate-200" />Traded and squared off the same day</li>
        <li className="flex items-center gap-1.5"><span aria-hidden="true" className="h-0.5 w-3 bg-amber-500" />Delivery % (right axis)</li>
        <li className="flex items-center gap-1.5"><span aria-hidden="true" className="h-0 w-3 border-t border-dashed border-slate-500" />Average volume {shares(avgVol)}</li>
      </ul>
      <ul className="mt-3 space-y-1 text-sm">
        {last ? <li>Last session: {shares(last.volume)} shares traded, {pct(last.delivery_pct)} delivered{volRatio !== null ? `; volume ${volRatio.toFixed(1)}× the 20-session average${volRatio >= 1.5 ? " (heavy)" : volRatio <= 0.7 ? " (quiet)" : ""}` : ""}.</li> : null}
        {up !== null && down !== null ? <li>Rising days averaged {pct(up)} delivery, falling days {pct(down)}. {tilt}</li> : null}
      </ul>
    </div>
  );
}

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
  const h1 = d.holdings[1];
  const pts = (k: (typeof HOLDERS)[number][0]) => {
    const v = delta(h0?.[k], h1?.[k]);
    return v === null || !h1 ? undefined : `${v > 0 ? "+" : ""}${v.toFixed(1)} pts vs ${h1.period_end.slice(0, 7)}`;
  };
  const ratio = latest?.delivery_pct != null && avg ? latest.delivery_pct / avg : null;
  const insBuy = d.insider.filter((r) => r.type === "Buy"), insSell = d.insider.filter((r) => r.type === "Sell");
  const sum = (rows: Insider[]) => rows.reduce((t, r) => t + (r.value ?? 0), 0) / 1e7;
  const dealSide = (side: string) => d.deals.filter((r) => r.side === side).reduce((t, r) => t + r.value_cr, 0);
  const dealNet = dealSide("BUY") - dealSide("SELL");
  type Point = { tone: "good" | "bad" | "neutral"; head: string; body: string };
  const points: Point[] = [];
  // Thresholds and wording come from scripts/tune_smart_money.py (weekly, liquid stocks, 2019-2026, return over the next 20 sessions against that day's median stock).
  // Delivery LEVEL had an edge in 7 of 8 years (50%+: beat the market 52% of the time; under 35%: 46-48%); a spike against the stock's own average had none.
  if (latest?.delivery_pct != null) {
    const lv = latest.delivery_pct;
    const spike = ratio !== null && ratio >= 1.5 ? ` It is ${ratio.toFixed(1)}× its own 20-session average, but a jump like that has not predicted anything on its own.` : "";
    points.push(lv >= 50
      ? { tone: "good", head: "High delivery", body: `${pct(lv)} of the last session was taken for delivery. Stocks that are mostly held, not traded in and out, beat the market about 52% of the time over the next four weeks (past data; 50% is no edge).${spike}` }
      : lv < 35
        ? { tone: "neutral", head: "Low delivery", body: `${pct(lv)} was taken for delivery: mostly intraday trading. Such stocks beat the market a little less often than half the time over the next four weeks (46-48% in past data).${spike}` }
        : { tone: "neutral", head: "Average delivery", body: `${pct(lv)} was taken for delivery, in the middle band where past data shows no edge either way.${spike}` });
  }
  const moved = HOLDERS.flatMap(([k, label]) => {
    const v = delta(h0?.[k], h1?.[k]);
    return v !== null && Math.abs(v) >= 0.25 ? [{ k, label, v }] : [];
  });
  const inst = moved.filter((m) => m.k === "fii" || m.k === "dii" || m.k === "mf");
  const instUp = inst.some((m) => m.v > 0) && !inst.some((m) => m.v < 0);
  if (h1)
    points.push(moved.length === 0
      ? { tone: "neutral", head: "Ownership is steady", body: `No holder group moved by 0.25 points or more since ${h1.period_end.slice(0, 7)}.` }
      : { tone: instUp ? "good" : "neutral", head: "Ownership changed", body: `${moved.map((m) => `${m.label} ${m.v > 0 ? "up" : "down"} ${Math.abs(m.v).toFixed(1)} pts to ${pct(h0?.[m.k])}`).join("; ")} since ${h1.period_end.slice(0, 7)}. ${instUp ? "Institutions adding has gone with a better chance of beating the market (about 55%), but only one year of FII / DII splits is stored, so treat that as early evidence." : "Falling institutional or promoter holding has not been a reliable warning in past data."}` });
  points.push(d.insider.length === 0
    ? { tone: "neutral", head: "No insider trades listed", body: "Nothing filed by promoters or directors in the stored history." }
    : { tone: "neutral", head: "Insiders", body: `${insBuy.length} ${insBuy.length === 1 ? "buy" : "buys"} (${cr(sum(insBuy))}) and ${insSell.length} ${insSell.length === 1 ? "sell" : "sells"} (${cr(sum(insSell))}) listed. Worth knowing, but in 8 years of filings a stock with heavy insider buying beat the market only 51% of the time, so it is context, not a signal.` });
  points.push(d.deals.length === 0
    ? { tone: "neutral", head: "No bulk or block deals", body: "No large single trade stored for this stock yet." }
    : { tone: "neutral", head: "Large deals", body: `${d.deals.length} bulk/block ${d.deals.length === 1 ? "deal" : "deals"}: ${cr(dealSide("BUY"))} bought, ${cr(dealSide("SELL"))} sold, net ${dealNet >= 0 ? "buying" : "selling"} of ${cr(Math.abs(dealNet))}. Net buying here has not helped in past data (the stock beat the market 43-46% of the time), often because the buying came after a rise. Check who the buyer was in the table.` });
  const DOT = { good: "bg-emerald-500", bad: "bg-red-500", neutral: "bg-slate-400" };
  return (
    <div className="space-y-4">
      <Card
        title={`${d.symbol}: smart money`}
        note="From NSE: delivery from the daily bhavcopy; holdings from each quarterly shareholding filing (the FII / DII split appears once its filing has been read); insider trades from SEBI insider-trading disclosures; deals from NSE bulk and block files (history starts when the daily job first ran). These are facts about who is buying and holding, not a forecast. The notes were checked against what happened next, over 2019-2026 (about 280,000 stock-weeks of liquid stocks, return over 20 sessions against the market that day)."
      >
        <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
          <Stat label="Delivery % (last session)" value={pct(latest?.delivery_pct)} hint={ratio !== null ? `${ratio.toFixed(1)}× its 20-session avg (${pct(avg)})` : latest?.date} />
          <Stat label="FII / FPI" value={pct(h0?.fii)} hint={pts("fii") ?? h0?.period_end} />
          <Stat label="DII" value={pct(h0?.dii)} hint={pts("dii") ?? (h0 ? `MF ${pct(h0.mf)}` : undefined)} />
          <Stat label="Mutual funds" value={pct(h0?.mf)} hint={pts("mf")} />
          <Stat label="Promoter" value={pct(h0?.promoter)} hint={pts("promoter")} />
        </div>
        <h3 className="mb-2 mt-4 text-xs font-semibold text-ink-soft">What stands out</h3>
        <ul className="grid gap-x-6 gap-y-2 text-sm md:grid-cols-2">
          {points.map((p) => (
            <li key={p.head} className="flex gap-2">
              <span aria-hidden="true" className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[p.tone]}`} />
              <span><span className="font-medium">{p.head}. </span>{p.body}</span>
            </li>
          ))}
        </ul>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Ownership by quarter"><OwnershipChart rows={d.holdings} /></Card>
        <Card title="Delivery and trade volume by session"><DeliveryChart rows={d.delivery} /></Card>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Insider trades">
          <div tabIndex={0} className="max-h-56 overflow-y-auto text-xs">
            <DataTable<Insider> caption="Insider trades" columns={insiderColumns} rows={d.insider} rowKey={(r) => r.did} empty="No insider trades stored for this stock." />
          </div>
        </Card>
        <Card title="Bulk and block deals">
          <div tabIndex={0} className="max-h-56 overflow-y-auto text-xs">
            <DataTable<Deal> caption="Bulk and block deals" columns={dealColumns} rows={d.deals} rowKey={(r) => `${r.date}${r.kind}${r.client}${r.side}${r.quantity}${r.price}`} empty="No bulk or block deal stored for this stock yet." />
          </div>
        </Card>
      </div>
    </div>
  );
}
