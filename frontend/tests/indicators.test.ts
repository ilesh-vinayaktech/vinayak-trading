import { describe, expect, it } from "vitest";
import { defaultSpec, loadActive, MAX_ACTIVE, paramsOf, parseActive, saveActive, specOf, toPoints, trimNumber } from "@/lib/indicators";
import type { IndicatorDef } from "@/lib/schemas";

const macd = { name: "macd", params: [{ default: "12" }, { default: "26" }, { default: "9" }] } as unknown as IndicatorDef;

describe("indicator preferences", () => {
  it("builds and splits specs", () => {
    expect(defaultSpec(macd)).toBe("macd:12:26:9");
    expect(defaultSpec({ name: "obv", params: [] } as unknown as IndicatorDef)).toBe("obv");
    expect(specOf("rsi", ["21"])).toBe("rsi:21");
    expect(paramsOf("bb:20:2.5")).toEqual(["20", "2.5"]);
    expect(paramsOf("obv")).toEqual([]);
  });

  it("keeps only well-formed saved entries and caps the list", () => {
    const good = { uid: "a", spec: "rsi:14", visible: true };
    const raw = JSON.stringify([good, { uid: "b", spec: "rm -rf", visible: true }, { uid: 3, spec: "sma:5", visible: true }, { uid: "c", spec: "sma:5", visible: "yes" }, null, "x", { uid: "d", spec: "bb:20:2.5", visible: false }]);
    expect(parseActive(raw)).toEqual([good, { uid: "d", spec: "bb:20:2.5", visible: false }]);
    expect(parseActive("junk")).toEqual([]);
    expect(parseActive('{"a":1}')).toEqual([]);
    expect(parseActive(null)).toEqual([]);
    const many = Array.from({ length: MAX_ACTIVE + 5 }, (_, i) => ({ uid: `u${i}`, spec: "sma:5", visible: true }));
    expect(parseActive(JSON.stringify(many))).toHaveLength(MAX_ACTIVE);
  });

  it("persists and survives a broken store", () => {
    const mem = new Map<string, string>();
    const store = { getItem: (k: string) => mem.get(k) ?? null, setItem: (k: string, v: string) => void mem.set(k, v) };
    saveActive([{ uid: "a", spec: "rsi:14", visible: true }], store);
    expect(loadActive(store)).toEqual([{ uid: "a", spec: "rsi:14", visible: true }]);
    const broken = { getItem: () => { throw new Error("no"); }, setItem: () => { throw new Error("full"); } };
    expect(loadActive(broken)).toEqual([]);
    expect(() => saveActive([], broken)).not.toThrow();
  });
});

describe("series points", () => {
  it("turns a gap into a whitespace point, never a zero", () => {
    expect(toPoints(["2024-01-01", "2024-01-02", "2024-01-03"], [null, "1.5000", "0.0000"])).toEqual([{ time: "2024-01-01" }, { time: "2024-01-02", value: 1.5 }, { time: "2024-01-03", value: 0 }]);
    expect(toPoints(["2024-01-01"], [])).toEqual([{ time: "2024-01-01" }]);
  });

  it("trims trailing zeros for display", () => {
    expect(trimNumber("70.5300")).toBe("70.53");
    expect(trimNumber("100.0000")).toBe("100");
    expect(trimNumber("1200")).toBe("1200");
    expect(trimNumber(null)).toBe("—");
    expect(trimNumber(undefined)).toBe("—");
  });
});
