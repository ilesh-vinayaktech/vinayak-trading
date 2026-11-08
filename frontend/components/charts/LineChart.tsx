"use client";

import { ColorType, createChart, PriceScaleMode, type Time } from "lightweight-charts";
import { useEffect, useRef, useState } from "react";
import { plotNumber } from "@/lib/formatting";

export function LineChart({ points, color = "#0f172a" }: { points: { date: string; level: string }[]; color?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [log, setLog] = useState(true);
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
    const line = chart.addLineSeries({ color, lineWidth: 2, priceFormat: { type: "price", precision: 0, minMove: 1 } });
    line.setData(points.map((p) => ({ time: p.date as Time, value: plotNumber(p.level) })));
    chart.timeScale().fitContent();
    const resize = () => chart.applyOptions({ width: el.clientWidth });
    resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
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
      </div>
      <div ref={ref} className="w-full" data-testid="line-chart" />
    </div>
  );
}
