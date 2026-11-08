"use client";

import { ColorType, createChart, LineSeries, PriceScaleMode, type MouseEventParams, type Time } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { plotNumber } from "@/lib/formatting";

export function LineChart({ points, color = "#0f172a" }: { points: { date: string; level: string }[]; color?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [log, setLog] = useState(true);
  const [hover, setHover] = useState<{ date: string; level: string } | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = createChart(el, {
      height: 320,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#475569", fontSize: 12 },
      grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#f1f5f9" } },
      rightPriceScale: { borderColor: "#e2e8f0", mode: log ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal, scaleMargins: { top: 0.1, bottom: 0.08 } },
      timeScale: { borderColor: "#e2e8f0", fixLeftEdge: true, fixRightEdge: true },
    });
    const line = chart.addSeries(LineSeries, { color, lineWidth: 2, priceFormat: { type: "price", precision: 0, minMove: 1 } });
    line.setData(points.map((p) => ({ time: p.date as Time, value: plotNumber(p.level) })));
    const byDate = new Map(points.map((p) => [p.date, p]));
    const onMove = (m: MouseEventParams<Time>) => setHover(typeof m.time === "string" ? (byDate.get(m.time) ?? null) : null);
    chart.subscribeCrosshairMove(onMove);
    chart.timeScale().fitContent();
    const resize = () => chart.applyOptions({ width: el.clientWidth });
    resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
    };
  }, [points, color, log]);
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-xs text-ink-soft">
        <span>Scale</span>
        <button type="button" onClick={() => setLog(true)} aria-pressed={log} className={`rounded px-2 py-1 ${log ? "bg-slate-900 text-white" : "bg-slate-100"}`}>
          Log
        </button>
        <button type="button" onClick={() => setLog(false)} aria-pressed={!log} className={`rounded px-2 py-1 ${!log ? "bg-slate-900 text-white" : "bg-slate-100"}`}>
          Linear
        </button>
        <span className="ml-auto font-mono text-xs text-ink" data-testid="level-legend" aria-live="polite">
          {(hover ?? points[points.length - 1]) ? `${(hover ?? points[points.length - 1])?.date}  level ${(hover ?? points[points.length - 1])?.level}` : ""}
        </span>
      </div>
      <div ref={ref} className="w-full" data-testid="line-chart" />
    </div>
  );
}
