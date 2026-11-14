import { describe, expect, it } from "vitest";
import { EXTEND_WITHIN_BARS, reachedLeftEdge, viewToRestore } from "@/lib/chartView";

describe("loading earlier history while panning", () => {
  it("asks for it only when the user moved the view to the left edge, never for the first fit", () => {
    expect(reachedLeftEdge({ from: 0 }, false)).toBe(false); // the initial fit sits at the edge: that is not a request
    expect(reachedLeftEdge({ from: 0 }, true)).toBe(true);
    expect(reachedLeftEdge({ from: -40 }, true)).toBe(true); // dragged past the first bar
    expect(reachedLeftEdge({ from: EXTEND_WITHIN_BARS - 0.1 }, true)).toBe(true);
    expect(reachedLeftEdge({ from: EXTEND_WITHIN_BARS }, true)).toBe(false); // exactly at the limit: still plenty of bars on screen
    expect(reachedLeftEdge({ from: 80 }, true)).toBe(false);
    expect(reachedLeftEdge(null, true)).toBe(false);
  });
});

describe("keeping the user's place when earlier history arrives", () => {
  const saved = { key: "7|none|1w", range: { from: "2025-01-06", to: "2026-11-09" } };
  it("restores the view only for the same chart and only after an extension", () => {
    expect(viewToRestore(saved, "7|none|1w", true)).toEqual(saved.range);
    expect(viewToRestore(saved, "7|none|1w", false)).toBeNull(); // a range preset: fit the new data
    expect(viewToRestore(saved, "7|none|1d", true)).toBeNull(); // another timeframe
    expect(viewToRestore(saved, "8|none|1w", true)).toBeNull(); // another stock
    expect(viewToRestore(null, "7|none|1w", true)).toBeNull();
  });
});
