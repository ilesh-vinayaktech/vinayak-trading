"use client";

import { LineSeries, LineStyle, createSeriesMarkers, type ISeriesApi, type Time } from "lightweight-charts";
import { useEffect, type MutableRefObject } from "react";
import { KINDS, type Analysis, type AutoKind } from "@/lib/autoAnalysis";
import { barTime } from "@/lib/timeframes";
import type { ChartHandles } from "./DrawingTools";

const STYLE = { solid: LineStyle.Solid, dashed: LineStyle.Dashed, dotted: LineStyle.Dotted } as const;
type TimedBar = { date: string; time?: number };

/** Draws the analysis on the chart (price lines for levels, a line series for each trend line) and takes it all off again when switched off or changed. */
export function useAutoLines(handles: MutableRefObject<ChartHandles | null>, ready: number, bars: TimedBar[], analysis: Analysis, on: boolean, kinds: ReadonlySet<AutoKind>) {
  useEffect(() => {
    const h = handles.current;
    if (!h || !on) return;
    const made: ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[] = [];
    const extra: ISeriesApi<"Line">[] = [];
    const main = h.series as ISeriesApi<"Candlestick">;
    for (const l of analysis.lines) {
      if (!kinds.has(l.kind)) continue;
      made.push(main.createPriceLine({ price: l.price, color: l.color, lineWidth: l.width, lineStyle: STYLE[l.dash], axisLabelVisible: true, title: l.label }));
    }
    // a trend line is drawn with its layer; a channel's base line comes with the channel when the Trend lines layer is off, so the pair reads as a channel
    const drawn: typeof analysis.trends = [];
    for (const t of analysis.trends) {
      if (!kinds.has(t.kind)) continue;
      drawn.push(t);
      if (t.kind === "channels" && t.base && !kinds.has("trend")) drawn.push(t.base);
    }
    for (const t of drawn) {
      const a = bars[t.fromIndex], b = bars[t.toIndex];
      if (!a || !b) continue;
      const s = h.chart.addSeries(LineSeries, { color: t.color, lineWidth: t.width, lineStyle: STYLE[t.dash], lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false, title: t.label, autoscaleInfoProvider: () => null });
      s.setData([{ time: barTime(a) as Time, value: t.fromPrice }, { time: barTime(b) as Time, value: t.toPrice }]);
      extra.push(s);
    }
    // candlestick patterns: a second markers layer on the price series, apart from the corporate-action and decision markers the chart draws itself
    const marks = kinds.has("patterns")
      ? analysis.markers.flatMap((m) => { const b = bars[m.index]; return b ? [{ time: barTime(b) as Time, position: m.position, shape: m.shape, color: m.color, text: m.text }] : []; })
      : [];
    const layer = marks.length ? createSeriesMarkers(h.series, marks) : null;
    return () => {
      // eslint-disable-next-line react-hooks/exhaustive-deps -- read at cleanup on purpose: is this still the chart the lines were drawn on?
      if (handles.current?.chart !== h.chart) return; // the chart was replaced: its lines went with it
      for (const p of made) main.removePriceLine(p);
      for (const s of extra) h.chart.removeSeries(s);
      layer?.detach();
    };
  }, [handles, ready, bars, analysis, on, kinds]);
}

const Glyph = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M3 17l5-6 4 3 8-9" />
    <path d="M3 8h18M3 20h18" strokeDasharray="2 3" />
  </svg>
);

/** The rail button that switches the automatic drawings on or off, and beside it a list of what they are with a checkbox for each. */
export function AutoToolButton({ on, onToggle, kinds, onKinds, counts, open, onOpen }: { on: boolean; onToggle: () => void; kinds: ReadonlySet<AutoKind>; onKinds: (k: Set<AutoKind>) => void; counts: Record<AutoKind, number>; open: boolean; onOpen: (v: boolean) => void }) {
  const flip = (k: AutoKind) => {
    const next = new Set(kinds);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    onKinds(next);
  };
  return (
    <div className="relative">
      <button type="button" title="Auto analysis: draw support and resistance, trend lines, pivots, Fibonacci, range and volume profile from the chart's own data" aria-label="Auto analysis" aria-pressed={on} onClick={onToggle} className={`relative flex h-9 w-9 items-center justify-center rounded-md transition-colors ${on ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-100"}`}>
        <Glyph />
      </button>
      {on && open ? (
        <div role="group" aria-label="Auto analysis layers" className="absolute bottom-0 left-full z-30 ml-2 max-h-[min(24rem,60vh)] w-64 overflow-y-auto rounded-lg border border-line bg-white p-3 text-left shadow-lg">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm font-semibold">Auto analysis</span>
            <button type="button" aria-label="Close the layer list" onClick={() => onOpen(false)} className="rounded px-1.5 text-slate-500 hover:bg-slate-100">×</button>
          </div>
          <ul className="space-y-1.5">
            {KINDS.map((k) => (
              <li key={k.kind}>
                <label className="flex cursor-pointer items-center gap-2 text-sm" title={k.hint}>
                  <input type="checkbox" checked={kinds.has(k.kind)} onChange={() => flip(k.kind)} />
                  <span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: k.color }} />
                  <span>{k.label} <span className="text-xs text-slate-500">({counts[k.kind]})</span></span>
                </label>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-xs text-slate-500">Hover a layer for what it is. These show where the price paused before, not where it will go. Green is the only candlestick pattern that beat a random stock in past data; grey ones are shapes, not signals.</p>
        </div>
      ) : null}
      {on && !open ? <button type="button" aria-label="Show the layer list" title="Show the layer list" onClick={() => onOpen(true)} className="absolute -right-1 top-1/2 flex h-5 w-3 -translate-y-1/2 items-center justify-center rounded-sm bg-white text-[10px] text-slate-500 shadow-sm ring-1 ring-line">›</button> : null}
    </div>
  );
}
