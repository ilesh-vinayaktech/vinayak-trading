import type { Dash, Drawing, Pt } from "./model";

// Pure geometry: from a drawing's anchors (bar date, price) to the shapes to paint, to hit-testing
// and moving. The chart supplies a Projection; nothing here touches the chart or the DOM.

export interface Projection {
  x(t: string): number | null;
  y(p: number): number | null;
  time(x: number): string | null; // nearest bar date
  price(y: number): number | null;
  index(t: string): number | null; // bar index
  width: number; // plot area
  height: number;
}

export type Stroke = { color: string; width: number; dash: Dash; opacity?: number };
export type Shape =
  | { kind: "line"; x1: number; y1: number; x2: number; y2: number; stroke: Stroke }
  | { kind: "poly"; pts: [number, number][]; closed: boolean; fill?: string; fillOpacity?: number; stroke: Stroke }
  | { kind: "rect"; x: number; y: number; w: number; h: number; fill?: string; fillOpacity?: number; stroke: Stroke }
  | { kind: "ellipse"; cx: number; cy: number; rx: number; ry: number; fill?: string; fillOpacity?: number; stroke: Stroke }
  | { kind: "arrowhead"; x: number; y: number; angle: number; color: string; size: number }
  | { kind: "text"; x: number; y: number; text: string; color: string; anchor: "start" | "middle" | "end" };

export const FIB_RETRACEMENT = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1] as const;
export const FIB_EXTENSION = [0, 0.618, 1, 1.272, 1.618, 2.618] as const;
const FIB_COLORS = ["#64748b", "#dc2626", "#d97706", "#059669", "#0891b2", "#2563eb", "#7c3aed"];
const GREEN = "#059669";
const RED = "#dc2626";

type XY = { x: number; y: number };

const stroke = (d: Drawing, over: Partial<Stroke> = {}): Stroke => ({ color: d.style.color, width: d.style.width, dash: d.style.dash, ...over });

/** The clip of the infinite line through a,b (forward and/or backward) to the plot rectangle. */
export function clipLine(a: XY, b: XY, w: number, h: number, forward: boolean, backward: boolean): [XY, XY] | null {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  if (dx === 0 && dy === 0) return null;
  let lo = backward ? -Infinity : 0;
  let hi = forward ? Infinity : 1;
  const edge = (p: number, q: number) => {
    // inequality p*t <= q (Liang-Barsky)
    if (p === 0) return q >= 0;
    const r = q / p;
    if (p < 0) lo = Math.max(lo, r);
    else hi = Math.min(hi, r);
    return true;
  };
  if (!edge(-dx, a.x) || !edge(dx, w - a.x) || !edge(-dy, a.y) || !edge(dy, h - a.y)) return null;
  if (lo > hi) return null;
  return [{ x: a.x + lo * dx, y: a.y + lo * dy }, { x: a.x + hi * dx, y: a.y + hi * dy }];
}

function screen(d: Drawing, proj: Projection): XY[] | null {
  const out: XY[] = [];
  for (const p of d.points) {
    const x = p.t === "" ? proj.width * 0.5 : proj.x(p.t);
    const y = proj.y(p.p);
    if (x === null || y === null) return null;
    out.push({ x, y });
  }
  return out;
}

const fmtPrice = (n: number) => (Math.abs(n) >= 1 ? n.toFixed(2) : n.toFixed(4).replace(/0+$/, "").replace(/\.$/, ""));
const sign = (n: number) => (n > 0 ? "+" : "");

function dayDiff(a: string, b: string): number {
  return Math.round((Date.UTC(+b.slice(0, 4), +b.slice(5, 7) - 1, +b.slice(8, 10)) - Date.UTC(+a.slice(0, 4), +a.slice(5, 7) - 1, +a.slice(8, 10))) / 86_400_000);
}

function line(a: XY, b: XY, s: Stroke): Shape {
  return { kind: "line", x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: s };
}

function arrowAt(from: XY, to: XY, color: string, size = 9): Shape {
  return { kind: "arrowhead", x: to.x, y: to.y, angle: Math.atan2(to.y - from.y, to.x - from.x), color, size };
}

function clipped(a: XY, b: XY, proj: Projection, s: Stroke, fwd: boolean, back: boolean): Shape[] {
  const seg = clipLine(a, b, proj.width, proj.height, fwd, back);
  return seg ? [line(seg[0], seg[1], s)] : [];
}

/** The shapes of one drawing in screen space ([] if an anchor is off the loaded data). */
export function shapesFor(d: Drawing, proj: Projection): Shape[] {
  const P = screen(d, proj);
  if (!P) return [];
  const [a, b, c] = P as [XY, XY, XY];
  const s = stroke(d);
  const col = d.style.color;
  const pts = d.points;
  switch (d.type) {
    case "trend":
      return [line(a, b, s)];
    case "ray":
      return clipped(a, b, proj, s, true, false);
    case "extended":
      return clipped(a, b, proj, s, true, true);
    case "hline":
      return [line({ x: 0, y: a.y }, { x: proj.width, y: a.y }, s)];
    case "hray":
      return [line(a, { x: proj.width, y: a.y }, s)];
    case "vline":
      return [line({ x: a.x, y: 0 }, { x: a.x, y: proj.height }, s)];
    case "cross":
      return [line({ x: 0, y: a.y }, { x: proj.width, y: a.y }, s), line({ x: a.x, y: 0 }, { x: a.x, y: proj.height }, s)];
    case "arrow":
      return [line(a, b, s), arrowAt(a, b, col, 8 + d.style.width * 2)];
    case "channel": {
      if (!c) return [];
      const slope = b.x === a.x ? 0 : (b.y - a.y) / (b.x - a.x);
      const off = c.y - (a.y + slope * (c.x - a.x)); // vertical offset of the parallel
      const a2 = { x: a.x, y: a.y + off };
      const b2 = { x: b.x, y: b.y + off };
      return [
        { kind: "poly", pts: [[a.x, a.y], [b.x, b.y], [b2.x, b2.y], [a2.x, a2.y]], closed: true, fill: col, fillOpacity: 0.08, stroke: stroke(d, { opacity: 0 }) },
        line(a, b, s),
        line(a2, b2, s),
        line({ x: a.x, y: a.y + off / 2 }, { x: b.x, y: b.y + off / 2 }, stroke(d, { dash: "dashed", width: 1, opacity: 0.7 })),
      ];
    }
    case "pitchfork": {
      if (!c) return [];
      const m = { x: (b.x + c.x) / 2, y: (b.y + c.y) / 2 };
      const dir = { x: m.x - a.x, y: m.y - a.y };
      const far = (o: XY): [XY, XY] | null => clipLine(o, { x: o.x + dir.x, y: o.y + dir.y }, proj.width, proj.height, true, false);
      const out: Shape[] = [line(b, c, stroke(d, { width: 1, opacity: 0.7 }))];
      for (const [o, st] of [[a, s], [b, stroke(d, { width: Math.max(1, d.style.width - 1) })], [c, stroke(d, { width: Math.max(1, d.style.width - 1) })]] as [XY, Stroke][]) {
        const seg = far(o);
        if (seg) out.push(line(seg[0], seg[1], st));
      }
      return out;
    }
    case "rect":
      return [{ kind: "rect", x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y), fill: col, fillOpacity: 0.1, stroke: s }];
    case "ellipse":
      return [{ kind: "ellipse", cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2, rx: Math.abs(b.x - a.x) / 2, ry: Math.abs(b.y - a.y) / 2, fill: col, fillOpacity: 0.1, stroke: s }];
    case "triangle":
      return c ? [{ kind: "poly", pts: [[a.x, a.y], [b.x, b.y], [c.x, c.y]], closed: true, fill: col, fillOpacity: 0.1, stroke: s }] : [];
    case "brush":
      return [{ kind: "poly", pts: P.map((q) => [q.x, q.y] as [number, number]), closed: false, stroke: s }];
    case "fibret":
    case "fibext": {
      const ext = d.type === "fibext";
      if (ext && !c) return [];
      const levels = ext ? FIB_EXTENSION : FIB_RETRACEMENT;
      const [p0, p1, p2] = pts as [Pt, Pt, Pt];
      const left = ext ? Math.min(a.x, b.x, c.x) : Math.min(a.x, b.x);
      const right = ext ? Math.max(a.x, b.x, c.x) + 60 : Math.max(a.x, b.x);
      const out: Shape[] = [line(a, b, stroke(d, { dash: "dashed", width: 1, opacity: 0.8 }))];
      if (ext) out.push(line(b, c, stroke(d, { dash: "dashed", width: 1, opacity: 0.8 })));
      const priceAt = (lv: number) => (ext ? p2.p + (p1.p - p0.p) * lv : p1.p - (p1.p - p0.p) * lv);
      const ys = levels.map((lv) => proj.y(priceAt(lv)));
      levels.forEach((lv, i) => {
        const y = ys[i];
        if (y === null || y === undefined) return;
        const color = FIB_COLORS[i % FIB_COLORS.length] as string;
        out.push(line({ x: left, y }, { x: right, y }, { color, width: 1, dash: "solid" }));
        out.push({ kind: "text", x: left + 4, y: y - 3, text: `${lv} (${fmtPrice(priceAt(lv))})`, color, anchor: "start" });
        const yn = ys[i + 1];
        if (yn !== null && yn !== undefined && i < levels.length - 1) out.push({ kind: "rect", x: left, y: Math.min(y, yn), w: right - left, h: Math.abs(yn - y), fill: color, fillOpacity: 0.05, stroke: { color, width: 1, dash: "solid", opacity: 0 } });
      });
      return out;
    }
    case "measure": {
      const [p0, p1] = pts as [Pt, Pt];
      const up = p1.p >= p0.p;
      const color = up ? GREEN : RED;
      const dp = p1.p - p0.p;
      const bars = Math.abs((proj.index(p1.t) ?? 0) - (proj.index(p0.t) ?? 0));
      return [
        { kind: "rect", x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(b.x - a.x), h: Math.abs(b.y - a.y), fill: color, fillOpacity: 0.1, stroke: { color, width: 1, dash: "dashed", opacity: 0.6 } },
        line(a, b, { color, width: d.style.width, dash: "solid" }),
        arrowAt(a, b, color),
        { kind: "text", x: (a.x + b.x) / 2, y: Math.min(a.y, b.y) - 6, text: `${sign(dp)}${fmtPrice(dp)} (${sign(dp)}${((dp / p0.p) * 100).toFixed(2)}%)  ${bars} bars, ${Math.abs(dayDiff(p0.t, p1.t))} days`, color, anchor: "middle" },
      ];
    }
    case "pricerange": {
      const [p0, p1] = pts as [Pt, Pt];
      const left = Math.min(a.x, b.x);
      const right = Math.max(a.x, b.x);
      const mid = (a.x + b.x) / 2;
      const dp = p1.p - p0.p;
      const color = dp >= 0 ? GREEN : RED;
      return [
        { kind: "rect", x: left, y: Math.min(a.y, b.y), w: right - left, h: Math.abs(b.y - a.y), fill: color, fillOpacity: 0.1, stroke: { color, width: 1, dash: "solid", opacity: 0.7 } },
        line({ x: mid, y: a.y }, { x: mid, y: b.y }, { color, width: 1, dash: "solid" }),
        arrowAt({ x: mid, y: a.y }, { x: mid, y: b.y }, color),
        { kind: "text", x: mid, y: Math.min(a.y, b.y) - 6, text: `${sign(dp)}${fmtPrice(dp)} (${sign(dp)}${((dp / p0.p) * 100).toFixed(2)}%)`, color, anchor: "middle" },
      ];
    }
    case "daterange": {
      const [p0, p1] = pts as [Pt, Pt];
      const bars = Math.abs((proj.index(p1.t) ?? 0) - (proj.index(p0.t) ?? 0));
      const midY = (a.y + b.y) / 2;
      return [
        { kind: "rect", x: Math.min(a.x, b.x), y: 0, w: Math.abs(b.x - a.x), h: proj.height, fill: col, fillOpacity: 0.07, stroke: { color: col, width: 1, dash: "solid", opacity: 0.7 } },
        line({ x: a.x, y: midY }, { x: b.x, y: midY }, { color: col, width: 1, dash: "solid" }),
        arrowAt({ x: a.x, y: midY }, { x: b.x, y: midY }, col),
        { kind: "text", x: (a.x + b.x) / 2, y: midY - 6, text: `${bars} bars, ${Math.abs(dayDiff(p0.t, p1.t))} days`, color: col, anchor: "middle" },
      ];
    }
    case "long":
    case "short": {
      if (!c) return [];
      const [p0, p1, p2] = pts as [Pt, Pt, Pt];
      const x0 = a.x;
      const x1 = b.x > a.x + 20 ? b.x : a.x + 120;
      const gain = Math.abs(p1.p - p0.p);
      const risk = Math.abs(p2.p - p0.p);
      return [
        { kind: "rect", x: x0, y: Math.min(a.y, b.y), w: x1 - x0, h: Math.abs(b.y - a.y), fill: GREEN, fillOpacity: 0.18, stroke: { color: GREEN, width: 1, dash: "solid", opacity: 0.8 } },
        { kind: "rect", x: x0, y: Math.min(a.y, c.y), w: x1 - x0, h: Math.abs(c.y - a.y), fill: RED, fillOpacity: 0.18, stroke: { color: RED, width: 1, dash: "solid", opacity: 0.8 } },
        line({ x: x0, y: a.y }, { x: x1, y: a.y }, { color: "#475569", width: 1, dash: "solid" }),
        { kind: "text", x: x0 + 4, y: b.y + (b.y < a.y ? 12 : -4), text: `Target ${fmtPrice(p1.p)} (${sign(p1.p - p0.p)}${(((p1.p - p0.p) / p0.p) * 100).toFixed(2)}%)`, color: GREEN, anchor: "start" },
        { kind: "text", x: x0 + 4, y: c.y + (c.y < a.y ? 12 : -4), text: `Stop ${fmtPrice(p2.p)} (${sign(p2.p - p0.p)}${(((p2.p - p0.p) / p0.p) * 100).toFixed(2)}%)`, color: RED, anchor: "start" },
        { kind: "text", x: x0 + 4, y: a.y - 4, text: `${d.type === "long" ? "Long" : "Short"}  R:R ${risk === 0 ? "-" : (gain / risk).toFixed(2)}`, color: "#334155", anchor: "start" },
      ];
    }
    case "text":
      return [{ kind: "text", x: a.x, y: a.y, text: d.text ?? "Text", color: col, anchor: "start" }];
  }
}

/** Where the drag handles sit: one per stored point. */
export function anchors(d: Drawing, proj: Projection): XY[] {
  const P = screen(d, proj);
  if (!P) return [];
  if (d.type === "hline") return [{ x: Math.min(proj.width - 12, 40), y: P[0]?.y ?? 0 }];
  if (d.type === "vline") return [{ x: P[0]?.x ?? 0, y: 40 }];
  if (d.type === "brush") return [];
  return P;
}

function distSeg(px: number, py: number, x1: number, y1: number, x2: number, y2: number): number {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((px - x1) * dx + (py - y1) * dy) / len2));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

function insidePoly(px: number, py: number, pts: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i] as [number, number];
    const [xj, yj] = pts[j] as [number, number];
    if (yi > py !== yj > py && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function shapeDistance(sh: Shape, px: number, py: number, filled: boolean): number {
  switch (sh.kind) {
    case "line":
      return distSeg(px, py, sh.x1, sh.y1, sh.x2, sh.y2);
    case "poly": {
      if (filled && sh.closed && insidePoly(px, py, sh.pts)) return 0;
      let best = Infinity;
      const n = sh.pts.length;
      for (let i = 0; i < (sh.closed ? n : n - 1); i++) {
        const [x1, y1] = sh.pts[i] as [number, number];
        const [x2, y2] = sh.pts[(i + 1) % n] as [number, number];
        best = Math.min(best, distSeg(px, py, x1, y1, x2, y2));
      }
      return best;
    }
    case "rect": {
      const inside = px >= sh.x && px <= sh.x + sh.w && py >= sh.y && py <= sh.y + sh.h;
      if (filled && inside) return 0;
      const dx = Math.max(sh.x - px, 0, px - (sh.x + sh.w));
      const dy = Math.max(sh.y - py, 0, py - (sh.y + sh.h));
      if (!inside) return Math.hypot(dx, dy);
      return Math.min(px - sh.x, sh.x + sh.w - px, py - sh.y, sh.y + sh.h - py);
    }
    case "ellipse": {
      if (sh.rx === 0 || sh.ry === 0) return Infinity;
      const v = Math.hypot((px - sh.cx) / sh.rx, (py - sh.cy) / sh.ry);
      if (filled && v <= 1) return 0;
      return Math.abs(v - 1) * Math.min(sh.rx, sh.ry);
    }
    case "text": {
      const w = sh.text.length * 6.5;
      const x0 = sh.anchor === "middle" ? sh.x - w / 2 : sh.anchor === "end" ? sh.x - w : sh.x;
      return px >= x0 && px <= x0 + w && py >= sh.y - 12 && py <= sh.y + 3 ? 0 : Infinity;
    }
    case "arrowhead":
      return Infinity;
  }
}

const FILLED = new Set(["rect", "ellipse", "triangle", "channel", "long", "short", "measure", "pricerange", "daterange"]);

/** Distance in px from (px,py) to the drawing, 0 when inside a filled shape. */
export function distanceTo(d: Drawing, proj: Projection, px: number, py: number): number {
  const shapes = shapesFor(d, proj);
  let best = Infinity;
  for (const sh of shapes) {
    if (sh.kind === "poly" && sh.stroke.opacity === 0 && d.type !== "channel") continue;
    best = Math.min(best, shapeDistance(sh, px, py, FILLED.has(d.type)));
  }
  return best;
}

/** Top-most drawing within tol px, preferring the nearest. */
export function pick(list: Drawing[], proj: Projection, px: number, py: number, tol = 6): Drawing | null {
  let best: Drawing | null = null;
  let bestDist = tol;
  for (const d of list) {
    if (d.hidden) continue;
    const dist = distanceTo(d, proj, px, py);
    if (dist <= bestDist) {
      best = d;
      bestDist = dist;
    }
  }
  return best;
}

/** Index of the anchor handle near (px,py), or -1. */
export function pickHandle(d: Drawing, proj: Projection, px: number, py: number, tol = 8): number {
  const a = anchors(d, proj);
  for (let i = 0; i < a.length; i++) {
    const q = a[i] as XY;
    if (Math.hypot(px - q.x, py - q.y) <= tol) return i;
  }
  return -1;
}

/** The drawing with one anchor moved to a new screen position (null if it is off the data). */
export function withHandleAt(d: Drawing, index: number, proj: Projection, x: number, y: number): Drawing | null {
  const t = proj.time(x);
  const p = proj.price(y);
  const old = d.points[index];
  if (!old || p === null || (t === null && d.type !== "hline")) return null;
  const next: Pt = d.type === "hline" ? { t: "", p } : d.type === "vline" ? { t: t as string, p: old.p } : { t: t ?? old.t, p };
  return { ...d, points: d.points.map((q, i) => (i === index ? next : q)) };
}

/** The drawing shifted by (dx,dy) screen pixels (null if any anchor would leave the data). */
export function translated(d: Drawing, proj: Projection, dx: number, dy: number): Drawing | null {
  const horizontalOnly = d.type === "hline"; // has a price, no bar
  const verticalOnly = d.type === "vline"; // has a bar, no meaningful price
  const pts: Pt[] = [];
  for (const p of d.points) {
    const x0 = p.t === "" ? proj.width * 0.5 : proj.x(p.t);
    const y0 = proj.y(p.p);
    if (x0 === null || y0 === null) return null;
    const t = horizontalOnly ? "" : proj.time(x0 + dx);
    const price = verticalOnly ? p.p : proj.price(y0 + dy);
    if (price === null || t === null) return null;
    pts.push({ t, p: price });
  }
  return { ...d, points: pts };
}

/** Snap a screen point to the nearest open/high/low/close of the bar under it, within `tol` px. */
export function magnet(bar: { open: number; high: number; low: number; close: number } | undefined, proj: Projection, y: number, tol = 14): number | null {
  if (!bar) return null;
  let best: number | null = null;
  let bestD = tol;
  for (const p of [bar.open, bar.high, bar.low, bar.close]) {
    const py = proj.y(p);
    if (py !== null && Math.abs(py - y) <= bestD) {
      best = p;
      bestD = Math.abs(py - y);
    }
  }
  return best;
}
