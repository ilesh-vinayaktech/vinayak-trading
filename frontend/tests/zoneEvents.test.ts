import { describe, expect, it } from "vitest";
import { zoneEvents } from "@/lib/zoneEvents";

describe("zone events", () => {
  it("marks a top the day the score leaves extreme greed and a bottom the day it leaves extreme fear", () => {
    const s = [50, 60, 72, 75, 68, 60, ...Array(12).fill(50), 28, 20, 27, 35, 45];
    expect(zoneEvents(s)).toEqual([{ index: 4, kind: "top" }, { index: 21, kind: "bottom" }]);
  });
  it("marks nothing while the score stays in the middle or is still inside an extreme", () => {
    expect(zoneEvents([50, 55, 45, 52])).toEqual([]);
    expect(zoneEvents([50, 72, 75, 80])).toEqual([]);
  });
  it("drops a mark that comes within ten days of the last one", () => {
    expect(zoneEvents([50, 72, 68, 72, 68, 50])).toEqual([{ index: 2, kind: "top" }]);
  });
});
