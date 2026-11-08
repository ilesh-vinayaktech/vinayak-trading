import { z } from "zod";

// A drawing is an annotation on a chart: it feeds nothing else. Points are (bar date, price) in the
// price basis the chart is showing, so drawings are stored per instrument AND basis.

export const TOOL_TYPES = [
  "trend", "ray", "extended", "hline", "hray", "vline", "cross", "arrow",
  "channel", "pitchfork", "rect", "ellipse", "triangle", "brush",
  "fibret", "fibext", "measure", "pricerange", "daterange", "long", "short", "text",
] as const;
export type ToolType = (typeof TOOL_TYPES)[number];

export type ToolGroup = "Lines" | "Channels" | "Shapes" | "Fibonacci" | "Measure" | "Forecast" | "Annotation";

/** points: how many clicks complete the drawing ("free" = press-and-drag, e.g. the brush). */
export const TOOLS: Record<ToolType, { label: string; group: ToolGroup; points: number | "free"; hint: string }> = {
  trend: { label: "Trend line", group: "Lines", points: 2, hint: "click two points" },
  ray: { label: "Ray", group: "Lines", points: 2, hint: "click the start, then a point on the ray" },
  extended: { label: "Extended line", group: "Lines", points: 2, hint: "click two points; the line runs both ways" },
  hline: { label: "Horizontal line", group: "Lines", points: 1, hint: "click a price level" },
  hray: { label: "Horizontal ray", group: "Lines", points: 1, hint: "click a start point; the ray runs right" },
  vline: { label: "Vertical line", group: "Lines", points: 1, hint: "click a bar" },
  cross: { label: "Cross line", group: "Lines", points: 1, hint: "click a bar and price" },
  arrow: { label: "Arrow", group: "Lines", points: 2, hint: "click the tail, then the head" },
  channel: { label: "Parallel channel", group: "Channels", points: 3, hint: "two points for the trend, a third for the width" },
  pitchfork: { label: "Andrews pitchfork", group: "Channels", points: 3, hint: "click the pivot, then two swing points" },
  rect: { label: "Rectangle", group: "Shapes", points: 2, hint: "click two opposite corners" },
  ellipse: { label: "Ellipse", group: "Shapes", points: 2, hint: "click two opposite corners of its box" },
  triangle: { label: "Triangle", group: "Shapes", points: 3, hint: "click three corners" },
  brush: { label: "Brush", group: "Shapes", points: "free", hint: "press and drag to draw freehand" },
  fibret: { label: "Fib retracement", group: "Fibonacci", points: 2, hint: "click the swing start, then its end" },
  fibext: { label: "Trend-based fib extension", group: "Fibonacci", points: 3, hint: "click the swing start, its end, then the retracement" },
  measure: { label: "Measure", group: "Measure", points: 2, hint: "click two points: price, percent, bars and days" },
  pricerange: { label: "Price range", group: "Measure", points: 2, hint: "click two prices" },
  daterange: { label: "Date range", group: "Measure", points: 2, hint: "click two bars" },
  long: { label: "Long position", group: "Forecast", points: 3, hint: "click entry, then target, then stop" },
  short: { label: "Short position", group: "Forecast", points: 3, hint: "click entry, then target, then stop" },
  text: { label: "Text", group: "Annotation", points: 1, hint: "click where the note goes" },
};

export const GROUPS: ToolGroup[] = ["Lines", "Channels", "Shapes", "Fibonacci", "Measure", "Forecast", "Annotation"];

export const COLORS = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0f172a", "#db2777", "#0891b2"] as const;
export const DASHES = ["solid", "dashed", "dotted"] as const;
export type Dash = (typeof DASHES)[number];

const pointSchema = z.object({ t: z.string(), p: z.number().finite() });
export type Pt = z.infer<typeof pointSchema>;

const styleSchema = z.object({
  color: z.string().regex(/^#[0-9a-fA-F]{6}$/),
  width: z.number().int().min(1).max(4),
  dash: z.enum(DASHES),
});
export type Style = z.infer<typeof styleSchema>;

export const drawingSchema = z.object({
  id: z.string().min(1).max(64),
  type: z.enum(TOOL_TYPES),
  points: z.array(pointSchema).min(1).max(400),
  style: styleSchema,
  locked: z.boolean(),
  hidden: z.boolean(),
  text: z.string().max(200).optional(),
});
export type Drawing = z.infer<typeof drawingSchema>;

export const MAX_DRAWINGS = 300;
export const DEFAULT_STYLE: Style = { color: "#2563eb", width: 2, dash: "solid" };

export function newId(): string {
  return `d${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

export function makeDrawing(type: ToolType, points: Pt[], style: Style = DEFAULT_STYLE, text?: string): Drawing {
  return { id: newId(), type, points, style, locked: false, hidden: false, ...(text !== undefined ? { text } : {}) };
}

export function storageKey(instrumentId: number, adjust: string): string {
  return `drawings:v2:${instrumentId}:${adjust}`;
}

const legacySchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("h"), price: z.number().finite() }),
  z.object({ type: z.literal("t"), t1: z.string(), p1: z.number().finite(), t2: z.string(), p2: z.number().finite() }),
]);

/** Version 1 stored only horizontal and trend lines; they are carried over, not lost. */
export function migrateLegacy(raw: string | null): Drawing[] {
  if (!raw) return [];
  try {
    const arr: unknown = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    return arr.flatMap((x) => {
      const r = legacySchema.safeParse(x);
      if (!r.success) return [];
      return [r.data.type === "h" ? makeDrawing("hline", [{ t: "", p: r.data.price }]) : makeDrawing("trend", [{ t: r.data.t1, p: r.data.p1 }, { t: r.data.t2, p: r.data.p2 }])];
    });
  } catch {
    return [];
  }
}

/** Whatever is stored is untrusted: anything malformed is dropped, never rendered. */
export function parseDrawings(raw: string | null): Drawing[] {
  if (!raw) return [];
  try {
    const arr: unknown = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    return arr.flatMap((x) => {
      const r = drawingSchema.safeParse(x);
      return r.success ? [r.data] : [];
    }).slice(0, MAX_DRAWINGS);
  } catch {
    return [];
  }
}

export function load(instrumentId: number, adjust: string, store: Pick<Storage, "getItem"> = window.localStorage): Drawing[] {
  try {
    const v2 = parseDrawings(store.getItem(storageKey(instrumentId, adjust)));
    if (v2.length) return v2;
    return migrateLegacy(store.getItem(`drawings:v1:${instrumentId}:${adjust}`));
  } catch {
    return [];
  }
}

export function save(instrumentId: number, adjust: string, list: Drawing[], store: Pick<Storage, "setItem"> = window.localStorage): void {
  try {
    store.setItem(storageKey(instrumentId, adjust), JSON.stringify(list));
  } catch {
    /* storage unavailable or full: drawings simply do not persist */
  }
}
