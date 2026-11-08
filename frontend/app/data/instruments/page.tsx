"use client";

import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useMemo, useState } from "react";
import { PriceChart } from "@/components/charts/PriceChart";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/status/Badge";
import { Card, ErrorBox, Loading, Stat } from "@/components/status/LoadState";
import { DataTable } from "@/components/tables/DataTable";
import { api } from "@/lib/api/client";
import { shortHash } from "@/lib/formatting";
import type { Adjust, InstrumentDetail } from "@/lib/schemas";

const MODES: { value: Adjust; label: string; blurb: string }[] = [
  { value: "none", label: "Raw (as traded)", blurb: "exactly as traded; no adjustment" },
  { value: "split", label: "Split/bonus adjusted", blurb: "splits, bonuses and similar price events; no dividends" },
  { value: "total_return", label: "Total-return adjusted", blurb: "split/bonus adjusted and dividends folded in" },
];

type Action = InstrumentDetail["actions"][number];

const ACTION_COLUMNS: ColumnDef<Action, unknown>[] = [
  { header: "Ex-date", accessorKey: "ex_date" },
  { header: "Kind", accessorKey: "kind" },
  {
    header: "Status",
    accessorKey: "status",
    cell: ({ getValue }) => {
      const s = String(getValue());
      return <Badge tone={s === "ok" ? "good" : "warn"}>{s === "ok" ? "verified" : s}</Badge>;
    },
  },
  { header: "Amount / share ratio", cell: ({ row }) => (row.original.amount ? `₹${row.original.amount} per share` : row.original.num ? `${row.original.num}:${row.original.den} (shares after : before)` : "-") },
  { header: "Subject", accessorKey: "subject", cell: ({ getValue }) => <span className="text-xs text-ink-soft">{String(getValue() ?? "")}</span> },
];

export default function InstrumentsPage() {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(true); // the suggestion list: closed once an instrument is picked
  const [id, setId] = useState<number | null>(null);
  const [adjust, setAdjust] = useState<Adjust>("none");
  const [start, setStart] = useState("2024-01-01");
  const [end, setEnd] = useState("2024-12-31");

  const search = useQuery({ queryKey: ["search", q], queryFn: () => api.searchInstruments(q), enabled: q.trim().length >= 1 });
  const detail = useQuery({ queryKey: ["instrument", id], queryFn: () => api.instrument(id as number), enabled: id !== null });
  const bars = useQuery({
    queryKey: ["bars", id, start, end, adjust],
    queryFn: () => api.bars(id as number, start, end, adjust),
    enabled: id !== null && start <= end,
  });
  const actions = useMemo(() => detail.data?.actions ?? [], [detail.data]);
  const mode = MODES.find((m) => m.value === adjust) ?? MODES[0];

  return (
    <div className="space-y-6">
      <PageHeader title="Data Explorer" subtitle="Daily bars from the backend bar reader. Adjustment happens there, never in the browser." />

      <Card title="Find an instrument">
        <label className="block text-xs text-ink-soft" htmlFor="q">
          Symbol, ISIN or name
        </label>
        <input id="q" value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => { if (q.trim()) setOpen(true); }} placeholder="RELIANCE or INE002A01018" className="mt-1 w-full max-w-md rounded-md border border-line px-3 py-2 text-sm" />
        {open && search.isLoading && q ? <Loading what="matches" /> : null}
        {search.error ? <ErrorBox error={search.error} what="the search" /> : null}
        {open && search.data ? (
          <ul className="mt-3 divide-y divide-line rounded-md border border-line" aria-label="Matches">
            {search.data.length === 0 ? <li className="p-3 text-sm text-ink-soft">No instrument matches.</li> : null}
            {search.data.map((i) => (
              <li key={i.id}>
                <button type="button" onClick={() => { setId(i.id); setQ(i.symbol); setOpen(false); }} className="flex w-full items-center justify-between gap-3 p-3 text-left text-sm hover:bg-slate-50">
                  <span>
                    <span className="font-medium">{i.symbol}</span> <span className="text-ink-soft">{i.name}</span>
                  </span>
                  <span className="flex items-center gap-2 text-xs text-ink-soft">
                    {i.isin}
                    <Badge tone={i.status === "active" ? "good" : "neutral"}>{i.status}</Badge>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </Card>

      {id === null ? null : detail.isLoading ? (
        <Loading what="instrument" />
      ) : detail.error || !detail.data ? (
        <ErrorBox error={detail.error} what="the instrument" />
      ) : (
        <>
          <Card title={`${detail.data.symbol} - ${detail.data.name ?? ""}`}>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <Stat label="ISIN" value={detail.data.isin ?? "-"} />
              <Stat label="First bar" value={detail.data.bars.first ?? "-"} />
              <Stat label="Last bar" value={detail.data.bars.last ?? "-"} />
              <Stat label="Bars" value={detail.data.bars.count} />
            </div>
          </Card>

          <Card title="Price history">
            <div className="mb-3 flex flex-wrap items-end gap-3">
              <div>
                <label htmlFor="adjust" className="block text-xs text-ink-soft">
                  Price basis
                </label>
                <select id="adjust" value={adjust} onChange={(e) => setAdjust(e.target.value as Adjust)} className="rounded-md border border-line px-2 py-2 text-sm">
                  {MODES.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label htmlFor="start" className="block text-xs text-ink-soft">
                  From
                </label>
                <input id="start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className="rounded-md border border-line px-2 py-2 text-sm" />
              </div>
              <div>
                <label htmlFor="end" className="block text-xs text-ink-soft">
                  To
                </label>
                <input id="end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} className="rounded-md border border-line px-2 py-2 text-sm" />
              </div>
              <Badge tone={adjust === "none" ? "neutral" : "good"}>{mode?.label}</Badge>
            </div>
            <p className="mb-3 text-xs text-ink-soft">{mode?.blurb}</p>
            {start > end ? <p className="text-sm text-red-700">The start date is after the end date.</p> : null}
            {bars.isLoading ? <Loading what="bars" /> : null}
            {bars.error ? <ErrorBox error={bars.error} what="bars" /> : null}
            {bars.data ? (
              <>
                {bars.data.bars.length === 0 ? <p className="text-sm text-ink-soft">No bars in this range.</p> : <PriceChart bars={bars.data.bars} actions={actions} instrumentId={detail.data.id} adjust={adjust} />}
                <div className="mt-3 flex flex-wrap gap-2 text-xs">
                  <Badge tone="neutral">basis: {mode?.label}</Badge>
                  <Badge tone="neutral">adjustment version {shortHash(bars.data.adjustment_version, 16)}</Badge>
                  <Badge tone={bars.data.clean ? "good" : "warn"}>{bars.data.clean ? "no unpriced or provisional events" : "data-quality warnings"}</Badge>
                </div>
                {bars.data.unapplied.length > 0 ? (
                  <p className="mt-2 text-sm text-amber-800" role="alert">
                    Unpriced actions affect these prices: {bars.data.unapplied.map((a) => `${a.kind} ${a.ex_date}`).join(", ")}.
                  </p>
                ) : null}
                {bars.data.provisional.length > 0 ? (
                  <p className="mt-2 text-sm text-amber-800" role="alert">
                    Provisional (unverified) adjustments applied: {bars.data.provisional.map((a) => `${a.kind} ${a.ex_date}`).join(", ")}.
                  </p>
                ) : null}
              </>
            ) : null}
          </Card>

          <Card title="Corporate actions" note="Markers on the chart: blue = verified, amber = under review.">
            <div className="max-h-96 overflow-y-auto">
              <DataTable data={actions} columns={ACTION_COLUMNS} empty="No corporate actions recorded." />
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

