"use client";

import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type ISeriesApi,
  type LogicalRange,
  type MouseEventParams,
  type SeriesMarker,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { reachedLeftEdge, viewToRestore, type SavedView } from "@/lib/chartView";
import { plotNumber } from "@/lib/formatting";
import { toPoints, type Active } from "@/lib/indicators";
import type { Bars, IndicatorDef, IndicatorSeries, InstrumentDetail, Timeframe } from "@/lib/schemas";
import { TIMEFRAME_LABELS, barLabel, barTime, isIntraday } from "@/lib/timeframes";
import { DrawingTools, type ChartHandles, type DrawingApi } from "./DrawingTools";
import { IndicatorRow } from "./IndicatorLegend";

type Action = InstrumentDetail["actions"][number];
export type Mark = { day: string; action: "BUY" | "SELL" };
/** The candle still forming, as the server built it for this timeframe from the live feed (`time`: date or UTC epoch seconds). */
export type LiveView = { candle: { time: number | string; open: string; high: string; low: string; close: string; volume: string }; prevClose: string | null; live: boolean };

/** The live candle as a bar of the chart's own shape, so it is placed and labelled like every other bar. */
function liveBarOf(v: LiveView): Bar {
  const c = v.candle;
  const date = typeof c.time === "number" ? new Date((c.time + 19800) * 1000).toISOString().slice(0, 10) : c.time;
  return { date, ...(typeof c.time === "number" ? { time: c.time } : {}), open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume, factor: "1" };
}
const NO_SIGNALS: Mark[] = []; // a stable default: a fresh array each render would rebuild the chart each render
type Bar = Bars["bars"][number];
export type ChartType = "candles" | "line" | "area";
export type ChartApi = DrawingApi & { screenshot: () => void };
export type IndicatorControls = {
  active: Active[];
  data: IndicatorSeries | undefined;
  catalog: IndicatorDef[];
  onToggle: (uid: string) => void;
  onRemove: (uid: string) => void;
  onEdit: (uid: string, spec: string) => void;
};

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });
const PALETTE = ["#2563eb", "#f59e0b", "#7c3aed", "#db2777", "#0891b2", "#059669"];
const PANE_HEIGHT = 140;

/** Candles/line/area and volume exactly as the API returned them (prices are parsed only to be
 * drawn). The data is OUR database's: the chart library only renders it. Indicator VALUES come from
 * the backend (algo.indicators); overlays draw on the price pane, oscillators in panes below it.
 * Drawings are browser-only notes (see DrawingTools); they never feed anything else. */
export function PriceChart({ showEvents = false, bars, actions, instrumentId, adjust, timeframe, symbol, exchange, chartType, indicators, topbar, signals = NO_SIGNALS, onExtend, live = null, compare }: { showEvents?: boolean; compare?: { name: string; points: { date: string; level: string }[] }; live?: LiveView | null; onExtend?: () => void; signals?: Mark[]; bars: Bar[]; actions: Action[]; instrumentId: number; adjust: string; timeframe: Timeframe; symbol: string; exchange: string; chartType: ChartType; indicators: IndicatorControls; topbar: (api: ChartApi) => ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const handles = useRef<ChartHandles | null>(null);
  const [hover, setHover] = useState<Bar | null>(null);
  const [ready, setReady] = useState(0); // bumps each time a fresh chart exists
  const [tick, setTick] = useState(0); // bumps when the view moves or resizes, so overlays re-project
  const movedByUser = useRef(false); // set by the mouse (wheel or drag): the library also reports moves we make ourselves
  const extending = useRef(false); // earlier history was just asked for: keep the user's place when it arrives
  const savedView = useRef<SavedView<Time> | null>(null);
  const lastExtend = useRef(0);
  const onExtendRef = useRef(onExtend);
  onExtendRef.current = onExtend;
  const askEarlier = useRef(() => {
    const ask = onExtendRef.current;
    if (!ask) return;
    extending.current = true;
    window.setTimeout(() => {
      extending.current = false; // nothing arrived (already at the first bar): the next rebuild fits the data
    }, 4000);
    ask();
  });

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = createChart(el, {
      width: el.clientWidth,
      height: el.clientHeight,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#475569", fontSize: 12, panes: { separatorColor: "#e2e8f0", separatorHoverColor: "#cbd5e1", enableResize: true } },
      grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#f1f5f9" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#e2e8f0", scaleMargins: { top: 0.1, bottom: 0.2 }, minimumWidth: 64 },
      timeScale: { borderColor: "#e2e8f0", rightOffset: 6, minBarSpacing: 0.4, timeVisible: isIntraday(timeframe), secondsVisible: false }, // edges are free: wheel zooms either way and you can drag past the loaded history
    });
    const series: ISeriesApi<SeriesType> =
      chartType === "candles"
        ? chart.addSeries(CandlestickSeries, { upColor: "#089981", downColor: "#f23645", borderVisible: false, wickUpColor: "#089981", wickDownColor: "#f23645" })
        : chartType === "line"
          ? chart.addSeries(LineSeries, { color: "#2563eb", lineWidth: 2 })
          : chart.addSeries(AreaSeries, { lineColor: "#2563eb", topColor: "rgba(37,99,235,0.28)", bottomColor: "rgba(37,99,235,0.02)", lineWidth: 2 });
    if (chartType === "candles") (series as ISeriesApi<"Candlestick">).setData(bars.map((b) => ({ time: barTime(b) as Time, open: plotNumber(b.open), high: plotNumber(b.high), low: plotNumber(b.low), close: plotNumber(b.close) })));
    else (series as ISeriesApi<"Line">).setData(bars.map((b) => ({ time: barTime(b) as Time, value: plotNumber(b.close) })));
    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.9, bottom: 0 } });
    volume.setData(bars.map((b, i) => ({ time: barTime(b) as Time, value: plotNumber(b.volume), color: plotNumber(b.close) >= plotNumber(bars[Math.max(0, i - 1)]?.close ?? b.close) ? "rgba(8,153,129,0.28)" : "rgba(242,54,69,0.28)" })));
    const byTime = new Map<string | number, Bar>(bars.map((b) => [barTime(b), b]));
    const onMove = (p: MouseEventParams<Time>) => setHover(typeof p.time === "string" || typeof p.time === "number" ? (byTime.get(p.time) ?? null) : null);
    chart.subscribeCrosshairMove(onMove);
    const onRange = (r: LogicalRange | null) => {
      setTick((n) => n + 1);
      if (reachedLeftEdge(r, movedByUser.current) && Date.now() - lastExtend.current > 1000) {
        lastExtend.current = Date.now();
        askEarlier.current(); // the user has panned or zoomed out to the first loaded bar: load more behind it
      }
    };
    const markMoved = () => {
      movedByUser.current = true;
    };
    el.addEventListener("wheel", markMoved, { passive: true });
    el.addEventListener("pointerdown", markMoved);
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);
    const days = bars.map((b) => b.date);
    const markers: SeriesMarker<Time>[] = [];
    for (const a of isIntraday(timeframe) || !showEvents ? [] : actions) { // action markers sit on date-axis bars
      const day = days.find((d) => d >= a.ex_date);
      if (!day || a.ex_date < (days[0] ?? "")) continue;
      markers.push({ time: day as Time, position: "aboveBar", color: a.status === "ok" ? "#2563eb" : "#d97706", shape: "arrowDown", text: a.kind });
    }
    if (!isIntraday(timeframe)) {
      for (const s of signals) { // a decision is drawn on the day it was made (after that close)
        const day = days.find((d) => d >= s.day);
        if (day) markers.push({ time: day as Time, position: s.action === "BUY" ? "belowBar" : "aboveBar", color: s.action === "BUY" ? "#089981" : "#f23645", shape: s.action === "BUY" ? "arrowUp" : "arrowDown", text: s.action });
      }
    }
    markers.sort((x, y) => String(x.time).localeCompare(String(y.time)));
    createSeriesMarkers(series, markers);
    const viewKey = `${instrumentId}|${adjust}|${timeframe}`;
    const keep = viewToRestore(savedView.current, viewKey, extending.current);
    extending.current = false;
    movedByUser.current = keep !== null;
    if (keep) {
      try {
        chart.timeScale().setVisibleRange(keep);
      } catch {
        chart.timeScale().fitContent();
      }
    } else chart.timeScale().fitContent();
    const fit = () => {
      chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
      setTick((n) => n + 1);
    };
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    handles.current = { chart, series, volume };
    setReady((n) => n + 1);
    // the library lays the chart out on the next frames: project the overlays again once it has
    const frame = requestAnimationFrame(() => requestAnimationFrame(() => setTick((n) => n + 1)));
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      chart.unsubscribeCrosshairMove(onMove);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      el.removeEventListener("wheel", markMoved);
      el.removeEventListener("pointerdown", markMoved);
      try {
        const r = chart.timeScale().getVisibleRange();
        savedView.current = r ? { key: viewKey, range: { from: r.from as Time, to: r.to as Time } } : null;
      } catch {
        savedView.current = null; // the chart could not say where it was: the next one fits the data
      }
      handles.current = null;
      chart.remove();
    };
  }, [bars, actions, signals, chartType, timeframe, showEvents]); // eslint-disable-line react-hooks/exhaustive-deps

  // indicators: overlays on the price pane, oscillators one pane each below it
  const { active, data, catalog } = indicators;
  const colorsFor = useMemo(() => {
    const m = new Map<string, Record<string, string>>();
    active.forEach((a, i) => {
      const r = data?.indicators.find((x) => x.spec === a.spec);
      if (r && r.outputs.length === 1) m.set(a.uid, { [r.outputs[0]?.key ?? "value"]: PALETTE[i % PALETTE.length] as string });
    });
    return m;
  }, [active, data]);

  useEffect(() => {
    const h = handles.current;
    if (!h || !data) return;
    const made: ISeriesApi<SeriesType>[] = [];
    let panes = 0;
    for (const a of active) {
      if (!a.visible) continue;
      const r = data.indicators.find((x) => x.spec === a.spec);
      if (!r) continue;
      const paneIndex = r.pane === "pane" ? ++panes : 0;
      const colors = colorsFor.get(a.uid) ?? {};
      let first: ISeriesApi<SeriesType> | null = null;
      for (const o of r.outputs) {
        const color = colors[o.key] ?? o.color;
        const label = paneIndex > 0;
        let s: ISeriesApi<SeriesType>;
        if (o.kind === "histogram") {
          s = h.chart.addSeries(HistogramSeries, { lastValueVisible: false, priceLineVisible: false }, paneIndex);
          s.setData(o.values.map((v, i) => (v === null ? { time: data.dates[i] as Time } : { time: data.dates[i] as Time, value: Number.parseFloat(v), color: Number.parseFloat(v) >= 0 ? "rgba(8,153,129,0.6)" : "rgba(242,54,69,0.6)" })));
        } else {
          s = h.chart.addSeries(LineSeries, o.kind === "dots" ? { color, lineVisible: false, pointMarkersVisible: true, pointMarkersRadius: 2, lastValueVisible: false, priceLineVisible: false } : { color, lineWidth: r.outputs.length === 1 || o.key === "up" || o.key === "down" ? 2 : 1, lastValueVisible: label, priceLineVisible: false }, paneIndex);
          s.setData(toPoints(data.dates, o.values).map((p) => ({ ...p, time: p.time as Time })));
          first ??= s;
        }
        made.push(s);
      }
      if (first) for (const lv of r.levels) first.createPriceLine({ price: Number.parseFloat(lv), color: "#cbd5e1", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false });
    }
    const frame = requestAnimationFrame(() => {
      h.chart.panes().forEach((p, i) => {
        if (i > 0) p.setHeight(PANE_HEIGHT);
      });
      setTick((n) => n + 1);
    });
    return () => {
      cancelAnimationFrame(frame);
      if (handles.current?.chart !== h.chart) return; // the chart was replaced: its series went with it
      for (const s of made) h.chart.removeSeries(s);
    };
  }, [active, data, ready, colorsFor]);

  // the candle still forming follows the feed: updated in place, so zoom and position are kept (no rebuild of the chart).
  // One older than the last stored bar is ignored: the chart already has that bar.
  const liveBar = useMemo(() => (live ? liveBarOf(live) : null), [live]);
  useEffect(() => {
    const h = handles.current;
    const last = bars[bars.length - 1];
    if (!h || !live || !liveBar || !last) return;
    const time = barTime(liveBar);
    if (time < barTime(last)) return;
    const close = plotNumber(liveBar.close);
    const open = plotNumber(liveBar.open);
    const high = plotNumber(liveBar.high);
    const low = plotNumber(liveBar.low);
    if (chartType === "candles") (h.series as ISeriesApi<"Candlestick">).update({ time: time as Time, open, high, low, close });
    else (h.series as ISeriesApi<"Line">).update({ time: time as Time, value: close });
    const up = close >= (timeframe === "1d" && live.prevClose !== null ? plotNumber(live.prevClose) : open);
    (h.volume as ISeriesApi<"Histogram"> | undefined)?.update({ time: time as Time, value: plotNumber(liveBar.volume), color: up ? "rgba(8,153,129,0.45)" : "rgba(242,54,69,0.45)" });
  }, [live, liveBar, ready, chartType, timeframe, bars]);

  // a benchmark drawn over the stock as a line on its own left scale (index levels are not in rupees per share)
  useEffect(() => {
    const h = handles.current;
    if (!h || !compare || compare.points.length === 0) return;
    h.chart.applyOptions({ leftPriceScale: { visible: true, borderColor: "#e2e8f0" } });
    const s = h.chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 2, priceScaleId: "left", title: compare.name, priceLineVisible: false });
    s.setData(compare.points.map((p) => ({ time: p.date as Time, value: plotNumber(p.level) })));
    return () => {
      if (handles.current?.chart !== h.chart) return; // the chart was replaced: its series went with it
      h.chart.removeSeries(s);
      h.chart.applyOptions({ leftPriceScale: { visible: false } });
    };
  }, [compare, ready]);

  const screenshot = () => {
    const h = handles.current;
    if (!h) return;
    const canvas = h.chart.takeScreenshot();
    const a = document.createElement("a");
    a.download = `${symbol}-${adjust}.png`;
    a.href = canvas.toDataURL("image/png");
    a.click();
  };

  const shown = hover ?? liveBar ?? bars[bars.length - 1];
  const hoverIndex = hover && data ? data.dates.indexOf(hover.date) : -1;
  const index = hoverIndex >= 0 ? hoverIndex : null;
  const rowsOf = (pane: "overlay" | "pane") =>
    active.flatMap((a) => {
      const r = data?.indicators.find((x) => x.spec === a.spec);
      return r && r.pane === pane ? [{ a, r }] : [];
    });
  const row = (a: Active, r: NonNullable<IndicatorSeries["indicators"][number]>) => (
    <IndicatorRow key={a.uid} result={r} def={catalog.find((d) => d.name === r.name)} index={index} colors={colorsFor.get(a.uid) ?? {}} visible={a.visible} onToggle={() => indicators.onToggle(a.uid)} onRemove={() => indicators.onRemove(a.uid)} onEdit={(spec) => indicators.onEdit(a.uid, spec)} />
  );
  const legend = shown ? (
    <div className="text-xs" aria-live="polite">
      <div data-testid="ohlc-legend">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 font-mono text-slate-600">
          <span className="font-sans text-[13px] font-semibold text-slate-900">
            {symbol} <span className="font-normal text-slate-500">· {TIMEFRAME_LABELS[timeframe]} · {exchange}</span>
          </span>
          <span>O <b className="font-medium text-slate-900">{shown.open}</b></span>
          <span>H <b className="font-medium text-slate-900">{shown.high}</b></span>
          <span>L <b className="font-medium text-slate-900">{shown.low}</b></span>
          <span>C <b className="font-medium text-slate-900">{shown.close}</b></span>
          <span className="text-slate-500">{barLabel(shown)}</span>
          {live && shown === liveBar ? <span data-testid="live-badge" className={`rounded px-1.5 font-sans text-[11px] font-semibold ${live.live ? "bg-red-50 text-red-600" : "bg-slate-100 text-slate-500"}`}>{live.live ? "● LIVE" : "last price"}</span> : null}
          <span className="text-slate-500">factor {shown.factor}</span>
        </div>
        <div className="mt-0.5 font-mono text-slate-500">
          Volume <span className="text-slate-800">{compact.format(plotNumber(shown.volume))}</span> <span className="hidden">Vol {shown.volume}</span>
        </div>
      </div>
      {rowsOf("overlay").map(({ a, r }) => row(a, r))}
    </div>
  ) : null;

  // oscillator legends sit at the top-left of their own pane
  const paneRows = rowsOf("pane");
  let paneOverlay: ReactNode = null;
  try {
    const h = handles.current;
    const box = ref.current?.getBoundingClientRect();
    const visiblePanes = paneRows.filter(({ a }) => a.visible);
    if (h && box && visiblePanes.length > 0) {
      const panes = h.chart.panes();
      paneOverlay = visiblePanes.map(({ a, r }, i) => {
        const el = panes[i + 1]?.getHTMLElement();
        const top = el ? el.getBoundingClientRect().top - box.top : null;
        return top === null ? null : (
          <div key={a.uid} className="pointer-events-none absolute left-3 z-20" style={{ top: top + 4 }}>
            {row(a, r)}
          </div>
        );
      });
    }
  } catch {
    paneOverlay = null; // the chart was replaced mid-render
  }
  // moving the chart without a mouse: zoom, move, fit. At the start of the loaded history, moving left or zooming out asks
  // for earlier history (onExtend) instead of stopping dead.
  const view = (action: "in" | "out" | "left" | "right" | "fit") => {
    const scale = handles.current?.chart.timeScale();
    const r = scale?.getVisibleLogicalRange();
    if (!scale || !r) return;
    const width = r.to - r.from;
    const mid = (r.from + r.to) / 2;
    const atStart = r.from <= 0.5;
    if (action === "fit") scale.fitContent();
    else if (action === "in") {
      if (width > 10) scale.setVisibleLogicalRange({ from: mid - width / 4, to: mid + width / 4 });
    } else if (action === "out") {
      if (atStart) askEarlier.current();
      scale.setVisibleLogicalRange({ from: mid - width, to: mid + width });
    } else {
      const step = (action === "left" ? -1 : 1) * width * 0.25;
      if (action === "left" && atStart) askEarlier.current();
      scale.setVisibleLogicalRange({ from: r.from + step, to: r.to + step });
    }
    setTick((n) => n + 1);
  };
  const viewBtn = "flex h-7 min-w-7 items-center justify-center rounded px-1.5 text-sm text-slate-700 hover:bg-slate-100";
  const controls = (
    <div className="absolute bottom-10 left-1/2 z-20 flex -translate-x-1/2 items-center gap-0.5 rounded-lg border border-line bg-white/95 p-0.5 shadow" role="group" aria-label="Move the chart">
      <button type="button" aria-label="Move left" title="Move left (earlier)" onClick={() => view("left")} className={viewBtn}>‹</button>
      <button type="button" aria-label="Zoom out" title="Zoom out" onClick={() => view("out")} className={viewBtn}>−</button>
      <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => view("in")} className={viewBtn}>+</button>
      <button type="button" aria-label="Move right" title="Move right (later)" onClick={() => view("right")} className={viewBtn}>›</button>
      <button type="button" aria-label="Fit all" title="Fit all loaded bars" onClick={() => view("fit")} className={`${viewBtn} text-xs`}>Fit</button>
    </div>
  );
  const hiddenRows = paneRows.filter(({ a }) => !a.visible);
  return (
    <DrawingTools handles={handles.current} ready={ready} tick={tick} bars={bars} instrumentId={instrumentId} adjust={adjust} above={legend} overlay={<>{controls}{paneOverlay}{hiddenRows.length ? <div className="pointer-events-none absolute bottom-9 right-20 z-20 flex gap-2">{hiddenRows.map(({ a, r }) => row(a, r))}</div> : null}</>} topbar={(api) => topbar({ ...api, screenshot })}>
      <div ref={ref} className="h-full w-full" data-testid="price-chart" />
    </DrawingTools>
  );
}
