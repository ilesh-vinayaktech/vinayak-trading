import { describe, expect, it } from "vitest";
import { addDrawing, load, MAX_DRAWINGS, parseDrawings, save, storageKey, undoDrawing, type Drawing } from "@/lib/drawings";

const h = (price: number): Drawing => ({ type: "h", price });

describe("drawings", () => {
  it("keeps raw and adjusted drawings apart", () => {
    expect(storageKey(7, "none")).not.toBe(storageKey(7, "split"));
    expect(storageKey(7, "none")).not.toBe(storageKey(8, "none"));
  });

  it("round-trips valid drawings and drops anything malformed or untrusted", () => {
    const t: Drawing = { type: "t", t1: "2024-01-02", p1: 100.5, t2: "2024-03-04", p2: 120 };
    expect(parseDrawings(JSON.stringify([h(10), t]))).toEqual([h(10), t]);
    const mixed = [h(1), { type: "h", price: "x" }, { type: "t", t1: "yesterday", p1: 1, t2: "2024-01-01", p2: 2 }, { type: "evil", html: "<img onerror=x>" }, null, 5];
    expect(parseDrawings(JSON.stringify(mixed))).toEqual([h(1)]);
    expect(parseDrawings(null)).toEqual([]);
    expect(parseDrawings("not json")).toEqual([]);
    expect(parseDrawings('{"type":"h","price":1}')).toEqual([]); // not an array
    expect(parseDrawings(JSON.stringify([{ type: "h", price: null }]))).toEqual([]);
  });

  it("adds, undoes and caps the list", () => {
    let list: Drawing[] = [];
    for (let i = 0; i < MAX_DRAWINGS + 5; i++) list = addDrawing(list, h(i));
    expect(list).toHaveLength(MAX_DRAWINGS);
    expect(list[list.length - 1]).toEqual(h(MAX_DRAWINGS + 4));
    expect(undoDrawing([h(1), h(2)])).toEqual([h(1)]);
    expect(undoDrawing([])).toEqual([]);
    const many = Array.from({ length: MAX_DRAWINGS + 20 }, (_, i) => h(i));
    expect(parseDrawings(JSON.stringify(many))).toHaveLength(MAX_DRAWINGS);
  });

  it("persists per instrument and basis and survives a broken store", () => {
    const mem = new Map<string, string>();
    const store = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) };
    save(7, "none", [h(5)], store);
    expect(load(7, "none", store)).toEqual([h(5)]);
    expect(load(7, "split", store)).toEqual([]);
    const broken = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("full");
      },
    };
    expect(load(7, "none", broken)).toEqual([]);
    expect(() => save(7, "none", [h(1)], broken)).not.toThrow();
  });
});
