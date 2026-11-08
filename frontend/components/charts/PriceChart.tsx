"use client";

import { ColorType, CrosshairMode, createChart, type MouseEventParams, type SeriesMarker, type Time } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { plotNumber } from "@/lib/formatting";
import type { Bars, InstrumentDetail } from "@/lib/schemas";
import { DrawingTools, type ChartHandles } from "./DrawingTools";

type Action = InstrumentDetail["actions"][number];
type Bar = Bars["bars"][number];

/** Candles and volume exactly as the API returned them (prices are parsed only to be drawn). The
 * data is OUR database's: the chart library only renders it. Corporate actions are markers on the
 * first bar on or after their ex-date. Drawings are browser-only notes (see DrawingTools); they
 * never feed anything else. */
export function PriceChart({ bars, actions, instrumentId, adjust }: { bars: Bar[]; actions: Action[]; instrumentId: number; adjust: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const handles = useRef<ChartHandles | null>(null);
  const [hover, setHover] = useState<Bar | null>(null);
  const [ready, setReady] = useState(0); // bumps each time a fresh chart exists
  const [tick, setTick] = useState(0); // bumps when the view moves, so drawings re-project

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = createChart(el, {
      height: 420,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#475569", fontSize: 12 },
      grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#f1f5f9" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#e2e8f0", scaleMargins: { top: 0.06, bottom: 0.27 } },
      timeScale: { borderColor: "#e2e8f0", fixLeftEdge: true, fixRightEdge: true },
    });
    const candles = chart.addCandlestickSeries({ upColor: "#059669", downColor: "#dc2626", borderVisible: false, wickUpColor: "#059669", wickDownColor: "#dc2626" });
    candles.setData(bars.map((b) => ({ time: b.date as Time, open: plotNumber(b.open), high: plotNumber(b.high), low: plotNumber(b.low), close: plotNumber(b.close) })));
    const volume = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", color: "#cbd5e1", lastValueVisible: false, priceLineVisible: false });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volume.setData(bars.map((b) => ({ time: b.date as Time, value: plotNumber(b.volume) })));
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
    candles.setMarkers(markers);
    chart.timeScale().fitContent();
    const resize = () => {
      chart.applyOptions({ width: el.clientWidth });
      setTick((n) => n + 1);
    };
    resize();
    window.addEventListener("resize", resize);
    handles.current = { chart, series: candles };
    setReady((n) => n + 1);
    // the library lays the chart out on the next frames: project the drawings again once it has
    const frame = requestAnimationFrame(() => requestAnimationFrame(() => setTick((n) => n + 1)));
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      chart.unsubscribeCrosshairMove(onMove);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      handles.current = null;
      chart.remove();
    };
  }, [bars, actions]);

  const shown = hover ?? bars[bars.length - 1];
  const legend = (
    <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-xs text-ink-soft" aria-live="polite" data-testid="ohlc-legend">
      {shown ? (
        <>
          <span className="text-ink">{shown.date}</span>
          <span>O {shown.open}</span>
          <span>H {shown.high}</span>
          <span>L {shown.low}</span>
          <span>C {shown.close}</span>
          <span>Vol {shown.volume}</span>
          <span>factor {shown.factor}</span>
        </>
      ) : null}
    </div>
  );
  return (
    <DrawingTools handles={handles.current} ready={ready} tick={tick} bars={bars} instrumentId={instrumentId} adjust={adjust} above={legend}>
      <div ref={ref} className="w-full" data-testid="price-chart" />
    </DrawingTools>
  );
}
