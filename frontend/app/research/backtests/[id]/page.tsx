"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, Skeleton, type Column } from "@/components/ui/DataTable";
import { Panel, StatCard, Tabs } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import { fmtMoney } from "@/lib/formatting";
import type { BacktestReport } from "@/lib/schemas";

type Trip = BacktestReport["round_trips"][number];
type Stock = BacktestReport["by_stock"][number];

/** Display only: the API sends ratios like "0.0360"; the figure on screen is that ratio as a percentage. */
const pct = (r: string | null) => (r === null ? "-" : `${(Number.parseFloat(r) * 100).toFixed(2)}%`);
const rs = (s: string | null) => (s === null ? "-" : `₹${fmtMoney(s, 2)}`);
const tone = (s: string | null) => (s === null ? undefined : s.startsWith("-") ? "bad" : s === "0" ? undefined : "good");
const colour = (s: string) => (s.startsWith("-") ? "text-red-600" : s === "0" ? "" : "text-emerald-700");

const TRIPS: Column<Trip>[] = [
  { key: "s", header: "Stock", cell: (t) => <span className="font-medium">{t.symbol}</span> },
  { key: "q", header: "Qty", className: "text-right", cell: (t) => t.qty },
  { key: "in", header: "Bought", cell: (t) => <span className="whitespace-nowrap">{t.entry_day} @ {fmtMoney(t.entry_price)}</span> },
  { key: "out", header: "Sold", cell: (t) => <span className="whitespace-nowrap">{t.exit_day} @ {fmtMoney(t.exit_price)}</span> },
  { key: "d", header: "Days held", className: "text-right", hideBelow: "md", cell: (t) => t.holding_days },
  { key: "g", header: "Before charges", className: "text-right", hideBelow: "lg", cell: (t) => fmtMoney(t.gross) },
  { key: "c", header: "Charges", className: "text-right", hideBelow: "lg", cell: (t) => fmtMoney(t.charges) },
  { key: "n", header: "Profit / loss (₹)", className: "text-right", cell: (t) => <span className={`font-medium ${colour(t.net)}`}>{fmtMoney(t.net)}</span> },
  { key: "r", header: "Return", className: "text-right", cell: (t) => <span className={colour(t.net)}>{pct(t.return)}</span> },
];

const STOCKS: Column<Stock>[] = [
  { key: "s", header: "Stock", cell: (s) => <span className="font-medium">{s.symbol}</span> },
  { key: "t", header: "Trades", className: "text-right", cell: (s) => s.trades },
  { key: "w", header: "Win rate", className: "text-right", cell: (s) => pct(s.win_rate) },
  { key: "c", header: "Charges (₹)", className: "text-right", hideBelow: "md", cell: (s) => fmtMoney(s.charges) },
  { key: "n", header: "Profit / loss (₹)", className: "text-right", cell: (s) => <span className={`font-medium ${colour(s.net)}`}>{fmtMoney(s.net)}</span> },
];

/** The run beside the index it should beat: same days, the index rebased to the same start amount. */
function IndexComparison({ b, finalAmount }: { b: BacktestReport["benchmark"]; finalAmount: string | null }) {
  if (!b) return null;
  if (b.note || b.return === null) return <Alert tone="warn" title="Not compared with the index">{b.note ?? `${b.name} could not be used.`}</Alert>;
  const rows = [
    { label: "Ended with", run: rs(finalAmount), idx: rs(b.final) },
    { label: "Total return", run: pct(b.strategy_return), idx: pct(b.return) },
    { label: "Worst drop", run: pct(b.strategy_max_drawdown), idx: pct(b.max_drawdown) },
    { label: "Sharpe ratio", run: b.strategy_sharpe ?? "-", idx: b.sharpe ?? "-" },
  ];
  const ahead = Number.parseFloat(b.strategy_return ?? "0") - Number.parseFloat(b.return);
  return (
    <Panel title={`Compared with ${b.name}`}>
      <div className="px-5 py-4">
        <table className="w-full text-sm">
          <caption className="sr-only">This run against the index</caption>
          <thead><tr className="text-xs uppercase tracking-wide text-ink-soft"><th scope="col" className="py-1 text-left font-medium" /><th scope="col" className="py-1 text-right font-medium">This run</th><th scope="col" className="py-1 text-right font-medium">Index</th></tr></thead>
          <tbody className="divide-y divide-line">
            {rows.map((x) => <tr key={x.label}><th scope="row" className="py-2 text-left font-normal">{x.label}</th><td className="py-2 text-right font-medium">{x.run}</td><td className="py-2 text-right">{x.idx}</td></tr>)}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-ink-soft">
          The run is {ahead >= 0 ? "ahead of" : "behind"} the index by {Math.abs(ahead * 100).toFixed(1)} percentage points. The grey line on the chart is the index, started with the same amount.
          Gross index returns include dividends, as the run does.
        </p>
      </div>
    </Panel>
  );
}

/** The "underwater" view: 0% at every new high, below it while the account is under its previous peak. */
function DrawdownChart({ curve }: { curve: BacktestReport["curve"] }) {
  if (curve.length < 2) return <p className="text-sm text-ink-soft">No equity curve was stored for this run.</p>;
  const dd = curve.map((p) => Number.parseFloat(p.drawdown));
  const low = Math.min(...dd, -0.01);
  const W = 1000, H = 160;
  const x = (i: number) => (i / (curve.length - 1)) * W;
  const y = (v: number) => 4 + (v / low) * (H - 8); // 0 at the top, the worst drop at the bottom
  const line = dd.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const worst = dd.indexOf(Math.min(...dd));
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Drawdown over time, worst ${(Math.min(...dd) * 100).toFixed(1)} percent on ${curve[worst]?.date ?? ""}`} className="h-40 w-full">
        <line x1="0" x2={W} y1="4" y2="4" stroke="#cbd5e1" strokeWidth="1" />
        <polygon points={`0,4 ${line} ${W},4`} fill="rgba(220,38,38,0.18)" />
        <polyline points={line} fill="none" stroke="#dc2626" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption className="mt-1 text-xs text-ink-soft">Worst: {(Math.min(...dd) * 100).toFixed(1)}% on {curve[worst]?.date}. The line is at the top when the account is at a new high.</figcaption>
    </figure>
  );
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Profit or loss by exit month: one row per year, green for a gain, red for a loss, deeper for a bigger move. */
function MonthlyCalendar({ months }: { months: BacktestReport["monthly"] }) {
  if (months.length === 0) return <p className="text-sm text-ink-soft">No closed trades yet.</p>;
  const byKey = new Map(months.map((m) => [m.month, m]));
  const years = [...new Set(months.map((m) => m.month.slice(0, 4)))];
  const biggest = Math.max(...months.map((m) => Math.abs(Number.parseFloat(m.net))), 1);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-center text-xs">
        <caption className="sr-only">Profit or loss by month</caption>
        <thead><tr><th className="px-1 py-1" />{MONTHS.map((m) => <th key={m} scope="col" className="px-1 py-1 font-medium text-ink-soft">{m}</th>)}</tr></thead>
        <tbody>
          {years.map((y) => (
            <tr key={y}>
              <th scope="row" className="px-2 py-1 text-left font-medium">{y}</th>
              {MONTHS.map((_, i) => {
                const m = byKey.get(`${y}-${String(i + 1).padStart(2, "0")}`);
                if (!m) return <td key={i} className="px-1 py-1 text-ink-faint">-</td>;
                const v = Number.parseFloat(m.net);
                const a = (0.12 + 0.6 * Math.min(Math.abs(v) / biggest, 1)).toFixed(2);
                return (
                  <td key={i} className="px-1 py-1">
                    <div title={`${m.month}: ${m.trades} trades, ${rs(m.net)}`} className="rounded px-1 py-1.5 font-medium" style={{ background: v < 0 ? `rgba(220,38,38,${a})` : `rgba(5,150,105,${a})` }}>
                      {Math.round(v).toLocaleString("en-IN")}
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-xs text-ink-soft">₹ made or lost by trades that closed in each month, after charges.</p>
    </div>
  );
}

function Bars({ rows, caption }: { rows: { label: string; value: number; shown: string; good?: boolean }[]; caption: string }) {
  const top = Math.max(...rows.map((r) => Math.abs(r.value)), 1);
  return (
    <ul aria-label={caption} className="space-y-1.5">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[7rem_1fr_6rem] items-center gap-2 text-xs">
          <span className="text-ink-soft">{r.label}</span>
          <div className="h-4 rounded bg-slate-100"><div className={`h-4 rounded ${r.good === false ? "bg-red-400" : "bg-emerald-500"}`} style={{ width: `${(Math.abs(r.value) / top) * 100}%` }} /></div>
          <span className="text-right font-medium">{r.shown}</span>
        </li>
      ))}
    </ul>
  );
}

export default function BacktestReportPage() {
  const id = Number(useParams<{ id: string }>().id);
  const q = useQuery({ queryKey: ["backtest-report", id], queryFn: () => api.backtestReport(id), enabled: Number.isFinite(id) });
  const [tab, setTab] = useState<"trades" | "stocks" | "open">("trades");
  const r = q.data;
  const s = r?.summary;
  const h = r?.headline;
  const crumbs = [{ label: "Backtests", href: "/research/backtests" }, { label: `Run #${id}` }];
  if (q.isError) return <div><PageHeader title={`Run #${id}`} breadcrumbs={crumbs} /><Alert tone="error">Could not load this run.</Alert></div>;
  if (!r || !s || !h) return <div><PageHeader title={`Run #${id}`} breadcrumbs={crumbs} /><Skeleton className="h-32 w-full" /></div>;
  return (
    <div className="space-y-6">
      <PageHeader title={`${r.strategy_id} v${r.strategy_version}`} subtitle={`Run #${r.run_id}${r.label ? ` (${r.label})` : ""} · ${r.start ?? "?"} to ${r.end ?? "?"}`} breadcrumbs={crumbs} />

      {r.study ? (
        <Alert tone="warn" title="Read with the study's limits in mind">
          This run belongs to <Link href={`/research/studies/${r.study.experiment_id}`} className="text-brand hover:underline">{r.study.name}</Link>. Prices exist only for stocks still listed today, so stocks that were delisted or merged away are missing from the past (survivorship bias flatters the result).
        </Alert>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Started with" value={rs(h.initial)} />
        <StatCard label="Ended with" value={rs(h.final)} hint="Cash plus open positions at market" tone={tone(h.change)} />
        <StatCard label="Total profit / loss" value={rs(h.change)} hint={`${pct(h.return)} on the start amount, after charges`} tone={tone(h.change)} />
        <StatCard label="Profit before charges" value={h.change === null || h.charges === null ? "-" : rs((Number.parseFloat(h.change) + Number.parseFloat(h.charges)).toFixed(2))} hint="Total profit plus charges paid" />
        <StatCard label="Worst drop" value={pct(h.max_drawdown)} hint="Peak to trough" tone="warn" />
        <StatCard label="Closed trades" value={s.trades} hint={`${s.wins} won · ${s.losses} lost`} />
        <StatCard label="Win rate" value={pct(s.win_rate)} />
        <StatCard label="Profit factor" value={s.profit_factor ?? "-"} hint="Money won per ₹1 lost" />
        <StatCard label="Charges paid" value={rs(h.charges)} tone={Number.parseFloat(s.cost_drag ?? "0") > 0.3 ? "warn" : undefined}
          hint={s.cost_drag === null ? `Average hold ${s.avg_holding_days ?? "-"} days` : `Already taken out of the profit · ${pct(s.cost_drag)} of the profit before charges · average hold ${s.avg_holding_days ?? "-"} days`} />
      </div>

      <Panel title="Account value over time">
        <div className="px-5 py-4">
          {r.curve.length > 1 ? <LineChart points={r.curve.map((p) => ({ date: p.date, level: p.equity }))} compare={r.benchmark?.curve} /> : <p className="text-sm text-ink-soft">No equity curve was stored for this run.</p>}
          <p className="mt-2 text-xs text-ink-soft">Closed trades made {rs(s.net_pnl)} after charges (average win {rs(s.avg_win)}, average loss {rs(s.avg_loss)}). The total above adds {rs(h.dividends)} of dividends and the gain on shares still held (less what it cost to buy them), so the two differ. Charges paid is for the whole run, including those held shares.</p>
        </div>
      </Panel>

      <Panel title="How far below its peak the account was">
        <div className="px-5 py-4"><DrawdownChart curve={r.curve} /></div>
      </Panel>

      <IndexComparison b={r.benchmark} finalAmount={h.final} />

      <Panel title="Profit and loss by month">
        <div className="px-5 py-4"><MonthlyCalendar months={r.monthly} /></div>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="How big were the wins and losses?">
          <div className="px-5 py-4">
            <Bars caption="Trades by return" rows={r.distribution.map((d) => ({ label: d.label, value: d.count, shown: `${d.count} trades`, good: !d.label.startsWith("below") && !d.label.startsWith("-") }))} />
            <p className="mt-2 text-xs text-ink-soft">Each bar counts closed trades by their return after charges.</p>
          </div>
        </Panel>
        <Panel title="Which weekday do trades close on?">
          <div className="px-5 py-4">
            <Bars caption="Profit or loss by weekday" rows={r.by_weekday.map((d) => ({ label: `${d.weekday} · ${d.trades}`, value: Number.parseFloat(d.net), shown: `₹${fmtMoney(d.net, 0)}`, good: !d.net.startsWith("-") }))} />
            <p className="mt-2 text-xs text-ink-soft">Net ₹ by the day of the week the trade was sold, with the trade count.</p>
          </div>
        </Panel>
      </div>

      <Panel>
        <div className="px-5 pt-3">
          <Tabs label="Report sections" value={tab} onChange={setTab} tabs={[
            { key: "trades", label: "Every trade", count: r.round_trips.length },
            { key: "stocks", label: "By stock", count: r.by_stock.length },
            { key: "open", label: "Still held", count: r.open_positions.length },
          ]} />
        </div>
        {tab === "trades" ? <DataTable caption="Closed trades" columns={TRIPS} rows={r.round_trips} rowKey={(t) => `${t.instrument_id}-${t.entry_day}-${t.exit_day}-${t.qty}`}
          empty={<EmptyState icon="info" title="No closed trades">This run bought nothing, or sold nothing yet.</EmptyState>} /> : null}
        {tab === "stocks" ? <DataTable caption="Results by stock" columns={STOCKS} rows={[...r.by_stock].sort((a, b) => Number.parseFloat(b.net) - Number.parseFloat(a.net))} rowKey={(x) => x.symbol}
          empty={<EmptyState icon="info" title="No closed trades" />} /> : null}
        {tab === "open" ? <DataTable caption="Positions still held at the end" columns={[
          { key: "s", header: "Stock", cell: (o) => <span className="font-medium">{o.symbol}</span> },
          { key: "q", header: "Qty", className: "text-right", cell: (o) => o.qty },
          { key: "l", header: "Buys", className: "text-right", cell: (o) => o.lots },
          { key: "d", header: "First bought", cell: (o) => o.entry_day },
          { key: "p", header: "Average price", className: "text-right", cell: (o) => fmtMoney(o.entry_price) },
        ]} rows={r.open_positions} rowKey={(o) => String(o.instrument_id)} empty={<EmptyState icon="info" title="Nothing held at the end" />} /> : null}
      </Panel>
    </div>
  );
}
