"use client";

import { ColorType, CrosshairMode, createChart, type MouseEventParams, type SeriesMarker, type Time } from "lightweight-charts";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { plotNumber } from "@/lib/formatting";
import type { Bars, InstrumentDetail } from "@/lib/schemas";
import { DrawingTools, type ChartHandles, type DrawingApi } from "./DrawingTools";

type Action = InstrumentDetail["actions"][number];
type Bar = Bars["bars"][number];
export type ChartType = "candles" | "line" | "area";
export type ChartApi = DrawingApi & { screenshot: () => void };

const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 2 });

/** Candles/line/area and volume exactly as the API returned them (prices are parsed only to be
 * drawn). The data is OUR database's: the chart library only renders it. Corporate actions are
 * markers on the first bar on or after their ex-date. The chart fills its container. Drawings are
 * browser-only notes (see DrawingTools); they never feed anything else. */
export function PriceChart({ bars, actions, instrumentId, adjust, symbol, exchange, chartType, topbar }: { bars: Bar[]; actions: Action[]; instrumentId: number; adjust: string; symbol: string; exchange: string; chartType: ChartType; topbar: (api: ChartApi) => ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const handles = useRef<ChartHandles | null>(null);
  const [hover, setHover] = useState<Bar | null>(null);
  const [ready, setReady] = useState(0); // bumps each time a fresh chart exists
  const [tick, setTick] = useState(0); // bumps when the view moves or resizes, so drawings re-project

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = createChart(el, {
      width: el.clientWidth,
      height: el.clientHeight,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#475569", fontSize: 12 },
      grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#f1f5f9" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#e2e8f0", scaleMargins: { top: 0.14, bottom: 0.27 } },
      timeScale: { borderColor: "#e2e8f0", fixLeftEdge: true, fixRightEdge: true },
    });
    const series =
      chartType === "candles"
        ? chart.addCandlestickSeries({ upColor: "#089981", downColor: "#f23645", borderVisible: false, wickUpColor: "#089981", wickDownColor: "#f23645" })
        : chartType === "line"
          ? chart.addLineSeries({ color: "#2563eb", lineWidth: 2 })
          : chart.addAreaSeries({ lineColor: "#2563eb", topColor: "rgba(37,99,235,0.28)", bottomColor: "rgba(37,99,235,0.02)", lineWidth: 2 });
    if (chartType === "candles") (series as import("lightweight-charts").ISeriesApi<"Candlestick">).setData(bars.map((b) => ({ time: b.date as Time, open: plotNumber(b.open), high: plotNumber(b.high), low: plotNumber(b.low), close: plotNumber(b.close) })));
    else (series as import("lightweight-charts").ISeriesApi<"Line">).setData(bars.map((b) => ({ time: b.date as Time, value: plotNumber(b.close) })));
    const volume = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(bars.map((b, i) => ({ time: b.date as Time, value: plotNumber(b.volume), color: plotNumber(b.close) >= plotNumber(bars[Math.max(0, i - 1)]?.close ?? b.close) ? "rgba(8,153,129,0.45)" : "rgba(242,54,69,0.45)" })));
    const byDate = new Map(bars.map((b) => [b.date, b]));
    const onMove = (p: MouseEventParams<Time>) => setHover(typeof p.time === "string" ? (byDate.get(p.time) ?? null) : null);
    chart.subscribeCrosshairMove(onMove);
    const onRange = () => setTick((n) => n + 1);
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRange);
    const days = bars.map((b) => b.date);
    const markers: SeriesMarker<Time>[] = [];
    for (const a of actions) {
      const day = days.find((d) => d >= a.ex_date);
      if (!day || a.ex_date < (days[0] ?? "")) continue;
      markers.push({ time: day as Time, position: "aboveBar", color: a.status === "ok" ? "#2563eb" : "#d97706", shape: "arrowDown", text: a.kind });
    }
    markers.sort((x, y) => String(x.time).localeCompare(String(y.time)));
    series.setMarkers(markers);
    chart.timeScale().fitContent();
    const fit = () => {
      chart.applyOptions({ width: el.clientWidth, height: el.clientHeight });
      setTick((n) => n + 1);
    };
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    handles.current = { chart, series };
    setReady((n) => n + 1);
    // the library lays the chart out on the next frames: project the drawings again once it has
    const frame = requestAnimationFrame(() => requestAnimationFrame(() => setTick((n) => n + 1)));
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      chart.unsubscribeCrosshairMove(onMove);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      handles.current = null;
      chart.remove();
    };
  }, [bars, actions, chartType]);

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
  const legend = shown ? (
    <div className="text-xs" aria-live="polite" data-testid="ohlc-legend">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 font-mono text-slate-600">
        <span className="font-sans text-[13px] font-semibold text-slate-900">
          {symbol} <span className="font-normal text-slate-500">· 1D · {exchange}</span>
        </span>
        <span>O <b className="font-medium text-slate-900">{shown.open}</b></span>
        <span>H <b className="font-medium text-slate-900">{shown.high}</b></span>
        <span>L <b className="font-medium text-slate-900">{shown.low}</b></span>
        <span>C <b className="font-medium text-slate-900">{shown.close}</b></span>
        <span className="text-slate-500">{shown.date}</span>
        <span className="text-slate-500">factor {shown.factor}</span>
      </div>
      <div className="mt-0.5 font-mono text-slate-500">
        Volume <span className="text-slate-800">{compact.format(plotNumber(shown.volume))}</span> <span className="hidden">Vol {shown.volume}</span>
      </div>
    </div>
  ) : null;
  return (
    <DrawingTools handles={handles.current} ready={ready} tick={tick} bars={bars} instrumentId={instrumentId} adjust={adjust} above={legend} topbar={(api) => topbar({ ...api, screenshot })}>
      <div ref={ref} className="h-full w-full" data-testid="price-chart" />
    </DrawingTools>
  );
}
