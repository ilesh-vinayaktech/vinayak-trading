"use client";

import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import {
  ChartWorkspace,
  BASES,
  presetStart,
} from "@/components/charts/ChartWorkspace";
import { FundamentalsPanel } from "@/components/fundamentals/FundamentalsPanel";
import { SmartMoneyPanel } from "@/components/market/SmartMoneyPanel";
import { LevelsPanel } from "@/components/market/LevelsPanel";
import { ScorePanel } from "@/components/market/ScorePanel";
import { PageHeader } from "@/components/layout/PageHeader";
import type { LiveView, Mark } from "@/components/charts/PriceChart";
import { useAuth } from "@/lib/auth";
import { Badge } from "@/components/status/Badge";
import { Card, Stat } from "@/components/status/LoadState";
import { DecisionList } from "@/components/charts/DecisionList";
import { DataTable } from "@/components/tables/DataTable";
import { api } from "@/lib/api/client";
import { shortHash } from "@/lib/formatting";
import type {
  Adjust,
  Instrument,
  InstrumentDetail,
  Timeframe,
} from "@/lib/schemas";
import { type Cadence, cadenceFits, intradayStart, isIntraday, latestDay } from "@/lib/timeframes";

type Action = InstrumentDetail["actions"][number];

const ACTION_COLUMNS: ColumnDef<Action, unknown>[] = [
  { header: "Ex-date", accessorKey: "ex_date" },
  { header: "Kind", accessorKey: "kind" },
  {
    header: "Status",
    accessorKey: "status",
    cell: ({ getValue }) => {
      const s = String(getValue());
      return (
        <Badge tone={s === "ok" ? "good" : "warn"}>
          {s === "ok" ? "verified" : s}
        </Badge>
      );
    },
  },
  {
    header: "Amount / share ratio",
    cell: ({ row }) =>
      row.original.amount
        ? `₹${row.original.amount} per share`
        : row.original.num
          ? `${row.original.num}:${row.original.den} (shares after : before)`
          : "-",
  },
  {
    header: "Subject",
    accessorKey: "subject",
    cell: ({ getValue }) => (
      <span className="text-xs text-ink-soft">{String(getValue() ?? "")}</span>
    ),
  },
];

function Explorer() {
  const raw = useSearchParams().get("id"); // deep link, e.g. from the screener
  const linked = raw !== null && /^\d+$/.test(raw) ? Number(raw) : null;
  const { can } = useAuth();
  const [strategyId, setStrategyId] = useState("");
  const [picked, setPicked] = useState<Instrument | null>(null);
  const [adjust, setAdjust] = useState<Adjust>("none");
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [range, setRange] = useState<{
    id: number | null;
    start: string;
    end: string;
  }>({ id: null, start: "", end: "" });
  const id = picked?.id ?? linked;

  const detail = useQuery({
    queryKey: ["instrument", id],
    queryFn: () => api.instrument(id as number),
    enabled: id !== null,
  });
  // each newly opened instrument starts on its last year of data
  useEffect(() => {
    const d = detail.data;
    if (d && d.id === id && range.id !== d.id && d.bars.last)
      setRange({
        id: d.id,
        start: presetStart(d.bars.last, d.bars.first, 12),
        end: d.bars.last,
      });
  }, [detail.data, id, range.id]);
  const ready = range.id === id && id !== null;
  // a chosen strategy runs on the open stock over the chart's own date range; its decisions are drawn on the chart
  const saved = useQuery({
    queryKey: ["strategies"],
    queryFn: api.strategies,
    enabled: can("strategy:own"),
  });
  const strategies = saved.data?.strategies ?? [];
  // the generated strategy definitions are offered too, as "def:ID:VERSION"; they are drawn over the chart's own range, to the latest bar
  const defs = useQuery({
    queryKey: ["intel", "definitions"],
    queryFn: api.intelDefinitions,
    enabled: can("strategy:own"),
  });
  // a strategy is offered on a candle at least as long as its own rebalance period: saved strategies decide daily; a definition decides daily, weekly or monthly
  const offered = [
    ...strategies.map((s) => ({ id: s.config_id, name: s.name, cadence: "DAILY" as Cadence })),
    ...(defs.data?.definitions ?? []).map((d) => ({
      id: `def:${d.strategy_id}:${d.version}`,
      name: `Definition: ${d.strategy_id}`,
      cadence: d.rebalance as Cadence,
    })),
  ].filter((o) => cadenceFits(timeframe, o.cadence));
  const chosen = offered.some((o) => o.id === strategyId) ? strategyId : "";
  const signals = useQuery({
    queryKey: ["signals", chosen, id, range.start, range.end],
    queryFn: () => {
      if (chosen.startsWith("def:")) {
        const [, sid = "", version = "1"] = chosen.split(":");
        return api.definitionSignals(sid, Number(version), {
          instrument_id: id as number,
          start: range.start,
          end: range.end,
        });
      }
      return api.strategySignals(chosen, {
        instrument_id: id as number,
        start: range.start,
        end: range.end,
        holding: false,
      });
    },
    enabled:
      chosen !== "" && ready && range.start <= range.end && !isIntraday(timeframe),
  });
  // the live price: polled every 2 s while the chart reaches the latest day, on every timeframe; the server builds the
  // candle still forming (today, this week, this month, or the current N-minute bar) and the chart moves it in place
  const lastDay = detail.data?.bars.last ?? "";
  const atLatest =
    lastDay !== "" &&
    range.end >= (isIntraday(timeframe) ? latestDay(lastDay) : lastDay);
  const liveQ = useQuery({
    queryKey: ["live", id, timeframe, adjust],
    queryFn: () => api.live(id as number, timeframe, adjust),
    enabled: ready && atLatest,
    refetchInterval: 2000,
    refetchIntervalInBackground: false, // a hidden tab does not poll
  });
  const liveView = useMemo<LiveView | null>(() => {
    const d = liveQ.data;
    return d?.candle
      ? {
          candle: d.candle,
          prevClose: d.quote?.prev_close ?? null,
          live: d.live,
        }
      : null;
  }, [liveQ.data]);
  const [, defId = "", defVersion = ""] = chosen.startsWith("def:") ? chosen.split(":") : [];
  const plain = defs.data?.definitions.find((d) => d.strategy_id === defId && String(d.version) === defVersion)?.plain;
  const marks = useMemo<Mark[]>(
    () =>
      (signals.data?.days ?? []).flatMap((d) =>
        d.action ? [{ day: d.day, action: d.action, reason: d.reason, plain }] : [],
      ),
    [signals.data, plain],
  );
  const buys = marks.filter((m) => m.action === "BUY").length;
  const strategyStatus =
    chosen === "" || isIntraday(timeframe)
      ? null
      : signals.isError
        ? "Could not run"
        : signals.isFetching || !signals.data
          ? "Running..."
          : `${buys} buy, ${marks.length - buys} sell`;
  // a chosen benchmark's levels are drawn over the stock (daily and longer timeframes), cut to the chart's own range
  const [benchId, setBenchId] = useState("");
  const benchList = useQuery({ queryKey: ["benchmarks"], queryFn: api.benchmarks });
  const bench = benchList.data?.benchmarks.find((b) => String(b.id) === benchId);
  const benchOn = !!bench && ready && !isIntraday(timeframe);
  const benchLevels = useQuery({
    queryKey: ["benchmark-levels", benchId, range.start],
    queryFn: () => api.benchmarkLevels(Number(benchId), range.start, 5000),
    enabled: benchOn,
  });
  const benchPoints = useMemo(
    () => (benchOn ? (benchLevels.data?.levels ?? []).filter((p) => p.date >= range.start && p.date <= range.end) : []),
    [benchOn, benchLevels.data, range.start, range.end],
  );
  const benchStatus = !benchOn
    ? null
    : benchLevels.isError
      ? "Could not load"
      : benchLevels.isFetching
        ? "Loading..."
        : benchPoints.length === 0
          ? "No data in this range"
          : null;
  const bars = useQuery({
    queryKey: ["bars", id, range.start, range.end, adjust, timeframe],
    queryFn: () =>
      api.bars(id as number, range.start, range.end, adjust, timeframe),
    enabled: ready && range.start <= range.end,
  });
  const pickTimeframe = (t: Timeframe) => {
    setTimeframe(t);
    const last = detail.data?.bars.last ?? null;
    if (!last) return;
    if (isIntraday(t)) {
      if (adjust === "total_return") setAdjust("split"); // minutes carry no dividend basis
      const end = latestDay(last); // today's minutes come from the live feed
      setRange((r) => ({ ...r, start: intradayStart(end, t), end }));
    } else {
      const months = t === "1mo" ? 0 : t === "1w" ? 60 : 12; // monthly: all history; weekly: 5 years; daily: 1 year
      setRange((r) => ({
        ...r,
        start: presetStart(last, detail.data?.bars.first ?? null, months),
        end: last,
      }));
    }
  };
  const actions = useMemo(() => detail.data?.actions ?? [], [detail.data]);
  const upcoming = useMemo(() => detail.data?.upcoming ?? [], [detail.data]);
  const actionsNewestFirst = useMemo(() => [...actions].reverse(), [actions]); // the API sends oldest first; the chart markers keep that order
  const mode = BASES.find((m) => m.value === adjust) ?? BASES[0];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Data Explorer"
        subtitle="Bars from the backend bar reader; intraday timeframes are built from stored 1-minute bars. Adjustment happens there, never in the browser."
      />

      <ChartWorkspace
        picked={picked ?? (detail.data?.id === id ? detail.data : null)}
        onPick={(i) => {
          setPicked(i);
          setRange({ id: null, start: "", end: "" });
        }}
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
        signals={marks}
        live={liveView}
        benchmark={{
          options: (benchList.data?.benchmarks ?? []).map((b) => ({ id: String(b.id), name: b.name })),
          value: benchId,
          onChange: setBenchId,
          status: benchStatus,
          name: bench?.name ?? "",
          points: benchPoints,
        }}
        strategy={{
          options: offered.map((o) => ({ id: o.id, name: o.name })),
          value: chosen,
          onChange: setStrategyId,
          status: strategyStatus,
        }}
      />

      {chosen !== "" && signals.data && !isIntraday(timeframe) ? (
        <DecisionList days={signals.data.days} name={signals.data.strategy} />
      ) : null}

      {bars.data ? (
        <div
          className="flex flex-wrap items-center gap-2 text-xs"
          data-testid="quality-strip"
        >
          <Badge tone="neutral">basis: {mode?.label}</Badge>
          {bars.data.source ? (
            <Badge tone="neutral">
              prices:{" "}
              {bars.data.source === "kite" ? "Kite candles" : "NSE bhavcopy"}
            </Badge>
          ) : null}
          <Badge tone="neutral">
            adjustment version {shortHash(bars.data.adjustment_version, 16)}
          </Badge>
          <Badge tone={bars.data.clean ? "good" : "warn"}>
            {bars.data.clean
              ? "no unpriced or provisional events"
              : "data-quality warnings"}
          </Badge>
          <span className="text-ink-soft">{mode?.blurb}</span>
        </div>
      ) : null}
      {bars.data && bars.data.unapplied.length > 0 ? (
        <p className="text-sm text-amber-800" role="alert">
          Unpriced actions affect these prices:{" "}
          {bars.data.unapplied.map((a) => `${a.kind} ${a.ex_date}`).join(", ")}.
        </p>
      ) : null}
      {bars.data && bars.data.provisional.length > 0 ? (
        <p className="text-sm text-amber-800" role="alert">
          Provisional (unverified) adjustments applied:{" "}
          {bars.data.provisional
            .map((a) => `${a.kind} ${a.ex_date}`)
            .join(", ")}
          .
        </p>
      ) : null}

      {detail.data ? (
        <FundamentalsPanel
          key={detail.data.id}
          instrumentId={detail.data.id}
          symbol={detail.data.symbol}
        />
      ) : null}

      {detail.data ? <SmartMoneyPanel key={`sm-${detail.data.id}`} instrumentId={detail.data.id} /> : null}

      {detail.data ? <ScorePanel key={`sc-${detail.data.symbol}`} symbol={detail.data.symbol} /> : null}

      {detail.data ? <LevelsPanel key={`lv-${detail.data.symbol}`} symbol={detail.data.symbol} /> : null}

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
          {upcoming.length > 0 ? (
            <Card
              title="Coming up"
              note="Announced by the company, not applied to prices until the ex-date. Dates can still be revised."
            >
              <DataTable data={upcoming} columns={ACTION_COLUMNS} empty="" />
            </Card>
          ) : null}
          <Card
            title="Corporate actions"
            note="Markers on the chart: blue = verified, amber = under review."
          >
            <div data-testid="actions-scroll" tabIndex={0} className="max-h-96 overflow-y-auto rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand/40">
              <DataTable
                data={actionsNewestFirst}
                columns={ACTION_COLUMNS}
                empty="No corporate actions recorded."
              />
            </div>
            {actions.length > 0 ? (
              <p className="mt-2 text-xs text-ink-soft">
                {actions.length} {actions.length === 1 ? "action" : "actions"}, newest first.
              </p>
            ) : null}
          </Card>
        </>
      ) : null}
    </div>
  );
}

export default function InstrumentsPage() {
  return (
    <Suspense fallback={null}>
      <Explorer />
    </Suspense>
  );
}
