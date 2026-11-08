import { z } from "zod";

// Chart annotations live in the browser only (localStorage), per instrument AND price basis: a line
// drawn on raw prices means nothing on split-adjusted prices, so the two never share drawings.
// They are notes on a chart, not data: they feed nothing else.

const drawingSchema = z.discriminatedUnion("type", [
  z.object({ type: z.literal("h"), price: z.number().finite() }),
  z.object({
    type: z.literal("t"),
    t1: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    p1: z.number().finite(),
    t2: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    p2: z.number().finite(),
  }),
]);
export type Drawing = z.infer<typeof drawingSchema>;

export const MAX_DRAWINGS = 200;

export function storageKey(instrumentId: number, adjust: string): string {
  return `drawings:v1:${instrumentId}:${adjust}`;
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

export function addDrawing(list: Drawing[], d: Drawing): Drawing[] {
  return [...list, d].slice(-MAX_DRAWINGS);
}

export function undoDrawing(list: Drawing[]): Drawing[] {
  return list.slice(0, -1);
}

export function load(instrumentId: number, adjust: string, store: Pick<Storage, "getItem"> = window.localStorage): Drawing[] {
  try {
    return parseDrawings(store.getItem(storageKey(instrumentId, adjust)));
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
