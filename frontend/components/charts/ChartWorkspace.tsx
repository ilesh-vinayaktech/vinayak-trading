"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ErrorBox, Loading } from "@/components/status/LoadState";
import { api } from "@/lib/api/client";
import { MAX_ACTIVE, defaultSpec, loadActive, newUid, saveActive, type Active } from "@/lib/indicators";
import { type Adjust, type Bars, type Instrument, type InstrumentDetail, type Timeframe } from "@/lib/schemas";
import { INTRADAY_MAX_DAYS, INTRADAY_PRESETS, isIntraday, shiftDays } from "@/lib/timeframes";
import { TimeframeMenu } from "./TimeframeMenu";
import { Icon, type IconName } from "./icons";
import { IndicatorDialog } from "./IndicatorDialog";
import { PriceChart, type ChartType, type IndicatorControls } from "./PriceChart";
import { SymbolSearch } from "./SymbolSearch";

export const BASES: { value: Adjust; label: string; blurb: string }[] = [
  { value: "none", label: "Raw (as traded)", blurb: "exactly as traded; no adjustment" },
  { value: "split", label: "Split/bonus adjusted", blurb: "splits, bonuses and similar price events; no dividends" },
  { value: "total_return", label: "Total-return adjusted", blurb: "split/bonus adjusted and dividends folded in" },
];

const TYPES: { key: ChartType; label: string; icon: IconName }[] = [
  { key: "candles", label: "Candles", icon: "candles" },
  { key: "line", label: "Line", icon: "line" },
  { key: "area", label: "Area", icon: "area" },
];

const PRESETS = [
  { key: "1M", months: 1 },
  { key: "3M", months: 3 },
  { key: "6M", months: 6 },
  { key: "1Y", months: 12 },
  { key: "5Y", months: 60 },
  { key: "All", months: 0 },
] as const;

/** First date of a "last N months" window ending at `last` (a request parameter; the API selects). */
export function presetStart(last: string, first: string | null, months: number): string {
  if (months === 0) return first ?? last;
  const d = new Date(`${last}T00:00:00Z`);
  d.setUTCMonth(d.getUTCMonth() - months);
  const iso = d.toISOString().slice(0, 10);
  return first && iso < first ? first : iso;
}

const tbBtn = (active = false) => `flex h-8 items-center justify-center gap-1.5 rounded-md px-2 text-[13px] transition-colors ${active ? "bg-blue-50 text-blue-700" : "text-slate-700 hover:bg-slate-100"} disabled:opacity-35 disabled:hover:bg-transparent`;
const Sep = () => <span className="mx-1 h-5 w-px bg-line" aria-hidden="true" />;

export function ChartWorkspace({ picked, onPick, instrument, adjust, onAdjust, timeframe, onTimeframe, start, end, onRange, bars, loading, error }: { picked: Instrument | null; onPick: (i: Instrument) => void; instrument: InstrumentDetail | null; adjust: Adjust; onAdjust: (a: Adjust) => void; timeframe: Timeframe; onTimeframe: (t: Timeframe) => void; start: string; end: string; onRange: (s: string, e: string) => void; bars: Bars | undefined; loading: boolean; error: unknown }) {
  const box = useRef<HTMLDivElement>(null);
  const [chartType, setChartType] = useState<ChartType>("candles");
  const [full, setFull] = useState(false);
  const [rangeOpen, setRangeOpen] = useState(false);
  const [active, setActive] = useState<Active[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [dialog, setDialog] = useState(false);
  useEffect(() => {
    setActive(loadActive());
    setLoaded(true);
  }, []);
  useEffect(() => {
    if (loaded) saveActive(active);
  }, [active, loaded]);
  const catalog = useQuery({ queryKey: ["indicator-catalog"], queryFn: api.indicatorCatalog, staleTime: Infinity });
  const names = active.map((a) => a.spec).join(",");
  const series = useQuery({
    queryKey: ["indicators", picked?.id, start, end, adjust, names],
    queryFn: () => api.indicatorSeries(picked?.id as number, start, end, adjust, names),
    enabled: picked !== null && names !== "" && start !== "" && start <= end && timeframe === "1d", // indicators are computed on daily bars
    placeholderData: (prev) => prev,
  });
  const controls: IndicatorControls = useMemo(
    () => ({
      active,
      data: series.data,
      catalog: catalog.data?.indicators ?? [],
      onToggle: (uid) => setActive((l) => l.map((a) => (a.uid === uid ? { ...a, visible: !a.visible } : a))),
      onRemove: (uid) => setActive((l) => l.filter((a) => a.uid !== uid)),
      onEdit: (uid, spec) => setActive((l) => l.map((a) => (a.uid === uid ? { ...a, spec } : a))),
    }),
    [active, series.data, catalog.data],
  );
  const counts: Record<string, number> = {};
  for (const a of active) {
    const n = a.spec.split(":")[0] as string;
    counts[n] = (counts[n] ?? 0) + 1;
  }
  const last = instrument?.bars.last ?? null;
  const first = instrument?.bars.first ?? null;

  useEffect(() => {
    const on = () => setFull(document.fullscreenElement === box.current);
    document.addEventListener("fullscreenchange", on);
    return () => document.removeEventListener("fullscreenchange", on);
  }, []);
  const toggleFull = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void box.current?.requestFullscreen();
  };

  const topbar = (api: Parameters<React.ComponentProps<typeof PriceChart>["topbar"]>[0]): ReactNode => (
    <div className="flex flex-wrap items-center gap-0.5 border-b border-line bg-white px-2 py-1" role="toolbar" aria-label="Chart controls">
      <SymbolSearch current={picked?.symbol ?? null} onPick={onPick} />
      <Sep />
      <TimeframeMenu value={timeframe} onChange={onTimeframe} className={tbBtn(false)} />
      <Sep />
      <div className="flex items-center" role="group" aria-label="Chart type">
        {TYPES.map((t) => (
          <button key={t.key} type="button" title={t.label} aria-label={t.label} aria-pressed={chartType === t.key} onClick={() => setChartType(t.key)} className={tbBtn(chartType === t.key)}>
            <Icon name={t.icon} size={18} />
          </button>
        ))}
      </div>
      <Sep />
      <button type="button" title={timeframe !== "1d" ? "Indicators are available on the 1D timeframe" : "Indicators"} aria-label="Indicators" disabled={timeframe !== "1d"} onClick={() => setDialog(true)} className={tbBtn(active.length > 0 && timeframe === "1d")}>
        <Icon name="line" size={18} />
        <span>Indicators</span>
      </button>
      <Sep />
      <label className="sr-only" htmlFor="adjust">
        Price basis
      </label>
      <select id="adjust" value={adjust} onChange={(e) => onAdjust(e.target.value as Adjust)} title={BASES.find((b) => b.value === adjust)?.blurb} className="h-8 rounded-md border-0 bg-transparent px-2 text-[13px] font-medium text-slate-800 hover:bg-slate-100">
        {BASES.map((b) => (
          <option key={b.value} value={b.value} disabled={isIntraday(timeframe) && b.value === "total_return"}>
            {b.label}
          </option>
        ))}
      </select>
      <Sep />
      <div className="flex items-center" role="group" aria-label="Date range">
        {(isIntraday(timeframe)
          ? INTRADAY_PRESETS.filter((p) => p.days <= INTRADAY_MAX_DAYS[timeframe]).map((p) => ({ key: p.key, from: (l: string) => shiftDays(l, -p.days) }))
          : PRESETS.map((p) => ({ key: p.key, from: (l: string) => presetStart(l, first, p.months) }))
        ).map((p) => (
          <button key={p.key} type="button" disabled={!last} onClick={() => last && onRange(p.from(last), last)} className={tbBtn(false)}>
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
                <label htmlFor="start" className="block text-[11px] text-slate-500">
                  From
                </label>
                <input id="start" type="date" value={start} onChange={(e) => onRange(e.target.value, end)} className="rounded border border-line px-2 py-1 text-sm" />
              </div>
              <div>
                <label htmlFor="end" className="block text-[11px] text-slate-500">
                  To
                </label>
                <input id="end" type="date" value={end} onChange={(e) => onRange(start, e.target.value)} className="rounded border border-line px-2 py-1 text-sm" />
              </div>
            </div>
          ) : null}
        </div>
      </div>
      <span className="flex-1" />
      <button type="button" title="Undo (Ctrl+Z)" aria-label="Undo" disabled={!api.canUndo} onClick={api.undo} className={tbBtn()}>
        <Icon name="undo" size={18} />
      </button>
      <button type="button" title="Redo (Ctrl+Shift+Z)" aria-label="Redo" disabled={!api.canRedo} onClick={api.redo} className={tbBtn()}>
        <Icon name="redo" size={18} />
      </button>
      <Sep />
      <button type="button" title="Object tree" aria-label={`Objects (${api.count})`} aria-pressed={api.listOpen} onClick={api.toggleList} className={tbBtn(api.listOpen)}>
        <Icon name="list" size={18} />
        <span className="text-[11px] tabular-nums">{api.count}</span>
      </button>
      <button type="button" title="Download a PNG of the chart" aria-label="Screenshot" disabled={!bars || bars.bars.length === 0} onClick={api.screenshot} className={tbBtn()}>
        <Icon name="camera" size={18} />
      </button>
      <button type="button" title={full ? "Exit full screen" : "Full screen"} aria-label={full ? "Exit full screen" : "Full screen"} onClick={toggleFull} className={tbBtn(full)}>
        <Icon name={full ? "exit" : "fullscreen"} size={18} />
      </button>
      <button type="button" disabled title="Needs a stored backtest with its trades; none exist yet" className="ml-1 hidden h-8 cursor-not-allowed items-center rounded-md border border-dashed border-line px-2 text-[12px] text-slate-400 lg:flex">
        Strategy run: not available yet
      </button>
    </div>
  );

  const body =
    picked === null ? (
      <Empty title="Open a chart" text="Search for a symbol, ISIN or company name to load its daily bars." />
    ) : error ? (
      <div className="p-4"><ErrorBox error={error} what="bars" /></div>
    ) : loading || !bars ? (
      <div className="p-4"><Loading what="bars" /></div>
    ) : bars.bars.length === 0 ? (
      <Empty title="No bars in this range" text="Choose a wider date range." />
    ) : null;

  return (
    <div ref={box} className={`flex flex-col overflow-hidden rounded-lg border border-line bg-white shadow-sm ${full ? "h-screen" : "h-[calc(100vh-15rem)] min-h-[560px]"}`} data-testid="chart-workspace">
      {bars && bars.bars.length > 0 && picked ? (
        <PriceChart bars={bars.bars} actions={instrument?.actions ?? []} instrumentId={picked.id} adjust={adjust} timeframe={bars.timeframe} symbol={picked.symbol} exchange="NSE" chartType={chartType} indicators={controls} topbar={topbar} />
      ) : (
        <>
          {topbar({ undo: () => {}, redo: () => {}, canUndo: false, canRedo: false, count: 0, listOpen: false, toggleList: () => {}, screenshot: () => {} })}
          <div className="flex-1">{body}</div>
        </>
      )}
      {dialog ? (
        <IndicatorDialog
          catalog={catalog.data?.indicators ?? []}
          counts={counts}
          atLimit={active.length >= MAX_ACTIVE}
          onClose={() => setDialog(false)}
          onAdd={(def) => active.length < MAX_ACTIVE && setActive((l) => [...l, { uid: newUid(), spec: defaultSpec(def), visible: true }])}
        />
      ) : null}
    </div>
  );
}

function Empty({ title, text }: { title: string; text: string }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
      <Icon name="candles" size={40} className="text-slate-300" />
      <div className="text-sm font-semibold text-slate-800">{title}</div>
      <div className="max-w-xs text-xs text-slate-500">{text}</div>
    </div>
  );
}
