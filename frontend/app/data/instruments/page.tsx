"use client";

import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";
import { ChartWorkspace, BASES, presetStart } from "@/components/charts/ChartWorkspace";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/status/Badge";
import { Card, Stat } from "@/components/status/LoadState";
import { DataTable } from "@/components/tables/DataTable";
import { api } from "@/lib/api/client";
import { shortHash } from "@/lib/formatting";
import type { Adjust, Instrument, InstrumentDetail, Timeframe } from "@/lib/schemas";
import { intradayStart, isIntraday } from "@/lib/timeframes";

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
  const [picked, setPicked] = useState<Instrument | null>(null);
  const [adjust, setAdjust] = useState<Adjust>("none");
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [range, setRange] = useState<{ id: number | null; start: string; end: string }>({ id: null, start: "", end: "" });
  const id = picked?.id ?? null;

  const detail = useQuery({ queryKey: ["instrument", id], queryFn: () => api.instrument(id as number), enabled: id !== null });
  // each newly opened instrument starts on its last year of data
  useEffect(() => {
    const d = detail.data;
    if (d && d.id === id && range.id !== d.id && d.bars.last) setRange({ id: d.id, start: presetStart(d.bars.last, d.bars.first, 12), end: d.bars.last });
  }, [detail.data, id, range.id]);
  const ready = range.id === id && id !== null;
  const bars = useQuery({
    queryKey: ["bars", id, range.start, range.end, adjust, timeframe],
    queryFn: () => api.bars(id as number, range.start, range.end, adjust, timeframe),
    enabled: ready && range.start <= range.end,
  });
  const pickTimeframe = (t: Timeframe) => {
    setTimeframe(t);
    const last = detail.data?.bars.last ?? null;
    if (!last) return;
    if (isIntraday(t)) {
      if (adjust === "total_return") setAdjust("split"); // minutes carry no dividend basis
      setRange((r) => ({ ...r, start: intradayStart(last, t), end: last }));
    } else {
      const months = t === "1mo" ? 0 : t === "1w" ? 60 : 12; // monthly: all history; weekly: 5 years; daily: 1 year
      setRange((r) => ({ ...r, start: presetStart(last, detail.data?.bars.first ?? null, months), end: last }));
    }
  };
  const actions = useMemo(() => detail.data?.actions ?? [], [detail.data]);
  const mode = BASES.find((m) => m.value === adjust) ?? BASES[0];

  return (
    <div className="space-y-4">
      <PageHeader title="Data Explorer" subtitle="Bars from the backend bar reader; intraday timeframes are built from stored 1-minute bars. Adjustment happens there, never in the browser." />

      <ChartWorkspace
        picked={picked}
        onPick={(i) => { setPicked(i); setRange({ id: null, start: "", end: "" }); }}
        instrument={detail.data ?? null}
        adjust={adjust}
        onAdjust={setAdjust}
        timeframe={timeframe}
        onTimeframe={pickTimeframe}
        start={range.start}
        end={range.end}
        onRange={(s, e) => setRange((r) => ({ ...r, start: s, end: e }))}
        bars={bars.data}
        loading={id !== null && (detail.isLoading || bars.isLoading || !ready)}
        error={detail.error ?? bars.error}
      />

      {bars.data ? (
        <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="quality-strip">
          <Badge tone="neutral">basis: {mode?.label}</Badge>
          <Badge tone="neutral">adjustment version {shortHash(bars.data.adjustment_version, 16)}</Badge>
          <Badge tone={bars.data.clean ? "good" : "warn"}>{bars.data.clean ? "no unpriced or provisional events" : "data-quality warnings"}</Badge>
          <span className="text-ink-soft">{mode?.blurb}</span>
        </div>
      ) : null}
      {bars.data && bars.data.unapplied.length > 0 ? (
        <p className="text-sm text-amber-800" role="alert">
          Unpriced actions affect these prices: {bars.data.unapplied.map((a) => `${a.kind} ${a.ex_date}`).join(", ")}.
        </p>
      ) : null}
      {bars.data && bars.data.provisional.length > 0 ? (
        <p className="text-sm text-amber-800" role="alert">
          Provisional (unverified) adjustments applied: {bars.data.provisional.map((a) => `${a.kind} ${a.ex_date}`).join(", ")}.
        </p>
      ) : null}

      {detail.data ? (
        <>
          <Card title={`${detail.data.symbol} - ${detail.data.name ?? ""}`}>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <Stat label="ISIN" value={detail.data.isin ?? "-"} />
              <Stat label="First bar" value={detail.data.bars.first ?? "-"} />
              <Stat label="Last bar" value={detail.data.bars.last ?? "-"} />
              <Stat label="Bars" value={detail.data.bars.count} />
            </div>
          </Card>
          <Card title="Corporate actions" note="Markers on the chart: blue = verified, amber = under review.">
            <div className="max-h-96 overflow-y-auto">
              <DataTable data={actions} columns={ACTION_COLUMNS} empty="No corporate actions recorded." />
            </div>
          </Card>
        </>
      ) : null}
    </div>
  );
}
