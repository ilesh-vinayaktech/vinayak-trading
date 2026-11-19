"use client";

import { useQuery } from "@tanstack/react-query";
import { LineSeries, LineStyle, type ISeriesApi, type Time } from "lightweight-charts";
import { useEffect, type MutableRefObject } from "react";
import { api } from "@/lib/api/client";
import type { RiseOdds } from "@/lib/schemas";
import type { ChartHandles } from "./DrawingTools";

const PANE_HEIGHT = 140;
const LINES = [
  { title: "Own direction", color: "#2563eb" },
  { title: "Against other stocks", color: "#f59e0b" },
] as const;

/** The rise odds of the stock (the model's chance of rising, and of beating the median stock, over the next 5 sessions, scored each night) as a pane under the chart, one line per model, with a dashed 50% line.
 * Daily candles only (the scores are daily); `pane` is the pane index below the indicator panes. Takes its series off again when switched off or changed. */
export function useRiseScorePane(handles: MutableRefObject<ChartHandles | null>, ready: number, on: boolean, symbol: string, firstDay: string | undefined, pane: number) {
  const own = useQuery({ queryKey: ["market", "rise-odds", symbol, "up"], queryFn: () => api.marketRiseOdds(symbol, "up"), retry: false, enabled: on, staleTime: 10 * 60_000 });
  const rel = useQuery({ queryKey: ["market", "rise-odds", symbol, "rel"], queryFn: () => api.marketRiseOdds(symbol, "rel"), retry: false, enabled: on, staleTime: 10 * 60_000 });
  const data: (RiseOdds | undefined)[] = [own.data, rel.data];
  useEffect(() => {
    const h = handles.current;
    if (!h || !on || data.every((d) => !d || d.history.length === 0)) return;
    const made: ISeriesApi<"Line">[] = [];
    LINES.forEach((l, i) => {
      const hist = data[i]?.history.filter((p) => !firstDay || p.day >= firstDay) ?? [];
      if (hist.length === 0) return;
      const s = h.chart.addSeries(LineSeries, { color: l.color, lineWidth: 2, title: l.title, priceLineVisible: false, priceFormat: { type: "custom", formatter: (v: number) => `${v.toFixed(0)}%` } }, pane);
      s.setData(hist.map((p) => ({ time: p.day as Time, value: p.prob * 100 })));
      if (made.length === 0) s.createPriceLine({ price: 50, color: "#cbd5e1", lineStyle: LineStyle.Dashed, lineWidth: 1, axisLabelVisible: false });
      made.push(s);
    });
    const frame = requestAnimationFrame(() => h.chart.panes()[pane]?.setHeight(PANE_HEIGHT));
    return () => {
      cancelAnimationFrame(frame);
      // eslint-disable-next-line react-hooks/exhaustive-deps -- compares against the chart this effect drew on: the current one may be a replacement
      if (handles.current?.chart !== h.chart) return; // the chart was replaced: its series went with it
      for (const s of made) h.chart.removeSeries(s);
    };
  }, [on, ready, pane, firstDay, own.data, rel.data]); // eslint-disable-line react-hooks/exhaustive-deps
  return { loading: on && (own.isLoading || rel.isLoading), failed: on && own.isError && rel.isError, unscored: on && !!own.data && !!rel.data && !own.data.scored && !rel.data.scored };
}

const Glyph = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 20V4M3 20h18" />
    <path d="M6 15l4-4 3 3 6-7" />
    <path d="M6 9h4" strokeDasharray="2 2" />
  </svg>
);

/** The rail button for the rise score pane. Off for weekly, monthly and intraday candles, where its tooltip says why. */
export function RiseScoreButton({ on, onToggle, daily, loading, failed, unscored }: { on: boolean; onToggle: () => void; daily: boolean; loading: boolean; failed: boolean; unscored: boolean }) {
  const note = !daily ? "Rise score: shown on daily candles only" : failed ? "The rise score could not be loaded" : unscored ? "This stock has not been scored (too little trading, or too little history)" : loading ? "Loading the rise score…" : "Rise score: the model's chance of rising over the next 5 sessions, scored each night, under the chart. A lean, not a signal";
  return (
    <button type="button" title={note} aria-label="Rise score" aria-pressed={on} disabled={!daily} onClick={onToggle} className={`relative flex h-9 w-9 items-center justify-center rounded-md transition-colors disabled:opacity-40 ${on ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-100"}`}>
      <Glyph />
    </button>
  );
}
