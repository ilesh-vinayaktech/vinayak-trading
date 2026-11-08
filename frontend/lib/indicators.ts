import type { IndicatorDef } from "@/lib/schemas";

// The indicators a user has put on the chart: a list of specs ("rsi:14", "macd:12:26:9") with a
// visibility flag. Preferences only: the VALUES are computed and tested by the backend.

export type Active = { uid: string; spec: string; visible: boolean };

export const MAX_ACTIVE = 12;
const KEY = "indicators:v1";

export function newUid(): string {
  return `i${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
}

/** name plus its default parameters, e.g. "macd:12:26:9" (the form the API echoes back). */
export function defaultSpec(def: IndicatorDef): string {
  return [def.name, ...def.params.map((p) => p.default)].join(":");
}

export function specOf(name: string, params: string[]): string {
  return [name, ...params].join(":");
}

export function paramsOf(spec: string): string[] {
  return spec.split(":").slice(1);
}

export function parseActive(raw: string | null): Active[] {
  if (!raw) return [];
  try {
    const arr: unknown = JSON.parse(raw);
    if (!Array.isArray(arr)) return [];
    return arr
      .flatMap((x): Active[] => {
        const o = x as Partial<Active> | null;
        return o && typeof o.uid === "string" && typeof o.spec === "string" && /^[a-z]+(:[0-9.]+)*$/.test(o.spec) && typeof o.visible === "boolean" ? [{ uid: o.uid, spec: o.spec, visible: o.visible }] : [];
      })
      .slice(0, MAX_ACTIVE);
  } catch {
    return [];
  }
}

export function loadActive(store: Pick<Storage, "getItem"> = window.localStorage): Active[] {
  try {
    return parseActive(store.getItem(KEY));
  } catch {
    return [];
  }
}

export function saveActive(list: Active[], store: Pick<Storage, "setItem"> = window.localStorage): void {
  try {
    store.setItem(KEY, JSON.stringify(list));
  } catch {
    /* storage unavailable or full: the list simply does not persist */
  }
}

export type Point = { time: string; value?: number };

/** Chart points for one output: a gap (no value yet) is a whitespace point, never a zero. */
export function toPoints(dates: string[], values: (string | null)[]): Point[] {
  return dates.map((time, i) => {
    const v = values[i];
    return v === null || v === undefined ? { time } : { time, value: Number.parseFloat(v) };
  });
}

/** Display text for a value: the backend's string with trailing zeros trimmed. */
export function trimNumber(s: string | null | undefined): string {
  if (s === null || s === undefined) return "—";
  return s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
}
