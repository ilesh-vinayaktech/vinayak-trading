"use client";

import {
  ColorType,
  CrosshairMode,
  LineStyle,
  createChart,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { useCallback, useEffect, useRef, useState } from "react";
import { addDrawing, load, save, undoDrawing, type Drawing } from "@/lib/drawings";
import { plotNumber } from "@/lib/formatting";
import type { Bars, InstrumentDetail } from "@/lib/schemas";

type Action = InstrumentDetail["actions"][number];
type Bar = Bars["bars"][number];
type Tool = "cursor" | "h" | "t";

const TOOLS: { key: Tool; label: string; hint: string }[] = [
  { key: "cursor", label: "Cursor", hint: "pan and zoom" },
  { key: "h", label: "Horizontal line", hint: "click a price level" },
  { key: "t", label: "Trend line", hint: "click two points" },
];

type Projection = {
  trend: { i: number; x1: number; y1: number; x2: number; y2: number }[];
  anchor: { x: number; y: number } | null;
};

/** Screen coordinates of the trend lines for the chart as it is NOW. A chart that was just replaced
 * (instrument or price basis changed) can be disposed mid-render: that yields no lines, not an error. */
function project(h: { chart: IChartApi; series: ISeriesApi<"Candlestick"> } | null, drawings: Drawing[], pending: { t: string; p: number } | null): Projection {
  if (!h) return { trend: [], anchor: null };
  try {
    const trend = drawings.flatMap((d, i) => {
      if (d.type !== "t") return [];
      const x1 = h.chart.timeScale().timeToCoordinate(d.t1 as Time);
      const x2 = h.chart.timeScale().timeToCoordinate(d.t2 as Time);
      const y1 = h.series.priceToCoordinate(d.p1);
      const y2 = h.series.priceToCoordinate(d.p2);
      return x1 === null || x2 === null || y1 === null || y2 === null ? [] : [{ i, x1, y1, x2, y2 }];
    });
    const x = pending ? h.chart.timeScale().timeToCoordinate(pending.t as Time) : null;
    const y = pending ? h.series.priceToCoordinate(pending.p) : null;
    return { trend, anchor: x === null || y === null ? null : { x, y } };
  } catch {
    return { trend: [], anchor: null };
  }
}

/** Candles and volume exactly as the API returned them (prices are parsed only to be drawn). The
 * data is OUR database's: the chart library only renders it. Corporate actions are markers on the
 * first bar on or after their ex-date. Drawings are browser-only notes kept per instrument and
 * price basis; they never feed anything else. */
export function PriceChart({ bars, actions, instrumentId, adjust }: { bars: Bar[]; actions: Action[]; instrumentId: number; adjust: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const handles = useRef<{ chart: IChartApi; series: ISeriesApi<"Candlestick"> } | null>(null);
  const linesRef = useRef<IPriceLine[]>([]); // the horizontal lines currently on the chart
  const toolRef = useRef<Tool>("cursor");
  const pendingRef = useRef<{ t: string; p: number } | null>(null);
  const [hover, setHover] = useState<Bar | null>(null);
  const [tool, setToolState] = useState<Tool>("cursor");
  const [pending, setPending] = useState<{ t: string; p: number } | null>(null);
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [ready, setReady] = useState(0); // bumps each time a fresh chart exists
  const [, setTick] = useState(0); // re-project trend lines when the view moves

  const setTool = useCallback((t: Tool) => {
    toolRef.current = t;
    pendingRef.current = null;
    setPending(null);
    setToolState(t);
  }, []);

  // drawings belong to one instrument and one price basis
  useEffect(() => {
    setDrawings(load(instrumentId, adjust));
    setLoaded(true);
    setTool("cursor");
  }, [instrumentId, adjust, setTool]);
  useEffect(() => {
    if (loaded) save(instrumentId, adjust, drawings);
  }, [drawings, loaded, instrumentId, adjust]);

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
    const onClick = (p: MouseEventParams<Time>) => {
      if (handles.current?.chart !== chart) return; // a superseded chart must not draw
      const t = toolRef.current;
      if (t === "cursor" || typeof p.time !== "string" || !p.point) return;
      const price = candles.coordinateToPrice(p.point.y);
      if (price === null) return;
      if (t === "h") {
        setDrawings((d) => addDrawing(d, { type: "h", price }));
      } else if (pendingRef.current === null) {
        pendingRef.current = { t: p.time, p: price };
        setPending(pendingRef.current);
      } else {
        const a = pendingRef.current;
        pendingRef.current = null;
        setPending(null);
        setDrawings((d) => addDrawing(d, { type: "t", t1: a.t, p1: a.p, t2: p.time as string, p2: price }));
      }
    };
    chart.subscribeCrosshairMove(onMove);
    chart.subscribeClick(onClick);
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
    // the library lays the chart out on the next frames: project the trend lines again once it has
    const frame = requestAnimationFrame(() => requestAnimationFrame(() => setTick((n) => n + 1)));
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", resize);
      chart.unsubscribeCrosshairMove(onMove);
      chart.unsubscribeClick(onClick);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRange);
      // Take the price lines off while the chart is alive: removing a chart that still carries
      // them makes the library paint a disposed chart a frame later ("Object is disposed").
      for (const l of linesRef.current) candles.removePriceLine(l);
      linesRef.current = [];
      handles.current = null;
      chart.remove();
    };
  }, [bars, actions]);

  // horizontal lines are native price lines (labelled on the price axis)
  useEffect(() => {
    const h = handles.current;
    if (!h) return;
    const made: IPriceLine[] = drawings.flatMap((d) =>
      d.type === "h" ? [h.series.createPriceLine({ price: d.price, color: "#7c3aed", lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: true, title: "" })] : [],
    );
    linesRef.current = made;
    return () => {
      // only while this chart is still the live one; otherwise its lines were already removed
      if (handles.current?.series !== h.series) return;
      for (const l of made) h.series.removePriceLine(l);
      linesRef.current = [];
    };
  }, [drawings, ready]);

  const shown = hover ?? bars[bars.length - 1];
  const { trend, anchor } = project(handles.current, drawings, pending);

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2" role="toolbar" aria-label="Chart tools">
        {TOOLS.map((t) => (
          <button key={t.key} type="button" aria-pressed={tool === t.key} title={t.hint} onClick={() => setTool(t.key)} className={`rounded px-3 py-1 text-xs ${tool === t.key ? "bg-slate-900 text-white" : "bg-slate-100 text-ink-soft hover:bg-slate-200"}`}>
            {t.label}
          </button>
        ))}
        <button type="button" disabled={drawings.length === 0} onClick={() => setDrawings((d) => undoDrawing(d))} className="rounded bg-slate-100 px-3 py-1 text-xs text-ink-soft hover:bg-slate-200 disabled:opacity-40">
          Undo
        </button>
        <button type="button" disabled={drawings.length === 0} onClick={() => setDrawings([])} className="rounded bg-slate-100 px-3 py-1 text-xs text-ink-soft hover:bg-slate-200 disabled:opacity-40">
          Clear drawings
        </button>
        <button type="button" disabled title="Needs a stored backtest with its trades; none exist yet" className="ml-auto cursor-not-allowed rounded border border-dashed border-line px-3 py-1 text-xs text-ink-faint">
          Load strategy run (not available yet)
        </button>
      </div>
      <p className="mb-2 min-h-4 text-xs text-ink-soft" data-testid="tool-hint">
        {tool === "cursor" ? "Drawings are notes saved in this browser for this instrument and price basis." : tool === "h" ? "Click the chart to place a horizontal line at that price." : pending ? "Click the second point of the trend line." : "Click the first point of the trend line."}
      </p>
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
      <div className={`relative ${tool === "cursor" ? "" : "cursor-crosshair"}`}>
        <div ref={ref} className="w-full" data-testid="price-chart" />
        <svg style={{ willChange: "transform" }} className="pointer-events-none absolute inset-0 z-10 h-full w-full" aria-hidden="true" data-testid="drawing-layer">
          {trend.map((l) => (
            <line key={l.i} x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} stroke="#7c3aed" strokeWidth={1.5} />
          ))}
          {anchor ? <circle cx={anchor.x} cy={anchor.y} r={4} fill="#7c3aed" /> : null}
        </svg>
      </div>
    </div>
  );
}
