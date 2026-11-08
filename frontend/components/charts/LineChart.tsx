"use client";

import { ColorType, createChart, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";
import { plotNumber } from "@/lib/formatting";

export function LineChart({ points, color = "#0f172a" }: { points: { date: string; level: string }[]; color?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const chart = createChart(el, {
      height: 300,
      layout: { background: { type: ColorType.Solid, color: "#ffffff" }, textColor: "#475569" },
      grid: { vertLines: { color: "#f1f5f9" }, horzLines: { color: "#f1f5f9" } },
      rightPriceScale: { borderColor: "#e2e8f0", mode: 1 },
      timeScale: { borderColor: "#e2e8f0" },
    });
    const line = chart.addLineSeries({ color, lineWidth: 2 });
    line.setData(points.map((p) => ({ time: p.date as Time, value: plotNumber(p.level) })));
    chart.timeScale().fitContent();
    const resize = () => chart.applyOptions({ width: el.clientWidth });
    resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.remove();
    };
  }, [points, color]);
  return <div ref={ref} className="w-full" data-testid="line-chart" />;
}
