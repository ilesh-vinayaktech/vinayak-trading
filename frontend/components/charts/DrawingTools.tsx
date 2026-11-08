"use client";

import type { IChartApi, ISeriesApi, SeriesType, Time } from "lightweight-charts";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { magnet, pick, pickHandle, shapesFor, translated, withHandleAt, anchors, type Projection, type Shape } from "@/lib/drawings/geometry";
import * as H from "@/lib/drawings/history";
import { COLORS, DASHES, DEFAULT_STYLE, GROUPS, load, makeDrawing, save, TOOLS, TOOL_TYPES, type Drawing, type Pt, type Style, type ToolGroup, type ToolType } from "@/lib/drawings/model";
import { Icon } from "./icons";


export type ChartHandles = { chart: IChartApi; series: ISeriesApi<SeriesType> };

/** What the page toolbar needs from the drawing layer. */
export type DrawingApi = { undo: () => void; redo: () => void; canUndo: boolean; canRedo: boolean; count: number; listOpen: boolean; toggleList: () => void };

export const SHORTCUTS: Partial<Record<ToolType, { code: string; label: string }>> = {
  trend: { code: "KeyT", label: "Alt+T" },
  hline: { code: "KeyH", label: "Alt+H" },
  vline: { code: "KeyV", label: "Alt+V" },
  cross: { code: "KeyC", label: "Alt+C" },
  fibret: { code: "KeyF", label: "Alt+F" },
  rect: { code: "KeyR", label: "Alt+R" },
  text: { code: "KeyX", label: "Alt+X" },
};
type Bar = { date: string; open: string; high: string; low: string; close: string };
type Tool = ToolType | "cursor";
type Drag = { kind: "handle"; index: number; original: Drawing } | { kind: "move"; original: Drawing; startX: number; startY: number };

const DASH_ARRAY: Record<string, string | undefined> = { solid: undefined, dashed: "6 4", dotted: "1.5 4" };

/** Chart coordinates <-> (bar date, price) for the chart as it is now; any failure means "not available". */
export function makeProjection(h: ChartHandles | null, bars: Bar[], width: number, height: number): Projection | null {
  if (!h || width <= 0 || height <= 0) return null;
  const idx = new Map(bars.map((b, i) => [b.date, i]));
  const guard = <T,>(f: () => T | null): T | null => {
    try {
      return f();
    } catch {
      return null; // the chart was disposed mid-render
    }
  };
  return {
    width,
    height,
    x: (t) => guard(() => h.chart.timeScale().timeToCoordinate(t as Time)),
    y: (p) => guard(() => h.series.priceToCoordinate(p)),
    time: (x) =>
      guard(() => {
        const l = h.chart.timeScale().coordinateToLogical(x);
        if (l === null || bars.length === 0) return null;
        return bars[Math.max(0, Math.min(bars.length - 1, Math.round(l)))]?.date ?? null;
      }),
    price: (y) => guard(() => h.series.coordinateToPrice(y)),
    index: (t) => idx.get(t) ?? null,
  };
}

function ShapeEl({ s, i, faint }: { s: Shape; i: number; faint: boolean }) {
  const o = (v?: number) => (faint ? 0.45 : (v ?? 1));
  if (s.kind === "arrowhead") {
    const { x, y, angle, size, color } = s;
    const pts = [[0, 0], [-size, size / 2.4], [-size, -size / 2.4]].map(([px, py]) => `${x + (px as number) * Math.cos(angle) - (py as number) * Math.sin(angle)},${y + (px as number) * Math.sin(angle) + (py as number) * Math.cos(angle)}`);
    return <polygon key={i} points={pts.join(" ")} fill={color} opacity={o()} />;
  }
  if (s.kind === "text") {
    const w = s.text.length * 6.4 + 8;
    const x0 = s.anchor === "middle" ? s.x - w / 2 : s.anchor === "end" ? s.x - w : s.x - 2;
    return (
      <g key={i} opacity={o()}>
        <rect x={x0} y={s.y - 12} width={w} height={16} rx={3} fill="#ffffff" opacity={0.85} />
        <text x={x0 + 4} y={s.y} fontSize={11} fontFamily="ui-monospace, monospace" fill={s.color}>
          {s.text}
        </text>
      </g>
    );
  }
  const common = { stroke: s.stroke.color, strokeWidth: s.stroke.width, strokeDasharray: DASH_ARRAY[s.stroke.dash], strokeOpacity: o(s.stroke.opacity), strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  const fill = s.kind !== "line" && s.fill ? { fill: s.fill, fillOpacity: o(s.fillOpacity) } : { fill: "none" };
  if (s.kind === "line") return <line key={i} x1={s.x1} y1={s.y1} x2={s.x2} y2={s.y2} {...common} />;
  if (s.kind === "rect") return <rect key={i} x={s.x} y={s.y} width={s.w} height={s.h} {...common} {...fill} />;
  if (s.kind === "ellipse") return <ellipse key={i} cx={s.cx} cy={s.cy} rx={s.rx} ry={s.ry} {...common} {...fill} />;
  const d = s.pts.map(([x, y], k) => `${k === 0 ? "M" : "L"}${x},${y}`).join(" ") + (s.closed ? " Z" : "");
  return <path key={i} d={d} {...common} {...fill} />;
}

export function DrawingTools({ handles, ready, tick, bars, instrumentId, adjust, topbar, above, overlay, children }: { handles: ChartHandles | null; ready: number; tick: number; bars: Bar[]; instrumentId: number; adjust: string; topbar?: (api: DrawingApi) => ReactNode; above?: ReactNode; overlay?: ReactNode; children: ReactNode }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [hist, setHist] = useState<H.History>(() => H.initial());
  const [loaded, setLoaded] = useState(false);
  const [tool, setToolState] = useState<Tool>("cursor");
  const [lastIn, setLastIn] = useState<Partial<Record<ToolGroup, ToolType>>>({});
  const [openGroup, setOpenGroup] = useState<ToolGroup | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [live, setLive] = useState<Drawing | null>(null); // a drawing being dragged (committed on release)
  const [draft, setDraft] = useState<{ type: ToolType; pts: Pt[] } | null>(null);
  const [hover, setHover] = useState<Pt | null>(null);
  const [snap, setSnap] = useState(true);
  const [allHidden, setAllHidden] = useState(false);
  const [listOpen, setListOpen] = useState(false);
  const [style, setStyle] = useState<Style>(DEFAULT_STYLE);
  const [cursor, setCursor] = useState("");
  const [size, setSize] = useState({ w: 0, h: 0 });
  const drag = useRef<Drag | null>(null);
  const brushing = useRef(false);

  // --- latest state for the native listeners ---
  const latest = useRef({ tool, hist, selected, draft, snap, style, live, bars });
  latest.current = { tool, hist, selected, draft, snap, style, live, bars };

  const list = useMemo(() => hist.list.map((d) => (live && d.id === live.id ? live : d)), [hist.list, live]);

  // drawings belong to one instrument and one price basis
  useEffect(() => {
    setHist(H.reset(load(instrumentId, adjust)));
    setLoaded(true);
    setSelected(null);
    setDraft(null);
    setToolState("cursor");
  }, [instrumentId, adjust]);
  useEffect(() => {
    if (loaded) save(instrumentId, adjust, hist.list);
  }, [hist.list, loaded, instrumentId, adjust]);

  // plot area size (the chart minus its price and time axes)
  useEffect(() => {
    const h = handles;
    const el = wrap.current;
    if (!h || !el) return;
    try {
      const mainPane = h.chart.panes()[0];
      const paneH = mainPane ? mainPane.getHeight() : el.clientHeight - h.chart.timeScale().height();
      setSize({ w: Math.max(0, h.chart.timeScale().width()), h: Math.max(0, paneH) });
    } catch {
      /* chart gone */
    }
  }, [handles, ready, tick]);

  const proj = useMemo(() => makeProjection(handles, bars, size.w, size.h), [handles, bars, size, tick, ready]); // eslint-disable-line react-hooks/exhaustive-deps
  const projRef = useRef(proj);
  projRef.current = proj;

  const setTool = useCallback((t: Tool) => {
    setToolState(t);
    setDraft(null);
    setOpenGroup(null);
    brushing.current = false;
    if (t !== "cursor") {
      setSelected(null);
      setLastIn((m) => ({ ...m, [TOOLS[t].group]: t }));
    }
  }, []);

  const commitNew = useCallback((d: Drawing) => {
    setHist((h) => H.add(h, d));
    setSelected(d.id);
    setDraft(null);
    setToolState("cursor");
  }, []);

  // --- native pointer handling: runs before the chart so a drag on a drawing does not pan the chart ---
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const pos = (e: PointerEvent | MouseEvent) => {
      const r = el.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    const inPlot = (x: number, y: number) => {
      const p = projRef.current;
      return p !== null && x >= 0 && y >= 0 && x <= p.width && y <= p.height;
    };
    const pointAt = (x: number, y: number): Pt | null => {
      const p = projRef.current;
      if (!p) return null;
      const t = p.time(x);
      let price = p.price(y);
      if (t === null || price === null) return null;
      if (latest.current.snap) {
        const b = latest.current.bars.find((q) => q.date === t);
        const snapped = b ? magnet({ open: +b.open, high: +b.high, low: +b.low, close: +b.close }, p, y) : null;
        if (snapped !== null) price = snapped;
      }
      return { t, p: price };
    };
    const stop = (e: Event) => {
      e.stopPropagation();
      e.preventDefault();
    };

    const down = (e: PointerEvent) => {
      if (e.button !== 0) return;
      const { x, y } = pos(e);
      const p = projRef.current;
      if (!p || !inPlot(x, y)) return;
      const s = latest.current;
      if (s.tool !== "cursor") {
        const need = TOOLS[s.tool].points;
        const pt = pointAt(x, y);
        if (!pt) return;
        stop(e);
        if (need === "free") {
          brushing.current = true;
          setDraft({ type: s.tool, pts: [pt] });
          return;
        }
        const pts = [...(s.draft?.pts ?? []), pt];
        if (pts.length >= need) {
          const text = s.tool === "text" ? "Text" : undefined;
          commitNew(makeDrawing(s.tool, pts, s.style, text));
        } else setDraft({ type: s.tool, pts });
        return;
      }
      // cursor: a handle of the selected drawing, then any drawing
      const sel = s.selected ? s.hist.list.find((d) => d.id === s.selected) : undefined;
      if (sel && !sel.locked && !sel.hidden) {
        const hi = pickHandle(sel, p, x, y);
        if (hi >= 0) {
          drag.current = { kind: "handle", index: hi, original: sel };
          stop(e);
          return;
        }
      }
      const hit = pick(s.hist.list, p, x, y);
      if (hit) {
        setSelected(hit.id);
        if (!hit.locked) drag.current = { kind: "move", original: hit, startX: x, startY: y };
        stop(e);
        return;
      }
      setSelected(null); // empty space: let the chart pan
    };

    const move = (e: PointerEvent) => {
      const { x, y } = pos(e);
      const p = projRef.current;
      if (!p) return;
      const s = latest.current;
      const dg = drag.current;
      if (dg) {
        const next = dg.kind === "handle" ? withHandleAt(dg.original, dg.index, p, x, y) : translated(dg.original, p, x - dg.startX, y - dg.startY);
        if (next) setLive(next);
        stop(e);
        return;
      }
      if (s.tool !== "cursor") {
        const pt = inPlot(x, y) ? pointAt(x, y) : null;
        setHover(pt);
        if (brushing.current && pt) setDraft((d) => (d ? { ...d, pts: [...d.pts, pt].slice(-400) } : d));
        return;
      }
      if (inPlot(x, y)) {
        const sel = s.selected ? s.hist.list.find((d) => d.id === s.selected) : undefined;
        if (sel && !sel.locked && pickHandle(sel, p, x, y) >= 0) setCursor("grab");
        else setCursor(pick(s.hist.list, p, x, y) ? "move" : "");
      } else setCursor("");
    };

    const up = (e: PointerEvent) => {
      const s = latest.current;
      if (brushing.current) {
        brushing.current = false;
        if (s.draft && s.draft.pts.length > 1) commitNew(makeDrawing(s.draft.type, s.draft.pts, s.style));
        else setDraft(null);
        stop(e);
        return;
      }
      if (drag.current) {
        const done = s.live;
        drag.current = null;
        if (done) setHist((h) => H.update(h, done));
        setLive(null);
        stop(e);
      }
    };

    const events = ["pointerdown", "mousedown", "touchstart"] as const;
    const swallow = (e: Event) => {
      // the chart listens for mouse/touch events too: stop those whenever the pointer event was ours
      const s = latest.current;
      const me = e as MouseEvent;
      const r = el.getBoundingClientRect();
      const x = me.clientX - r.left;
      const y = me.clientY - r.top;
      const p = projRef.current;
      if (!p || !inPlot(x, y)) return;
      if (s.tool !== "cursor") return stop(e);
      const sel = s.selected ? s.hist.list.find((d) => d.id === s.selected) : undefined;
      if ((sel && !sel.locked && pickHandle(sel, p, x, y) >= 0) || pick(s.hist.list, p, x, y)) stop(e);
    };
    el.addEventListener("pointerdown", down, true);
    for (const t of events.slice(1)) el.addEventListener(t, swallow, true);
    el.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
    return () => {
      el.removeEventListener("pointerdown", down, true);
      for (const t of events.slice(1)) el.removeEventListener(t, swallow, true);
      el.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
    };
  }, [commitNew]);

  // keyboard: delete, escape, undo/redo (not while typing in a field)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT")) return;
      const s = latest.current;
      if (e.altKey && !e.ctrlKey && !e.metaKey) {
        const hit = TOOL_TYPES.find((tt) => SHORTCUTS[tt]?.code === e.code);
        if (hit) {
          e.preventDefault();
          setTool(hit);
          return;
        }
      }
      if ((e.key === "Delete" || e.key === "Backspace") && s.selected) {
        e.preventDefault();
        const sel = s.hist.list.find((d) => d.id === s.selected);
        if (sel && !sel.locked) {
          setHist((h) => H.remove(h, sel.id));
          setSelected(null);
        }
      } else if (e.key === "Escape") {
        setDraft(null);
        setToolState("cursor");
        setSelected(null);
        brushing.current = false;
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        setHist((h) => (e.shiftKey ? H.redo(h) : H.undo(h)));
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
        e.preventDefault();
        setHist((h) => H.redo(h));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setTool]);

  // --- what to paint ---
  const preview = useMemo<Drawing | null>(() => {
    if (!draft || draft.pts.length === 0) return null;
    const need = TOOLS[draft.type].points;
    if (need === "free") return makeDrawing(draft.type, draft.pts, style);
    const pts = hover ? [...draft.pts, ...Array<Pt>(Math.max(0, need - draft.pts.length)).fill(hover)] : [...draft.pts, ...Array<Pt>(Math.max(0, need - draft.pts.length)).fill(draft.pts[draft.pts.length - 1] as Pt)];
    return makeDrawing(draft.type, pts, style);
  }, [draft, hover, style]);

  const visible = allHidden ? [] : list.filter((d) => !d.hidden);
  const selectedDrawing = list.find((d) => d.id === selected) ?? null;
  const paint = (d: Drawing, faint = false) => (proj ? shapesFor(d, proj).map((s, i) => <ShapeEl key={`${d.id}-${i}`} s={s} i={i} faint={faint} />) : null);
  const handlesXY = proj && selectedDrawing && !selectedDrawing.locked ? anchors(selectedDrawing, proj) : [];

  const patchSelected = (patch: Partial<Drawing>) => {
    if (selectedDrawing) setHist((h) => H.update(h, { ...selectedDrawing, ...patch }));
  };
  const setStyleOf = (patch: Partial<Style>) => {
    setStyle((s) => ({ ...s, ...patch }));
    if (selectedDrawing) patchSelected({ style: { ...selectedDrawing.style, ...patch } });
  };

  const hint = tool === "cursor" ? (selectedDrawing ? "Drag a handle to reshape, drag the drawing to move it, Delete removes it." : "Pick a tool to draw. Drawings are notes saved in this browser for this instrument and price basis.") : draft ? `${TOOLS[tool].label}: ${draft.pts.length} of ${TOOLS[tool].points === "free" ? "…" : TOOLS[tool].points} placed. ${TOOLS[tool].hint}. Esc cancels.` : `${TOOLS[tool].label}: ${TOOLS[tool].hint}. Esc cancels.`;

  const api: DrawingApi = { undo: () => setHist((h) => H.undo(h)), redo: () => setHist((h) => H.redo(h)), canUndo: hist.past.length > 0, canRedo: hist.future.length > 0, count: list.length, listOpen, toggleList: () => setListOpen((v) => !v) };
  const shownStyle = selectedDrawing?.style ?? style;
  const railBtn = (active: boolean) => `relative flex h-9 w-9 items-center justify-center rounded-md transition-colors ${active ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-100"}`;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {topbar?.(api)}
      <div className="flex min-h-0 flex-1">
        {/* ---- left tool rail ---- */}
        <div className="flex w-[52px] shrink-0 flex-col items-center gap-0.5 overflow-visible border-r border-line bg-white py-2" role="toolbar" aria-label="Drawing tools" aria-orientation="vertical">
          <button type="button" title="Cursor" aria-label="Cursor" aria-pressed={tool === "cursor"} onClick={() => setTool("cursor")} className={railBtn(tool === "cursor")}>
            <Icon name="cursor" />
          </button>
          <span className="my-1 h-px w-7 bg-line" aria-hidden="true" />
          {GROUPS.map((g) => {
            const items = TOOL_TYPES.filter((t) => TOOLS[t].group === g);
            const shownTool = (tool !== "cursor" && TOOLS[tool].group === g ? tool : lastIn[g]) ?? (items[0] as ToolType);
            const active = tool !== "cursor" && TOOLS[tool].group === g;
            return (
              <div key={g} className="group relative">
                <button type="button" title={`${TOOLS[shownTool].label}${SHORTCUTS[shownTool] ? ` (${SHORTCUTS[shownTool]?.label})` : ""}`} aria-label={TOOLS[shownTool].label} aria-pressed={active} data-group={g} onClick={() => setTool(shownTool)} className={railBtn(active)}>
                  <Icon name={shownTool} />
                </button>
                <button type="button" aria-label={`${g} tools`} aria-haspopup="menu" aria-expanded={openGroup === g} data-flyout={g} onClick={() => setOpenGroup(openGroup === g ? null : g)} className="absolute -right-1 top-1/2 flex h-5 w-3 -translate-y-1/2 items-center justify-center rounded-sm bg-white text-slate-400 opacity-0 shadow-sm ring-1 ring-line hover:text-slate-800 group-hover:opacity-100 focus-visible:opacity-100">
                  <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true"><path d="M2.5 1l3 3-3 3" fill="none" stroke="currentColor" strokeWidth="1.4" /></svg>
                </button>
                {openGroup === g ? (
                  <div role="menu" aria-label={g} className="absolute left-full top-0 z-40 ml-2 w-72 rounded-lg border border-line bg-white py-1.5 shadow-xl">
                    <div className="px-3 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">{g}</div>
                    {items.map((t) => (
                      <button key={t} type="button" role="menuitem" data-tool={t} onClick={() => setTool(t)} className="flex w-full items-center gap-3 px-3 py-2 text-left text-[13px] text-slate-800 hover:bg-slate-100">
                        <Icon name={t} className="text-slate-600" />
                        <span className="flex-1">{TOOLS[t].label}</span>
                        {SHORTCUTS[t] ? <span className="text-[11px] text-slate-400">{SHORTCUTS[t]?.label}</span> : null}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
            );
          })}
          <span className="my-1 h-px w-7 bg-line" aria-hidden="true" />
          <button type="button" title="Magnet: snap to open, high, low, close" aria-label="Magnet" aria-pressed={snap} onClick={() => setSnap((v) => !v)} className={railBtn(snap)}>
            <Icon name="magnet" />
          </button>
          <button type="button" title={allHidden ? "Show all drawings" : "Hide all drawings"} aria-label={allHidden ? "Show all" : "Hide all"} aria-pressed={allHidden} disabled={list.length === 0} onClick={() => setAllHidden((v) => !v)} className={`${railBtn(allHidden)} disabled:opacity-35`}>
            <Icon name={allHidden ? "eyeoff" : "eye"} />
          </button>
          <button type="button" title="Remove all drawings" aria-label="Clear drawings" disabled={list.length === 0} onClick={() => { setHist((h) => H.clear(h)); setSelected(null); }} className={`${railBtn(false)} disabled:opacity-35`}>
            <Icon name="trash" />
          </button>
        </div>

        {/* ---- chart area ---- */}
        <div className="relative min-w-0 flex-1">
          <div ref={wrap} className="relative h-full" data-draw-cursor={tool !== "cursor" ? "crosshair" : cursor}>
            {children}
            <svg className="pointer-events-none absolute left-0 top-0 z-10" width={size.w} height={size.h} style={{ willChange: "transform", overflow: "hidden" }} aria-hidden="true" data-testid="drawing-layer">
              {visible.map((d) => (
                <g key={d.id} data-drawing={d.type} data-selected={d.id === selected}>
                  {paint(d)}
                </g>
              ))}
              {preview ? <g opacity={0.8} data-testid="draft">{paint(preview, true)}</g> : null}
              {handlesXY.map((q, i) => (
                <circle key={i} cx={q.x} cy={q.y} r={5} fill="#ffffff" stroke="#0f172a" strokeWidth={1.5} data-testid="handle" />
              ))}
            </svg>
          </div>
          <div className="pointer-events-none absolute left-3 top-2 z-20">{above}</div>
          {overlay}

          {/* floating properties bar, like a charting terminal's: only while something is selected */}
          {selectedDrawing ? (
            <div role="group" aria-label="Drawing properties" className="absolute left-1/2 top-14 z-30 flex -translate-x-1/2 items-center gap-1 rounded-lg border border-line bg-white px-2 py-1 shadow-lg">
              <span className="px-1 text-[11px] font-medium text-slate-500">{TOOLS[selectedDrawing.type].label}</span>
              <span className="h-5 w-px bg-line" />
              {COLORS.map((c) => (
                <button key={c} type="button" aria-label={`Colour ${c}`} aria-pressed={shownStyle.color === c} onClick={() => setStyleOf({ color: c })} className="h-5 w-5 rounded-full" style={{ background: c, boxShadow: shownStyle.color === c ? "0 0 0 2px #fff, 0 0 0 4px #0f172a" : "none" }} />
              ))}
              <span className="h-5 w-px bg-line" />
              <select aria-label="Line width" value={shownStyle.width} onChange={(e) => setStyleOf({ width: Number(e.target.value) })} className="rounded border border-line bg-white px-1 py-0.5 text-xs">
                {[1, 2, 3, 4].map((w) => (
                  <option key={w} value={w}>{w}px</option>
                ))}
              </select>
              <select aria-label="Line style" value={shownStyle.dash} onChange={(e) => setStyleOf({ dash: e.target.value as Style["dash"] })} className="rounded border border-line bg-white px-1 py-0.5 text-xs">
                {DASHES.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
              {selectedDrawing.type === "text" ? <input aria-label="Text" value={selectedDrawing.text ?? ""} maxLength={200} onChange={(e) => patchSelected({ text: e.target.value })} className="w-40 rounded border border-line px-2 py-0.5 text-xs" /> : null}
              <span className="h-5 w-px bg-line" />
              <button type="button" title={selectedDrawing.locked ? "Unlock" : "Lock"} aria-label={selectedDrawing.locked ? "Unlock" : "Lock"} aria-pressed={selectedDrawing.locked} onClick={() => patchSelected({ locked: !selectedDrawing.locked })} className={`${railBtn(selectedDrawing.locked)} !h-7 !w-7`}>
                <Icon name={selectedDrawing.locked ? "lock" : "unlock"} size={16} />
              </button>
              <button type="button" title="Duplicate" aria-label="Duplicate" onClick={() => { const c = makeDrawing(selectedDrawing.type, selectedDrawing.points.map((q) => ({ ...q })), selectedDrawing.style, selectedDrawing.text); setHist((h) => H.add(h, c)); setSelected(c.id); }} className={`${railBtn(false)} !h-7 !w-7`}>
                <Icon name="copy" size={16} />
              </button>
              <button type="button" title="Delete (Del)" aria-label="Delete" disabled={selectedDrawing.locked} onClick={() => { setHist((h) => H.remove(h, selectedDrawing.id)); setSelected(null); }} className={`${railBtn(false)} !h-7 !w-7 text-red-600 hover:!bg-red-50 disabled:opacity-35`}>
                <Icon name="trash" size={16} />
              </button>
            </div>
          ) : null}

          {tool !== "cursor" || selectedDrawing ? (
            <p className="pointer-events-none absolute bottom-9 left-3 z-20 rounded bg-slate-900/85 px-2.5 py-1 text-[11px] text-white shadow" data-testid="tool-hint">
              {hint}
            </p>
          ) : null}

          {listOpen ? (
            <aside className="absolute bottom-0 right-0 top-0 z-30 w-72 overflow-y-auto border-l border-line bg-white shadow-xl" aria-label="Object tree">
              <div className="sticky top-0 border-b border-line bg-white px-3 py-2 text-xs font-semibold">Object tree ({list.length})</div>
              <ul className="divide-y divide-line text-xs" aria-label="Drawings">
                {list.length === 0 ? <li className="p-3 text-slate-500">No drawings on this chart.</li> : null}
                {list.map((d, i) => (
                  <li key={d.id} className={`flex items-center gap-2 px-3 py-2 ${d.id === selected ? "bg-blue-50" : ""}`}>
                    <Icon name={d.type} size={16} className="text-slate-500" />
                    <button type="button" className="flex-1 truncate text-left" onClick={() => { setSelected(d.id); setToolState("cursor"); }}>
                      {i + 1}. {TOOLS[d.type].label}
                    </button>
                    <button type="button" aria-label={d.hidden ? "Show" : "Hide"} aria-pressed={d.hidden} onClick={() => setHist((h) => H.update(h, { ...d, hidden: !d.hidden }))} className="text-slate-500 hover:text-slate-900">
                      <Icon name={d.hidden ? "eyeoff" : "eye"} size={16} />
                    </button>
                    <button type="button" aria-label={d.locked ? "Unlock" : "Lock"} aria-pressed={d.locked} onClick={() => setHist((h) => H.update(h, { ...d, locked: !d.locked }))} className="text-slate-500 hover:text-slate-900">
                      <Icon name={d.locked ? "lock" : "unlock"} size={16} />
                    </button>
                    <button type="button" aria-label="Delete" disabled={d.locked} onClick={() => { setHist((h) => H.remove(h, d.id)); if (selected === d.id) setSelected(null); }} className="text-red-600 disabled:opacity-35">
                      <Icon name="trash" size={16} />
                    </button>
                  </li>
                ))}
              </ul>
            </aside>
          ) : null}
        </div>
      </div>
      <style>{`[data-draw-cursor="move"] canvas{cursor:move!important}[data-draw-cursor="grab"] canvas{cursor:grab!important}[data-draw-cursor="crosshair"] canvas{cursor:crosshair!important}`}</style>
    </div>
  );
}
