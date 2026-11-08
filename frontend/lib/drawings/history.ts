import { MAX_DRAWINGS, type Drawing } from "./model";

// Undo/redo over whole drawing lists. Every edit is one step; dragging commits once, on release.

export type History = { list: Drawing[]; past: Drawing[][]; future: Drawing[][] };
export const MAX_STEPS = 100;

export const initial = (list: Drawing[] = []): History => ({ list, past: [], future: [] });

function commit(h: History, list: Drawing[]): History {
  return { list: list.slice(-MAX_DRAWINGS), past: [...h.past, h.list].slice(-MAX_STEPS), future: [] };
}

export const add = (h: History, d: Drawing): History => commit(h, [...h.list, d]);
export const remove = (h: History, id: string): History => (h.list.some((d) => d.id === id) ? commit(h, h.list.filter((d) => d.id !== id)) : h);
export const clear = (h: History): History => (h.list.length ? commit(h, []) : h);

/** Replace one drawing by id (a finished edit). */
export function update(h: History, d: Drawing): History {
  return h.list.some((x) => x.id === d.id) ? commit(h, h.list.map((x) => (x.id === d.id ? d : x))) : h;
}

/** Hide or show every drawing at once. */
export function setAllHidden(h: History, hidden: boolean): History {
  return h.list.every((d) => d.hidden === hidden) ? h : commit(h, h.list.map((d) => ({ ...d, hidden })));
}

export function undo(h: History): History {
  const prev = h.past[h.past.length - 1];
  return prev ? { list: prev, past: h.past.slice(0, -1), future: [h.list, ...h.future] } : h;
}

export function redo(h: History): History {
  const next = h.future[0];
  return next ? { list: next, past: [...h.past, h.list], future: h.future.slice(1) } : h;
}

/** Replace the list without a history step (loading another instrument or basis). */
export const reset = (list: Drawing[]): History => initial(list);
