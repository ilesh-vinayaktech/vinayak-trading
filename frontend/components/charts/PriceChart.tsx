"use client";

import { ColorType, createChart, type SeriesMarker, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { plotNumber } from "@/lib/formatting";
import type { Bars, InstrumentDetail } from "@/lib/schemas";

type Action = InstrumentDetail["actions"][number];

/** Candles and volume exactly as the API returned them (prices are parsed only to be drawn).
 * Corporate actions are markers on the first bar on or after their ex-date. */
export function PriceChart({ bars, actions }: { bars: Bars["bars"]; actions: Action[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = createChart(el, {
      height: 380,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#475569" },
      grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#f1f5f9" } },
      rightPriceScale: { borderColor: "#e2e8f0" },
      timeScale: { borderColor: "#e2e8f0" },
    });
    const candles = chart.addCandlestickSeries({ upColor: "#059669", downColor: "#dc2626", borderVisible: false, wickUpColor: "#059669", wickDownColor: "#dc2626" });
    candles.setData(bars.map((b) => ({ time: b.date as Time, open: plotNumber(b.open), high: plotNumber(b.high), low: plotNumber(b.low), close: plotNumber(b.close) })));
    const volume = chart.addHistogramSeries({ priceFormat: { type: "volume" }, priceScaleId: "vol", color: "#cbd5e1" });
    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volume.setData(bars.map((b) => ({ time: b.date as Time, value: plotNumber(b.volume) })));
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
      chart.remove();
    };
  }, [bars, actions]);
  return <div ref={ref} className="w-full" data-testid="price-chart" />;
}
