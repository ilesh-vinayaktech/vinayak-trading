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
  type MouseEventParams,
  type SeriesMarker,
  type SeriesType,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { plotNumber } from "@/lib/formatting";
import { toPoints, type Active } from "@/lib/indicators";
import type { Bars, IndicatorDef, IndicatorSeries, InstrumentDetail, Timeframe } from "@/lib/schemas";
import { TIMEFRAME_LABELS, barLabel, barTime } from "@/lib/timeframes";
import { DrawingTools, type ChartHandles, type DrawingApi } from "./DrawingTools";
import { IndicatorRow } from "./IndicatorLegend";

type Action = InstrumentDetail["actions"][number];
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
export function PriceChart({ bars, actions, instrumentId, adjust, timeframe, symbol, exchange, chartType, indicators, topbar }: { bars: Bar[]; actions: Action[]; instrumentId: number; adjust: string; timeframe: Timeframe; symbol: string; exchange: string; chartType: ChartType; indicators: IndicatorControls; topbar: (api: ChartApi) => ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const handles = useRef<ChartHandles | null>(null);
  const [hover, setHover] = useState<Bar | null>(null);
  const [ready, setReady] = useState(0); // bumps each time a fresh chart exists
  const [tick, setTick] = useState(0); // bumps when the view moves or resizes, so overlays re-project

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = createChart(el, {
      width: el.clientWidth,
      height: el.clientHeight,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#475569", fontSize: 12, panes: { separatorColor: "#e2e8f0", separatorHoverColor: "#cbd5e1", enableResize: true } },
      grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#f1f5f9" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#e2e8f0", scaleMargins: { top: 0.14, bottom: 0.27 }, minimumWidth: 64 },
      timeScale: { borderColor: "#e2e8f0", fixLeftEdge: true, fixRightEdge: true, timeVisible: timeframe !== "1d", secondsVisible: false },
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
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(bars.map((b, i) => ({ time: barTime(b) as Time, value: plotNumber(b.volume), color: plotNumber(b.close) >= plotNumber(bars[Math.max(0, i - 1)]?.close ?? b.close) ? "rgba(8,153,129,0.45)" : "rgba(242,54,69,0.45)" })));
    const byTime = new Map<string | number, Bar>(bars.map((b) => [barTime(b), b]));
    const onMove = (p: MouseEventParams<Time>) => setHover(typeof p.time === "string" || typeof p.time === "number" ? (byTime.get(p.time) ?? null) : null);
    chart.subscribeCrosshairMove(onMove);
    const onRange = () => setTick((n) => n + 1);
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);
    const days = bars.map((b) => b.date);
    const markers: SeriesMarker<Time>[] = [];
    for (const a of timeframe === "1d" ? actions : []) { // action markers sit on daily bars
      const day = days.find((d) => d >= a.ex_date);
      if (!day || a.ex_date < (days[0] ?? "")) continue;
      markers.push({ time: day as Time, position: "aboveBar", color: a.status === "ok" ? "#2563eb" : "#d97706", shape: "arrowDown", text: a.kind });
    }
    markers.sort((x, y) => String(x.time).localeCompare(String(y.time)));
    createSeriesMarkers(series, markers);
    chart.timeScale().fitContent();
    const fit = () => {
      chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
      setTick((n) => n + 1);
    };
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    handles.current = { chart, series };
    setReady((n) => n + 1);
    // the library lays the chart out on the next frames: project the overlays again once it has
    const frame = requestAnimationFrame(() => requestAnimationFrame(() => setTick((n) => n + 1)));
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      chart.unsubscribeCrosshairMove(onMove);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      handles.current = null;
      chart.remove();
    };
  }, [bars, actions, chartType, timeframe]);

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

  const screenshot = () => {
    const h = handles.current;
    if (!h) return;
    const canvas = h.chart.takeScreenshot();
    const a = document.createElement("a");
    a.download = `${symbol}-${adjust}.png`;
    a.href = canvas.toDataURL("image/png");
    a.click();
  };

  const shown = hover ?? bars[bars.length - 1];
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
  const hiddenRows = paneRows.filter(({ a }) => !a.visible);
  return (
    <DrawingTools handles={handles.current} ready={ready} tick={tick} bars={bars} instrumentId={instrumentId} adjust={adjust} above={legend} overlay={<>{paneOverlay}{hiddenRows.length ? <div className="pointer-events-none absolute bottom-9 right-20 z-20 flex gap-2">{hiddenRows.map(({ a, r }) => row(a, r))}</div> : null}</>} topbar={(api) => topbar({ ...api, screenshot })}>
      <div ref={ref} className="h-full w-full" data-testid="price-chart" />
    </DrawingTools>
  );
}
