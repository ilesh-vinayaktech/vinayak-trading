"use client";

import { ColorType, CrosshairMode, createChart, type MouseEventParams, type SeriesMarker, type Time } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { plotNumber } from "@/lib/formatting";
import type { Bars, InstrumentDetail } from "@/lib/schemas";

type Action = InstrumentDetail["actions"][number];
type Bar = Bars["bars"][number];

/** Candles and volume exactly as the API returned them (prices are parsed only to be drawn).
 * Corporate actions are markers on the first bar on or after their ex-date. Hovering shows the
 * bar's own strings, including the adjustment factor the backend applied. */
export function PriceChart({ bars, actions }: { bars: Bar[]; actions: Action[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<Bar | null>(null);
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
    const resize = () => chart.applyOptions({ width: el.clientWidth });
    resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
    };
  }, [bars, actions]);
  const shown = hover ?? bars[bars.length - 1];
  return (
    <div>
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
      <div ref={ref} className="w-full" data-testid="price-chart" />
    </div>
  );
}
