"use client";

import type { IChartApi, ISeriesApi, Time } from "lightweight-charts";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { magnet, pick, pickHandle, shapesFor, translated, withHandleAt, anchors, type Projection, type Shape } from "@/lib/drawings/geometry";
import * as H from "@/lib/drawings/history";
import { COLORS, DASHES, DEFAULT_STYLE, GROUPS, load, makeDrawing, save, TOOLS, TOOL_TYPES, type Drawing, type Pt, type Style, type ToolGroup, type ToolType } from "@/lib/drawings/model";


export type ChartHandles = { chart: IChartApi; series: ISeriesApi<"Candlestick"> };
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

export function DrawingTools({ handles, ready, tick, bars, instrumentId, adjust, above, children }: { handles: ChartHandles | null; ready: number; tick: number; bars: Bar[]; instrumentId: number; adjust: string; above?: ReactNode; children: ReactNode }) {
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
      setSize({ w: Math.max(0, h.chart.timeScale().width()), h: Math.max(0, el.clientHeight - h.chart.timeScale().height()) });
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
  }, []);

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

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-1.5" role="toolbar" aria-label="Chart tools">
        <button type="button" aria-pressed={tool === "cursor"} onClick={() => setTool("cursor")} className={`rounded px-3 py-1 text-xs ${tool === "cursor" ? "bg-slate-900 text-white" : "bg-slate-100 text-ink-soft hover:bg-slate-200"}`}>
          Cursor
        </button>
        {GROUPS.map((g) => {
          const items = TOOL_TYPES.filter((t) => TOOLS[t].group === g);
          const active = tool !== "cursor" && TOOLS[tool].group === g;
          return (
            <div key={g} className="relative">
              <button type="button" aria-haspopup="menu" aria-expanded={openGroup === g} data-group={g} onClick={() => setOpenGroup(openGroup === g ? null : g)} className={`rounded px-3 py-1 text-xs ${active ? "bg-slate-900 text-white" : "bg-slate-100 text-ink-soft hover:bg-slate-200"}`}>
                {active ? TOOLS[tool].label : g} ▾
              </button>
              {openGroup === g ? (
                <ul role="menu" className="absolute left-0 top-full z-30 mt-1 min-w-52 rounded-md border border-line bg-white py-1 shadow-lg">
                  {items.map((t) => (
                    <li key={t} role="none">
                      <button type="button" role="menuitem" data-tool={t} onClick={() => setTool(t)} className="flex w-full items-center justify-between px-3 py-1.5 text-left text-xs hover:bg-slate-100">
                        {TOOLS[t].label}
                        {lastIn[g] === t ? <span className="text-ink-faint">last used</span> : null}
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          );
        })}
        <span className="mx-1 h-4 w-px bg-line" aria-hidden="true" />
        <button type="button" aria-pressed={snap} onClick={() => setSnap((v) => !v)} title="Snap points to the nearest open, high, low or close" className={`rounded px-3 py-1 text-xs ${snap ? "bg-violet-600 text-white" : "bg-slate-100 text-ink-soft hover:bg-slate-200"}`}>
          Magnet
        </button>
        <button type="button" disabled={hist.past.length === 0} onClick={() => setHist((h) => H.undo(h))} title="Ctrl+Z" className="rounded bg-slate-100 px-3 py-1 text-xs text-ink-soft hover:bg-slate-200 disabled:opacity-40">
          Undo
        </button>
        <button type="button" disabled={hist.future.length === 0} onClick={() => setHist((h) => H.redo(h))} title="Ctrl+Shift+Z" className="rounded bg-slate-100 px-3 py-1 text-xs text-ink-soft hover:bg-slate-200 disabled:opacity-40">
          Redo
        </button>
        <button type="button" aria-pressed={allHidden} disabled={list.length === 0} onClick={() => setAllHidden((v) => !v)} className="rounded bg-slate-100 px-3 py-1 text-xs text-ink-soft hover:bg-slate-200 disabled:opacity-40">
          {allHidden ? "Show all" : "Hide all"}
        </button>
        <button type="button" disabled={list.length === 0} onClick={() => { setHist((h) => H.clear(h)); setSelected(null); }} className="rounded bg-slate-100 px-3 py-1 text-xs text-ink-soft hover:bg-slate-200 disabled:opacity-40">
          Clear drawings
        </button>
        <button type="button" aria-pressed={listOpen} onClick={() => setListOpen((v) => !v)} className="rounded bg-slate-100 px-3 py-1 text-xs text-ink-soft hover:bg-slate-200">
          Objects ({list.length})
        </button>
        <button type="button" disabled title="Needs a stored backtest with its trades; none exist yet" className="ml-auto cursor-not-allowed rounded border border-dashed border-line px-3 py-1 text-xs text-ink-faint">
          Load strategy run (not available yet)
        </button>
      </div>

      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs" aria-label="Drawing style">
        <span className="text-ink-soft">{selectedDrawing ? `Selected: ${TOOLS[selectedDrawing.type].label}` : "New drawings:"}</span>
        {COLORS.map((c) => (
          <button key={c} type="button" aria-label={`Colour ${c}`} aria-pressed={(selectedDrawing?.style ?? style).color === c} onClick={() => setStyleOf({ color: c })} className="h-5 w-5 rounded-full ring-offset-1" style={{ background: c, outline: (selectedDrawing?.style ?? style).color === c ? "2px solid #0f172a" : "none" }} />
        ))}
        <select aria-label="Line width" value={(selectedDrawing?.style ?? style).width} onChange={(e) => setStyleOf({ width: Number(e.target.value) })} className="rounded border border-line px-1 py-0.5">
          {[1, 2, 3, 4].map((w) => (
            <option key={w} value={w}>{w}px</option>
          ))}
        </select>
        <select aria-label="Line style" value={(selectedDrawing?.style ?? style).dash} onChange={(e) => setStyleOf({ dash: e.target.value as Style["dash"] })} className="rounded border border-line px-1 py-0.5">
          {DASHES.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
        {selectedDrawing ? (
          <>
            {selectedDrawing.type === "text" ? <input aria-label="Text" value={selectedDrawing.text ?? ""} maxLength={200} onChange={(e) => patchSelected({ text: e.target.value })} className="w-48 rounded border border-line px-2 py-0.5" /> : null}
            <button type="button" aria-pressed={selectedDrawing.locked} onClick={() => patchSelected({ locked: !selectedDrawing.locked })} className="rounded bg-slate-100 px-2 py-0.5 hover:bg-slate-200">
              {selectedDrawing.locked ? "Unlock" : "Lock"}
            </button>
            <button type="button" onClick={() => { const c = makeDrawing(selectedDrawing.type, selectedDrawing.points.map((p) => ({ ...p, p: p.p })), selectedDrawing.style, selectedDrawing.text); setHist((h) => H.add(h, c)); setSelected(c.id); }} className="rounded bg-slate-100 px-2 py-0.5 hover:bg-slate-200">
              Duplicate
            </button>
            <button type="button" disabled={selectedDrawing.locked} onClick={() => { setHist((h) => H.remove(h, selectedDrawing.id)); setSelected(null); }} className="rounded bg-red-50 px-2 py-0.5 text-red-700 hover:bg-red-100 disabled:opacity-40">
              Delete
            </button>
          </>
        ) : null}
      </div>
      <p className="mb-2 min-h-4 text-xs text-ink-soft" data-testid="tool-hint">{hint}</p>

      {above}
      <div ref={wrap} className="relative" data-draw-cursor={tool !== "cursor" ? "crosshair" : cursor}>
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
      <style>{`[data-draw-cursor="move"] canvas{cursor:move!important}[data-draw-cursor="grab"] canvas{cursor:grab!important}[data-draw-cursor="crosshair"] canvas{cursor:crosshair!important}`}</style>

      {listOpen ? (
        <ul className="mt-3 divide-y divide-line rounded-md border border-line text-xs" aria-label="Drawings">
          {list.length === 0 ? <li className="p-3 text-ink-soft">No drawings on this chart.</li> : null}
          {list.map((d, i) => (
            <li key={d.id} className={`flex items-center gap-2 p-2 ${d.id === selected ? "bg-slate-50" : ""}`}>
              <span className="h-3 w-3 rounded-full" style={{ background: d.style.color }} />
              <button type="button" className="flex-1 text-left" onClick={() => { setSelected(d.id); setToolState("cursor"); }}>
                {i + 1}. {TOOLS[d.type].label}
              </button>
              <button type="button" aria-pressed={d.hidden} onClick={() => setHist((h) => H.update(h, { ...d, hidden: !d.hidden }))} className="rounded bg-slate-100 px-2 py-0.5">{d.hidden ? "Show" : "Hide"}</button>
              <button type="button" aria-pressed={d.locked} onClick={() => setHist((h) => H.update(h, { ...d, locked: !d.locked }))} className="rounded bg-slate-100 px-2 py-0.5">{d.locked ? "Unlock" : "Lock"}</button>
              <button type="button" disabled={d.locked} onClick={() => { setHist((h) => H.remove(h, d.id)); if (selected === d.id) setSelected(null); }} className="rounded bg-red-50 px-2 py-0.5 text-red-700 disabled:opacity-40">Delete</button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
