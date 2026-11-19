"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ErrorBox, Loading } from "@/components/status/LoadState";
import { api } from "@/lib/api/client";
import type { Timeframe } from "@/lib/schemas";
import { INTRADAY_MAX_DAYS, INTRADAY_PRESETS, isIntraday, shiftDays } from "@/lib/timeframes";
import { presetStart } from "./ChartWorkspace";
import { Icon, type IconName } from "./icons";
import { PriceChart, type ChartApi, type ChartType, type IndicatorControls } from "./PriceChart";
import { TimeframeMenu } from "./TimeframeMenu";

const NO_INDICATORS: IndicatorControls = { active: [], data: undefined, catalog: [], onToggle: () => {}, onRemove: () => {}, onEdit: () => {} };
const TYPES: { key: ChartType; label: string; icon: IconName }[] = [
  { key: "candles", label: "Candles", icon: "candles" },
  { key: "line", label: "Line", icon: "line" },
  { key: "area", label: "Area", icon: "area" },
];
const PRESETS = [{ key: "1M", months: 1 }, { key: "3M", months: 3 }, { key: "6M", months: 6 }, { key: "1Y", months: 12 }, { key: "5Y", months: 60 }, { key: "Max", months: 0 }] as const;
const tbBtn = (active = false) => `flex h-8 items-center justify-center gap-1.5 rounded-md px-2 text-[13px] transition-colors ${active ? "bg-blue-50 text-blue-700" : "text-slate-700 hover:bg-slate-100"} disabled:opacity-40`;
const Sep = () => <span className="mx-1 h-5 w-px bg-line" aria-hidden="true" />;
const NO_API: ChartApi = { undo: () => {}, redo: () => {}, canUndo: false, canRedo: false, count: 0, listOpen: false, toggleList: () => {}, screenshot: () => {} };

/**
 * The candlestick chart of one index, the same chart and drawing tools as an instrument's: daily, weekly and monthly from the Kite daily candles (some back to 1990), intraday from the minutes the live feed
 * stores (so intraday history starts the day the feed first followed the index). Indexes have no volume, no corporate actions and no price basis: those controls are not offered. Reloaded every
 * 15 seconds on an intraday timeframe and every minute otherwise, so a forming session keeps moving.
 */
export function IndexChart({ symbol }: { symbol: string }) {
  const box = useRef<HTMLDivElement>(null);
  const [timeframe, setTimeframe] = useState<Timeframe>("1d");
  const [chartType, setChartType] = useState<ChartType>("candles");
  const [range, setRange] = useState<{ start?: string; end?: string }>({});
  const [full, setFull] = useState(false);
  const [rangeOpen, setRangeOpen] = useState(false);
  const intraday = isIntraday(timeframe);
  const q = useQuery({
    queryKey: ["market", "index-bars", symbol, timeframe, range.start ?? "", range.end ?? ""],
    queryFn: () => api.indexBars({ symbol, timeframe, start: range.start, end: range.end }),
    refetchInterval: intraday ? 15_000 : 60_000,
    refetchIntervalInBackground: false, // a hidden tab does not poll
    placeholderData: (prev) => prev, // keep the candles while a timeframe or range loads
    retry: false,
  });
  useEffect(() => {
    const on = () => setFull(document.fullscreenElement === box.current);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);
  const d = q.data;
  const first = d?.first ?? null, last = d?.last ?? null;
  const newest = d?.bars.length ? (d.bars[d.bars.length - 1]?.date ?? null) : null;
  const pickTimeframe = (t: Timeframe) => {
    setTimeframe(t);
    setRange({}); // each timeframe opens on the span the server chooses (a year of days, five days of minutes)
  };
  // panning or zooming out past the first loaded candle: load the same span again further back, never before the first candle (daily and longer only)
  const extend = () => {
    if (intraday || !first || !d?.bars.length) return;
    const from = range.start ?? d.bars[0]?.date ?? "";
    if (!from || from <= first) return;
    const span = Math.max(30, Math.round((Date.parse(range.end ?? last ?? from) - Date.parse(from)) / 86_400_000));
    const earlier = shiftDays(from, -span);
    setRange({ start: earlier < first ? first : earlier, end: range.end });
  };
  const presets = intraday
    ? [...INTRADAY_PRESETS.filter((p) => p.days < INTRADAY_MAX_DAYS[timeframe]).map((p) => ({ key: p.key, from: (l: string) => shiftDays(l, -p.days) })), { key: "Max", from: (l: string) => shiftDays(l, -INTRADAY_MAX_DAYS[timeframe]) }]
    : PRESETS.map((p) => ({ key: p.key, from: (l: string) => presetStart(l, first, p.months) }));
  const edge = intraday ? (newest ?? last) : last;

  const topbar = (chart: ChartApi): ReactNode => (
    <div className="flex flex-wrap items-center gap-0.5 border-b border-line bg-white px-2 py-1" role="toolbar" aria-label="Chart controls">
      <span className="px-2 text-[13px] font-semibold text-slate-900">{symbol}</span>
      <Sep />
      <TimeframeMenu value={timeframe} onChange={pickTimeframe} className={tbBtn(false)} />
      <Sep />
      <div className="flex items-center" role="group" aria-label="Chart type">
        {TYPES.map((t) => (
          <button key={t.key} type="button" title={t.label} aria-label={t.label} aria-pressed={chartType === t.key} onClick={() => setChartType(t.key)} className={tbBtn(chartType === t.key)}>
            <Icon name={t.icon} size={18} />
          </button>
        ))}
      </div>
      <Sep />
      <div className="flex items-center" role="group" aria-label="Date range">
        {presets.map((p) => (
          <button key={p.key} type="button" disabled={!edge} onClick={() => edge && setRange({ start: p.from(edge), end: edge })} className={tbBtn(false)}>
            {p.key}
          </button>
        ))}
        <div className="relative">
          <button type="button" aria-label="Custom range" aria-expanded={rangeOpen} onClick={() => setRangeOpen((v) => !v)} className={tbBtn(rangeOpen)}>
            <Icon name="chevron" size={16} />
          </button>
          {rangeOpen ? (
            <div className="absolute left-0 top-full z-50 mt-1 flex items-end gap-3 rounded-lg border border-line bg-white p-3 shadow-xl">
              <div>
                <label htmlFor="index-start" className="block text-[11px] text-slate-500">From</label>
                <input id="index-start" type="date" value={range.start ?? d?.bars[0]?.date ?? ""} onChange={(e) => setRange({ start: e.target.value, end: range.end })} className="rounded border border-line px-2 py-1 text-sm" />
              </div>
              <div>
                <label htmlFor="index-end" className="block text-[11px] text-slate-500">To</label>
                <input id="index-end" type="date" value={range.end ?? newest ?? ""} onChange={(e) => setRange({ start: range.start, end: e.target.value })} className="rounded border border-line px-2 py-1 text-sm" />
              </div>
            </div>
          ) : null}
        </div>
      </div>
      <span className="flex-1" />
      <button type="button" title="Undo (Ctrl+Z)" aria-label="Undo" disabled={!chart.canUndo} onClick={chart.undo} className={tbBtn()}>
        <Icon name="undo" size={18} />
      </button>
      <button type="button" title="Redo (Ctrl+Shift+Z)" aria-label="Redo" disabled={!chart.canRedo} onClick={chart.redo} className={tbBtn()}>
        <Icon name="redo" size={18} />
      </button>
      <Sep />
      <button type="button" title="Object tree" aria-label={`Objects (${chart.count})`} aria-pressed={chart.listOpen} onClick={chart.toggleList} className={tbBtn(chart.listOpen)}>
        <Icon name="list" size={18} />
        <span className="text-[11px] tabular-nums">{chart.count}</span>
      </button>
      <button type="button" title="Download a PNG of the chart" aria-label="Screenshot" disabled={!d || d.bars.length === 0} onClick={chart.screenshot} className={tbBtn()}>
        <Icon name="camera" size={18} />
      </button>
      <button type="button" title={full ? "Exit full screen" : "Full screen"} aria-label={full ? "Exit full screen" : "Full screen"} onClick={() => (document.fullscreenElement ? void document.exitFullscreen() : void box.current?.requestFullscreen())} className={tbBtn(full)}>
        <Icon name={full ? "exit" : "fullscreen"} size={18} />
      </button>
    </div>
  );

  const body = q.isError ? (
    <div className="p-4"><ErrorBox error={q.error} what="the index candles" /></div>
  ) : q.isLoading || !d ? (
    <div className="p-4"><Loading what="the index candles" /></div>
  ) : (
    <div className="flex h-full flex-col items-center justify-center gap-1 px-4 text-center">
      <div className="text-sm font-semibold text-slate-800">{intraday ? "No minute candles in this range" : "No candles in this range"}</div>
      <div className="max-w-sm text-xs text-slate-500">
        {intraday ? (d.intraday_first ? `Minute history for this index starts on ${d.intraday_first}. Choose a later range or a daily timeframe.` : "The live feed has not stored minutes for this index yet: they build up each session. Choose a daily timeframe.") : "Choose a wider date range."}
      </div>
    </div>
  );

  return (
    <div className="space-y-1">
      <div ref={box} className={`flex flex-col overflow-hidden rounded-lg border border-line bg-white shadow-sm ${full ? "h-screen" : "h-[560px]"}`} data-testid="index-chart">
        {d && d.bars.length > 0 ? (
          <PriceChart noVolume bars={d.bars} actions={[]} instrumentId={`idx:${symbol}`} adjust="none" timeframe={d.timeframe} symbol={symbol} exchange={d.exchange} chartType={chartType} indicators={NO_INDICATORS} topbar={topbar} onExtend={extend} />
        ) : (
          <>
            {topbar(NO_API)}
            <div className="flex-1">{body}</div>
          </>
        )}
      </div>
      {d ? (
        <p className="text-xs text-ink-faint">
          Kite daily candles from {d.first}; minute candles {d.intraday_first ? `from ${d.intraday_first}` : "not stored yet"} (built by the live feed each session). An index has no volume. Drawings are notes saved in this browser.
        </p>
      ) : null}
    </div>
  );
}
