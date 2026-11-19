import { describe, expect, it } from "vitest";
import { makeProjection, type ChartHandles } from "@/components/charts/DrawingTools";
import * as H from "@/lib/drawings/history";
import { barAnchor, barTime } from "@/lib/timeframes";
import { anchors, clipLine, distanceTo, FIB_EXTENSION, FIB_RETRACEMENT, magnet, pick, pickHandle, shapesFor, translated, withHandleAt, type Projection } from "@/lib/drawings/geometry";
import { DEFAULT_STYLE, GROUPS, load, makeDrawing, migrateLegacy, parseDrawings, save, storageKey, TOOL_TYPES, TOOLS, type Pt, type ToolType } from "@/lib/drawings/model";

// A simple linear chart: bar i is at x = 100 + 10*i, price p is at y = 600 - p. 60 bars from 2024-01-01.
const DATES = Array.from({ length: 60 }, (_, i) => new Date(Date.UTC(2024, 0, 1 + i)).toISOString().slice(0, 10));
const proj: Projection = {
  width: 800,
  height: 600,
  x: (t) => (t === "" ? null : DATES.includes(t) ? 100 + 10 * DATES.indexOf(t) : null),
  y: (p) => 600 - p,
  time: (x) => DATES[Math.max(0, Math.min(59, Math.round((x - 100) / 10)))] ?? null,
  price: (y) => 600 - y,
  index: (t) => (DATES.includes(t) ? DATES.indexOf(t) : null),
};
const pt = (i: number, p: number): Pt => ({ t: DATES[i] as string, p });
const draw = (type: ToolType, ...p: Pt[]) => makeDrawing(type, p);

describe("model", () => {
  it("describes every tool and groups them", () => {
    for (const t of TOOL_TYPES) expect(TOOLS[t].label.length).toBeGreaterThan(0);
    expect(new Set(TOOL_TYPES.map((t) => TOOLS[t].group))).toEqual(new Set(GROUPS));
    expect(TOOL_TYPES.length).toBeGreaterThanOrEqual(20);
  });

  it("round-trips, drops anything malformed and keeps raw and adjusted apart", () => {
    const d = draw("trend", pt(1, 100), pt(9, 150));
    expect(parseDrawings(JSON.stringify([d]))).toEqual([d]);
    const bad = [{ ...d, type: "evil" }, { ...d, style: { ...d.style, color: "red" } }, { ...d, points: [] }, { ...d, id: "" }, null, 7, { ...d, points: [{ t: "x", p: Infinity }] }];
    expect(parseDrawings(JSON.stringify(bad))).toEqual([]);
    expect(parseDrawings("not json")).toEqual([]);
    expect(parseDrawings('{"a":1}')).toEqual([]);
    expect(parseDrawings(null)).toEqual([]);
    expect(storageKey(7, "none")).not.toBe(storageKey(7, "split"));
  });

  it("carries version 1 drawings over", () => {
    const old = JSON.stringify([{ type: "h", price: 123 }, { type: "t", t1: "2024-01-02", p1: 1, t2: "2024-01-09", p2: 2 }, { type: "x" }]);
    const out = migrateLegacy(old);
    expect(out.map((d) => d.type)).toEqual(["hline", "trend"]);
    expect(out[0]?.points).toEqual([{ t: "", p: 123 }]);
    expect(migrateLegacy("junk")).toEqual([]);
    expect(migrateLegacy(null)).toEqual([]);
    expect(migrateLegacy('{"a":1}')).toEqual([]);
    const mem = new Map<string, string>([["drawings:v1:7:none", old]]);
    const store = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) };
    expect(load(7, "none", store)).toHaveLength(2);
    save(7, "none", [draw("hline", { t: "", p: 5 })], store);
    expect(load(7, "none", store)).toHaveLength(1); // v2 wins once saved
    const broken = { getItem: () => { throw new Error("denied"); }, setItem: () => { throw new Error("full"); } };
    expect(load(7, "none", broken)).toEqual([]);
    expect(() => save(7, "none", [], broken)).not.toThrow();
  });
});

describe("history", () => {
  const a = draw("hline", { t: "", p: 1 });
  const b = draw("hline", { t: "", p: 2 });
  it("adds, updates, removes, undoes and redoes", () => {
    let h = H.initial();
    h = H.add(H.add(h, a), b);
    expect(h.list).toEqual([a, b]);
    h = H.update(h, { ...a, locked: true });
    expect(h.list[0]?.locked).toBe(true);
    expect(H.update(h, draw("trend", pt(1, 1), pt(2, 2)))).toBe(h); // unknown id: no step
    h = H.remove(h, b.id);
    expect(h.list).toHaveLength(1);
    expect(H.remove(h, "nope")).toBe(h);
    h = H.undo(H.undo(h));
    expect(h.list).toEqual([a, b]);
    h = H.redo(h);
    expect(h.list[0]?.locked).toBe(true);
    expect(H.redo(H.redo(H.redo(H.redo(h)))).list).toHaveLength(1);
    expect(H.undo(H.initial())).toEqual(H.initial());
  });
  it("clears, hides, resets and caps", () => {
    let h = H.add(H.initial(), a);
    expect(H.setAllHidden(h, false)).toBe(h);
    h = H.setAllHidden(h, true);
    expect(h.list[0]?.hidden).toBe(true);
    h = H.clear(h);
    expect(h.list).toEqual([]);
    expect(H.clear(h)).toBe(h);
    expect(H.undo(h).list).toHaveLength(1);
    expect(H.reset([a]).past).toEqual([]);
    let big = H.initial();
    for (let i = 0; i < H.MAX_STEPS + 20; i++) big = H.add(big, draw("hline", { t: "", p: i }));
    expect(big.past.length).toBe(H.MAX_STEPS);
    expect(H.add(H.initial(Array.from({ length: 300 }, () => a)), b).list).toHaveLength(300);
  });
});

describe("geometry", () => {
  it("clips lines to the plot", () => {
    expect(clipLine({ x: 100, y: 100 }, { x: 100, y: 100 }, 800, 600, true, true)).toBeNull();
    const seg = clipLine({ x: 100, y: 300 }, { x: 200, y: 300 }, 800, 600, true, true);
    expect(seg).toEqual([{ x: 0, y: 300 }, { x: 800, y: 300 }]);
    expect(clipLine({ x: 100, y: 300 }, { x: 200, y: 300 }, 800, 600, true, false)).toEqual([{ x: 100, y: 300 }, { x: 800, y: 300 }]);
    expect(clipLine({ x: 100, y: 700 }, { x: 200, y: 700 }, 800, 600, true, true)).toBeNull(); // outside
    expect(clipLine({ x: 100, y: 700 }, { x: 100, y: 800 }, 800, 600, true, true)).toEqual([{ x: 100, y: 0 }, { x: 100, y: 600 }]); // an infinite vertical line still crosses
    expect(clipLine({ x: 100, y: 700 }, { x: 100, y: 800 }, 800, 600, true, false)).toBeNull(); // a ray pointing away does not
    expect(clipLine({ x: 100, y: 0 }, { x: 100, y: 10 }, 800, 600, true, true)).toEqual([{ x: 100, y: 0 }, { x: 100, y: 600 }]);
    expect(clipLine({ x: 900, y: 0 }, { x: 1000, y: 100 }, 800, 600, true, false)).toBeNull();
  });

  it("draws line family tools", () => {
    const l = (type: ToolType, ...p: Pt[]) => shapesFor(draw(type, ...p), proj);
    expect(l("trend", pt(0, 100), pt(10, 150))).toEqual([{ kind: "line", x1: 100, y1: 500, x2: 200, y2: 450, stroke: { color: DEFAULT_STYLE.color, width: 2, dash: "solid" } }]);
    const ray = l("ray", pt(0, 100), pt(10, 100))[0];
    expect(ray).toMatchObject({ kind: "line", x1: 100, x2: 800 });
    const ext = l("extended", pt(0, 100), pt(10, 100))[0];
    expect(ext).toMatchObject({ x1: 0, x2: 800 });
    expect(l("hline", { t: "", p: 200 })[0]).toMatchObject({ x1: 0, x2: 800, y1: 400 });
    expect(l("hray", pt(5, 200))[0]).toMatchObject({ x1: 150, x2: 800, y1: 400 });
    expect(l("vline", pt(5, 1))[0]).toMatchObject({ x1: 150, x2: 150, y1: 0, y2: 600 });
    expect(l("cross", pt(5, 200))).toHaveLength(2);
    const arrow = l("arrow", pt(0, 100), pt(10, 100));
    expect(arrow.map((s) => s.kind)).toEqual(["line", "arrowhead"]);
    expect(arrow[1]).toMatchObject({ x: 200, y: 500, angle: 0 });
  });

  it("draws channels, pitchforks and plain shapes", () => {
    const ch = shapesFor(draw("channel", pt(0, 100), pt(10, 100), pt(5, 150)), proj);
    expect(ch.filter((s) => s.kind === "line")).toHaveLength(3);
    const lines = ch.filter((s) => s.kind === "line");
    expect(lines[1]).toMatchObject({ y1: 450, y2: 450 }); // the parallel sits 50 above
    expect(shapesFor(draw("channel", pt(0, 100), pt(10, 100)), proj)).toEqual([]); // needs 3 points
    expect(shapesFor(draw("channel", pt(5, 100), pt(5, 100), pt(8, 150)), proj).length).toBeGreaterThan(0); // vertical base
    const pf = shapesFor(draw("pitchfork", pt(0, 100), pt(10, 160), pt(10, 100)), proj);
    expect(pf.filter((s) => s.kind === "line").length).toBeGreaterThanOrEqual(3);
    expect(shapesFor(draw("pitchfork", pt(0, 1), pt(1, 2)), proj)).toEqual([]);
    expect(shapesFor(draw("rect", pt(0, 100), pt(10, 150)), proj)[0]).toMatchObject({ kind: "rect", x: 100, y: 450, w: 100, h: 50 });
    expect(shapesFor(draw("ellipse", pt(0, 100), pt(10, 150)), proj)[0]).toMatchObject({ kind: "ellipse", cx: 150, cy: 475, rx: 50, ry: 25 });
    expect(shapesFor(draw("triangle", pt(0, 100), pt(10, 150), pt(5, 200)), proj)[0]).toMatchObject({ kind: "poly", closed: true });
    expect(shapesFor(draw("triangle", pt(0, 1), pt(1, 2)), proj)).toEqual([]);
    expect(shapesFor(draw("brush", pt(0, 100), pt(1, 110), pt(2, 90)), proj)[0]).toMatchObject({ kind: "poly", closed: false });
    expect(shapesFor(draw("text", pt(3, 100)), proj)[0]).toMatchObject({ kind: "text", text: "Text" });
    expect(shapesFor({ ...draw("text", pt(3, 100)), text: "hi" }, proj)[0]).toMatchObject({ text: "hi" });
  });

  it("computes Fibonacci levels from the move", () => {
    const fr = shapesFor(draw("fibret", pt(0, 100), pt(10, 200)), proj);
    const labels = fr.filter((s) => s.kind === "text").map((s) => (s as { text: string }).text);
    expect(labels).toHaveLength(FIB_RETRACEMENT.length);
    expect(labels[0]).toBe("0 (200.00)"); // level 0 is the end of the move
    expect(labels[4]).toBe("0.618 (138.20)");
    expect(labels[6]).toBe("1 (100.00)");
    const fe = shapesFor(draw("fibext", pt(0, 100), pt(10, 200), pt(15, 150)), proj);
    const el = fe.filter((s) => s.kind === "text").map((s) => (s as { text: string }).text);
    expect(el).toHaveLength(FIB_EXTENSION.length);
    expect(el[0]).toBe("0 (150.00)");
    expect(el[4]).toBe("1.618 (311.80)"); // 150 + 100 * 1.618
    expect(shapesFor(draw("fibext", pt(0, 1), pt(1, 2)), proj)).toEqual([]);
    const off = { ...proj, y: (p: number) => (p > 1000 ? null : 600 - p) };
    expect(shapesFor(draw("fibret", pt(0, 100), pt(10, 2000)), off)).toEqual([]);
  });

  it("measures price, percent, bars and days", () => {
    const m = shapesFor(draw("measure", pt(2, 100), pt(12, 110)), proj).find((s) => s.kind === "text") as { text: string };
    expect(m.text).toBe("+10.00 (+10.00%)  10 bars, 10 days");
    const down = shapesFor(draw("measure", pt(2, 100), pt(4, 90)), proj).find((s) => s.kind === "text") as { text: string };
    expect(down.text).toBe("-10.00 (-10.00%)  2 bars, 2 days");
    const pr = shapesFor(draw("pricerange", pt(0, 200), pt(5, 150)), proj).find((s) => s.kind === "text") as { text: string };
    expect(pr.text).toBe("-50.00 (-25.00%)");
    const dr = shapesFor(draw("daterange", pt(3, 100), pt(13, 100)), proj).find((s) => s.kind === "text") as { text: string };
    expect(dr.text).toBe("10 bars, 10 days");
    const small = shapesFor(draw("measure", pt(0, 0.5), pt(1, 0.75)), proj).find((s) => s.kind === "text") as { text: string };
    expect(small.text).toContain("+0.25");
  });

  it("lays out long and short positions with their risk/reward", () => {
    const lg = shapesFor(draw("long", pt(5, 100), pt(25, 130), pt(5, 90)), proj);
    expect(lg.filter((s) => s.kind === "rect")).toHaveLength(2);
    const texts = lg.filter((s) => s.kind === "text").map((s) => (s as { text: string }).text);
    expect(texts).toContain("Long  R:R 3.00");
    expect(texts.some((t) => t.startsWith("Target 130.00 (+30.00%)"))).toBe(true);
    expect(texts.some((t) => t.startsWith("Stop 90.00 (-10.00%)"))).toBe(true);
    const sh = shapesFor(draw("short", pt(5, 100), pt(5, 70), pt(5, 100)), proj).filter((s) => s.kind === "text").map((s) => (s as { text: string }).text);
    expect(sh).toContain("Short  R:R -"); // zero risk is shown, not divided by
    expect(shapesFor(draw("long", pt(5, 1), pt(6, 2)), proj)).toEqual([]);
  });

  it("finds drawings and handles under the pointer and moves them", () => {
    const t = draw("trend", pt(0, 100), pt(10, 150));
    const r = draw("rect", pt(20, 100), pt(30, 150));
    const h = draw("hline", { t: "", p: 300 });
    expect(distanceTo(t, proj, 150, 475)).toBeLessThan(1);
    expect(pick([t, r, h], proj, 150, 475)?.id).toBe(t.id);
    expect(pick([t, r, h], proj, 350, 475)?.id).toBe(r.id); // inside the filled rectangle
    expect(pick([t, r, h], proj, 500, 300)?.id).toBe(h.id);
    expect(pick([t, r, h], proj, 500, 100)).toBeNull();
    expect(pick([{ ...t, hidden: true }], proj, 150, 475)).toBeNull();
    expect(pickHandle(t, proj, 101, 499)).toBe(0);
    expect(pickHandle(t, proj, 200, 450)).toBe(1);
    expect(pickHandle(t, proj, 500, 100)).toBe(-1);
    expect(anchors(h, proj)).toEqual([{ x: 40, y: 300 }]);
    expect(anchors(draw("vline", pt(5, 1)), proj)).toEqual([{ x: 150, y: 40 }]);
    expect(anchors(draw("brush", pt(0, 1), pt(1, 2)), proj)).toEqual([]);
    const moved = withHandleAt(t, 1, proj, 300, 400);
    expect(moved?.points[1]).toEqual(pt(20, 200));
    expect(withHandleAt(t, 5, proj, 300, 400)).toBeNull();
    expect(withHandleAt(h, 0, proj, 300, 250)?.points[0]).toEqual({ t: "", p: 350 });
    expect(withHandleAt(draw("vline", pt(5, 7)), 0, proj, 300, 250)?.points[0]).toEqual({ t: DATES[20], p: 7 });
    const shifted = translated(t, proj, 20, -10);
    expect(shifted?.points).toEqual([pt(2, 110), pt(12, 160)]);
    expect(translated(h, proj, 90, -10)?.points).toEqual([{ t: "", p: 310 }]); // a horizontal line only moves vertically
    expect(translated(draw("vline", pt(5, 7)), proj, 20, 50)?.points).toEqual([pt(7, 7)]);
    expect(translated({ ...t, points: [{ t: "1999-01-01", p: 1 }] }, proj, 1, 1)).toBeNull();
  });

  it("snaps to the nearest open/high/low/close within range", () => {
    const bar = { open: 100, high: 120, low: 90, close: 110 };
    expect(magnet(bar, proj, 600 - 118)).toBe(120);
    expect(magnet(bar, proj, 600 - 100)).toBe(100);
    expect(magnet(bar, proj, 600 - 150)).toBeNull();
    expect(magnet(undefined, proj, 100)).toBeNull();
  });
});


describe("drawings on intraday charts", () => {
  const T0 = 1_795_000_000; // an epoch second of a 5-minute bar open
  const bar = (i: number) => ({ date: "2026-11-18", time: T0 + i * 300, open: "1", high: "2", low: "1", close: "2", volume: "1", factor: "1" });
  const daily = (d: string) => ({ date: d, open: "1", high: "2", low: "1", close: "2", volume: "1", factor: "1" });
  const handles = (axisOf: (t: unknown) => number | null) => ({ chart: { timeScale: () => ({ coordinateToLogical: (x: number) => x / 10, timeToCoordinate: axisOf }) }, series: { priceToCoordinate: (p: number) => p, coordinateToPrice: (y: number) => y } }) as unknown as ChartHandles;

  it("anchors a click on an intraday bar to that bar's own date and time instead of refusing it", () => {
    const bars = [bar(0), bar(1), bar(2)];
    const p = makeProjection(handles(() => 0), bars, 800, 400);
    expect(p?.time(10)).toBe(barAnchor(bars[1]!)); // the nearest bar to logical index 1
    expect(p?.time(10)).toMatch(/^2026-11-18 \d\d:\d\d$/);
    expect(p?.index(barAnchor(bars[2]!))).toBe(2);
  });

  it("places an intraday anchor on the chart's axis by the bar's shifted epoch time and a daily one by its date", () => {
    const asked: unknown[] = [];
    const bars = [bar(0), bar(1)];
    makeProjection(handles((t) => { asked.push(t); return 5; }), bars, 800, 400)?.x(barAnchor(bars[1]!));
    expect(asked).toEqual([barTime(bars[1]!)]);
    asked.length = 0;
    makeProjection(handles((t) => { asked.push(t); return 5; }), [daily("2026-11-17"), daily("2026-11-18")], 800, 400)?.x("2026-11-18");
    expect(asked).toEqual(["2026-11-18"]);
  });

  it("a daily click still anchors to the plain date", () => {
    const bars = [daily("2026-11-17"), daily("2026-11-18")];
    expect(makeProjection(handles(() => 0), bars, 800, 400)?.time(10)).toBe("2026-11-18");
  });

  it("keeps each intraday timeframe's drawings apart from the daily ones", () => {
    const store = new Map<string, string>();
    const mem = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v) };
    const d = makeDrawing("trend", [{ t: "2026-11-18 09:15", p: 100 }, { t: "2026-11-18 10:00", p: 101 }]);
    save("idx:NIFTY 50", "none", [d], mem, "5m");
    expect(load("idx:NIFTY 50", "none", mem, "5m")).toHaveLength(1);
    expect(load("idx:NIFTY 50", "none", mem, "15m")).toEqual([]); // another timeframe has its own
    expect(load("idx:NIFTY 50", "none", mem)).toEqual([]); // and so does the daily set
    expect(storageKey("idx:NIFTY 50", "none", "5m")).not.toBe(storageKey("idx:NIFTY 50", "none"));
  });
});
