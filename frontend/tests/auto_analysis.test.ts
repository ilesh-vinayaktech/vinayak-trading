import { describe, expect, it } from "vitest";
import { analyze, cluster, countsOf, patterns, swings, type AutoBar } from "@/lib/autoAnalysis";

const bar = (h: number, l: number, c: number, v = 1000, o = c): AutoBar => ({ open: String(o), high: String(h), low: String(l), close: String(c), volume: String(v) });
/** A zig-zag around a rising drift: lows and highs alternate every `half` bars so swings exist. */
function zig(n: number, base = 100, drift = 0.3, amp = 8, half = 8): AutoBar[] {
  return Array.from({ length: n }, (_, i) => {
    const phase = Math.floor(i / half) % 2 === 0 ? (i % half) / half : 1 - (i % half) / half;
    const mid = base + drift * i + amp * phase;
    return bar(mid + 1, mid - 1, mid);
  });
}

describe("swings and levels", () => {
  it("finds the highest and lowest bar of the 5 either side, once each", () => {
    const bars = Array.from({ length: 21 }, (_, i) => bar(i === 10 ? 15 : 10, i === 15 ? 4 : 9, 9.5));
    const s = swings(bars);
    expect(s.highs).toEqual([{ i: 10, p: 15 }]);
    expect(s.lows).toEqual([{ i: 15, p: 4 }]);
  });
  it("joins prices within 1.5% into one level and counts the touches", () => {
    expect(cluster([100, 101, 101.4, 120, 121])).toEqual([{ price: expect.closeTo(100.8, 5), touches: 3 }, { price: 120.5, touches: 2 }]);
  });
});

describe("analyze", () => {
  it("draws nothing for fewer than 30 bars", () => expect(analyze(zig(20))).toEqual({ lines: [], trends: [], markers: [] }));

  it("gives every layer for a trending, zig-zagging stock, with resistance above and support below the last close", () => {
    const bars = zig(160);
    const a = analyze(bars);
    const last = Number(bars[159]?.close);
    const kinds = new Set(a.lines.map((l) => l.kind));
    for (const k of ["levels", "pivots", "fib", "range", "profile"]) expect(kinds.has(k as never)).toBe(true);
    expect(a.lines.filter((l) => l.kind === "levels" && l.label.startsWith("R")).every((l) => l.price > last)).toBe(true);
    expect(a.lines.filter((l) => l.kind === "levels" && l.label.startsWith("S")).every((l) => l.price <= last)).toBe(true);
    expect(a.lines.filter((l) => l.kind === "fib")).toHaveLength(5);
    expect(a.lines.filter((l) => l.kind === "range")).toHaveLength(2);
  });

  it("puts the classic pivot between S1 and R1 and computes it from the previous bar", () => {
    const bars = zig(60);
    const prev = bars[58] as AutoBar;
    const p = (Number(prev.high) + Number(prev.low) + Number(prev.close)) / 3;
    const piv = analyze(bars).lines.filter((l) => l.kind === "pivots");
    const by = (name: string) => piv.find((l) => l.label.startsWith(name))?.price as number;
    expect(by("Pivot")).toBeCloseTo(p, 6);
    expect(by("S1")).toBeLessThan(by("Pivot"));
    expect(by("R1")).toBeGreaterThan(by("Pivot"));
  });

  it("keeps the volume profile's value area around its busiest price, and skips it when nothing traded", () => {
    const heavy = zig(60).map((b, i) => (i > 40 ? { ...b, volume: "100000" } : b));
    const prof = analyze(heavy).lines.filter((l) => l.kind === "profile");
    const poc = prof.find((l) => l.label.startsWith("Most"))?.price as number;
    expect(prof.find((l) => l.label.startsWith("Value area high"))?.price).toBeGreaterThanOrEqual(poc);
    expect(prof.find((l) => l.label.startsWith("Value area low"))?.price).toBeLessThanOrEqual(poc);
    expect(analyze(zig(60).map((b) => ({ ...b, volume: "0" }))).lines.some((l) => l.kind === "profile")).toBe(false);
  });

  it("keeps a trend line a close has broken through, in grey and marked broken, and gives no channel for it", () => {
    const rising = zig(120, 100, 0.5);
    const live = analyze(rising).trends.filter((t) => t.kind === "trend" && t.label.startsWith("Rising support"));
    expect(live.length).toBeGreaterThan(0);
    expect(live.every((t) => t.toIndex === 119 && t.color === "#059669")).toBe(true);
    const broken = analyze([...rising.slice(0, 119), bar(60, 50, 55)]); // a collapse on the last bar
    const rs = broken.trends.filter((t) => t.kind === "trend" && t.label.startsWith("Rising support"));
    expect(rs.length).toBeGreaterThan(0);
    expect(rs.every((t) => t.label.endsWith("broken") && t.color === "#94a3b8" && t.dash === "dotted")).toBe(true);
    expect(broken.trends.filter((t) => t.kind === "channels" && t.label === "Channel top")).toHaveLength(0);
  });
  it("draws a major and a minor line from different swings, never the same pair twice, and a parallel channel line for each unbroken one", () => {
    const a = analyze(zig(200, 100, 0.4, 8, 12));
    const lines = a.trends.filter((t) => t.kind === "trend");
    expect(new Set(lines.map((t) => `${t.label}|${t.fromIndex}`)).size).toBe(lines.length);
    for (const ch of a.trends.filter((t) => t.kind === "channels")) {
      const slope = (ch.toPrice - ch.fromPrice) / (ch.toIndex - ch.fromIndex);
      const twin = lines.find((t) => t.fromIndex === ch.fromIndex && Math.abs((t.toPrice - t.fromPrice) / (t.toIndex - t.fromIndex) - slope) < 1e-9);
      expect(twin).toBeDefined(); // parallel to a trend line that starts at the same bar
      expect(ch.label === "Channel top" ? ch.toPrice > (twin as { toPrice: number }).toPrice : ch.toPrice < (twin as { toPrice: number }).toPrice).toBe(true);
    }
  });
});

describe("candlestick patterns", () => {
  /** 20 quiet bars (range 2) that fall 1 a bar, then the pattern bars. */
  const fall = () => Array.from({ length: 20 }, (_, i) => bar(110 - i + 1, 110 - i - 1, 110 - i, 1000, 110 - i + 0.5));
  const rise = () => Array.from({ length: 20 }, (_, i) => bar(90 + i + 1, 90 + i - 1, 90 + i, 1000, 90 + i - 0.5));
  const only = (bars: AutoBar[]) => patterns(bars).filter((m) => m.index === bars.length - 1).map((m) => m.text);

  it("marks a hammer after a fall (long lower shadow, small body at the top) as bullish, below the bar", () => {
    const bars = [...fall(), bar(91.7, 84, 91.5, 1000, 91)]; // body 0.5, lower shadow 7, upper 0.2
    expect(only(bars)).toEqual(["Hammer"]);
    expect(patterns(bars).at(-1)).toMatchObject({ position: "belowBar", shape: "arrowUp" });
  });
  it("marks patterns anywhere in the loaded bars, not only the most recent ones", () => {
    const fall = Array.from({ length: 20 }, (_, i) => bar(110 - i + 1, 110 - i - 1, 110 - i, 1000, 110 - i + 0.5));
    const quiet = Array.from({ length: 400 }, () => bar(91, 89, 90, 1000, 90.2));
    const bars = [...fall, bar(91.7, 84, 91.5, 1000, 91), ...quiet]; // a hammer at bar 20 of 421
    expect(patterns(bars).filter((m) => m.index === 20).map((m) => m.text)).toEqual(["Hammer"]);
  });
  it("calls the same shape after a rise a hanging man, bearish, above the bar", () => {
    const bars = [...rise(), bar(110.2, 102, 110, 1000, 109.5)];
    expect(only(bars)).toEqual(["Hanging man"]);
    expect(patterns(bars).at(-1)).toMatchObject({ position: "aboveBar", shape: "arrowDown" });
  });
  it("marks a shooting star after a rise", () => {
    expect(only([...rise(), bar(118, 109.8, 110, 1000, 110.5)])).toEqual(["Shooting star"]);
  });
  it("marks a bullish engulfing after a fall and a bearish one after a rise", () => {
    expect(only([...fall(), bar(91, 87, 88, 1000, 90.5), bar(94, 86.5, 93, 1000, 87.5)])).toEqual(["Engulfing"]);
    expect(only([...rise(), bar(112, 108, 111, 1000, 108.5), bar(113, 105, 106, 1000, 111.5)])).toEqual(["Engulfing"]);
  });
  it("marks a morning star: a big down bar, a small one, then an up bar closing past the first one's midpoint", () => {
    expect(only([...fall(), bar(92, 85, 86, 1000, 91), bar(86.5, 84, 85, 1000, 85.5), bar(92, 85, 91, 1000, 85.5)])).toEqual(["Morning star"]);
  });
  it("does not mark a reversal pattern that comes after the wrong trend", () => {
    expect(only([...fall(), bar(118, 109.8, 110, 1000, 110.5)])).not.toContain("Shooting star"); // a shooting star needs a rise first
    expect(only([...rise(), bar(91.7, 84, 91.5, 1000, 91)])).not.toContain("Hammer"); // a hammer needs a fall first
  });
  it("marks an inside-bar breakout: a close above the high of the bar that held the inside bar", () => {
    const base = [...fall(), bar(96, 88, 94, 1000, 89), bar(93, 90, 92, 1000, 91)]; // mother bar, then a bar wholly inside it
    expect(only([...base, bar(99, 93, 98, 1000, 93.5)])).toEqual(["IB breakout (weak)"]);
    expect(patterns([...base, bar(99, 93, 98, 1000, 93.5)]).at(-1)).toMatchObject({ position: "belowBar", shape: "arrowUp" });
    expect(only([...base, bar(95, 91, 94.5, 1000, 92)])).not.toContain("IB breakout (weak)"); // closes inside the mother bar: no break yet
  });
  it("marks an inside-bar breakdown, also after several inside bars in a row", () => {
    const base = [...rise(), bar(112, 104, 110, 1000, 105), bar(110, 107, 108, 1000, 107), bar(109.5, 107.5, 109, 1000, 107.8)];
    expect(only([...base, bar(107, 100, 101, 1000, 106.5)])).toEqual(["IB breakdown (weak)"]);
    expect(patterns([...base, bar(107, 100, 101, 1000, 106.5)]).at(-1)).toMatchObject({ position: "aboveBar", shape: "arrowDown" });
  });
  it("draws an inside-bar breakout green only when it goes with an uptrend (50-bar average rising, price above it); other breaks are grey and weak", () => {
    const uptrend = Array.from({ length: 80 }, (_, i) => bar(100 + i * 0.5 + 1, 100 + i * 0.5 - 1, 100 + i * 0.5, 1000, 100 + i * 0.5 - 0.3));
    const top = 100 + 79 * 0.5;
    const setup = [...uptrend, bar(top + 6, top - 2, top + 2, 1000, top - 1), bar(top + 3, top + 0.5, top + 1.5, 1000, top + 1)]; // mother (range 8) then a clearly smaller inside bar
    const strong = patterns([...setup, bar(top + 9, top + 3, top + 8, 1000, top + 3.5)]).at(-1);
    expect(strong).toMatchObject({ text: "IB breakout, with trend", color: "#059669", position: "belowBar" });
    const down = patterns([...Array.from({ length: 80 }, (_, i) => bar(150 - i * 0.5 + 1, 150 - i * 0.5 - 1, 150 - i * 0.5, 1000, 150 - i * 0.5 + 0.3)), bar(114, 106, 110, 1000, 107), bar(111, 108, 109, 1000, 110), bar(118, 109, 117, 1000, 110)]).at(-1);
    expect(down).toMatchObject({ text: "IB breakout (weak)", color: "#94a3b8" }); // an uptrend break inside a downtrend: grey
  });
  it("does not count a bar that is only just inside its mother (the MARKSANS 10-11 Sep 2026 case: 89% of its range) as an inside bar", () => {
    const weak = [...fall(), bar(96, 88, 94, 1000, 89), bar(95.6, 88.4, 92, 1000, 91)]; // inside by 0.4 either side, range 7.2 of 8
    expect(only([...weak, bar(99, 93, 98, 1000, 93.5)])).not.toContain("IB breakout (weak)");
    expect(only([...weak.slice(0, -1), bar(93, 90, 92, 1000, 91), bar(99, 93, 98, 1000, 93.5)])).toEqual(["IB breakout (weak)"]); // the same mother with a clearly smaller inside bar does
  });
  it("needs every inside bar of a run to be clearly smaller, not just the last", () => {
    const run = [...fall(), bar(96, 88, 94, 1000, 89), bar(95.5, 89, 92, 1000, 91), bar(93, 91, 92.5, 1000, 91.5)]; // first inside bar is 6.5 of 8
    expect(only([...run, bar(99, 93, 98, 1000, 93.5)])).not.toContain("IB breakout (weak)");
  });
  it("ignores an inside bar whose mother bar is tiny, and a break with no inside bar before it", () => {
    expect(only([...fall(), bar(92.6, 92.1, 92.3, 1000, 92.2), bar(92.5, 92.2, 92.4, 1000, 92.3), bar(99, 93, 98, 1000, 93.5)])).not.toContain("IB breakout (weak)");
    expect(only([...fall(), bar(96, 88, 94, 1000, 89), bar(99, 90, 98, 1000, 93.5)])).not.toContain("IB breakout (weak)"); // second bar pokes above: not inside
  });
  it("draws every pattern grey except the one that beat a random stock in the 7-year study (an inside-bar breakout with the trend)", () => {
    const fall = Array.from({ length: 20 }, (_, i) => bar(110 - i + 1, 110 - i - 1, 110 - i, 1000, 110 - i + 0.5));
    for (const bars of [[...fall, bar(91.7, 84, 91.5, 1000, 91)], [...fall, bar(91, 87, 88, 1000, 90.5), bar(94, 86.5, 93, 1000, 87.5)], [...fall, bar(110, 100, 105, 1000, 105.2)]]) {
      expect(patterns(bars).at(-1)?.color).toBe("#94a3b8");
    }
  });
  it("marks a doji only when it is a fair size against the recent bars", () => {
    expect(only([...fall(), bar(110, 100, 105, 1000, 105.2)])).toEqual(["Doji"]);
    expect(only([...fall(), bar(86.4, 85.6, 86, 1000, 86.02)])).toEqual([]); // tiny range: not a doji worth showing
  });
});

describe("channels", () => {
  it("are set by the price between the two anchor swings, so a later spike does not stretch them", () => {
    const bars = zig(200, 100, 0.4, 8, 12);
    const spiked = [...bars.slice(0, 199), { ...(bars[199] as AutoBar), high: "9999" }]; // one wild high on the last bar; no close changes, so no line breaks
    const key = (a: ReturnType<typeof analyze>) => a.trends.filter((t) => t.kind === "channels").map((t) => `${t.label}|${t.fromIndex}|${t.fromPrice.toFixed(6)}|${t.toPrice.toFixed(6)}`).sort();
    expect(key(analyze(bars)).length).toBeGreaterThan(0);
    expect(key(analyze(spiked))).toEqual(key(analyze(bars)));
  });
});

describe("channels the price has left", () => {
  it("are not drawn once the last close is more than 1% beyond the far edge, and come back while it is inside", () => {
    const base = zig(160, 100, 0.4, 8, 12);
    const inside = analyze(base).trends.filter((t) => t.kind === "channels");
    expect(inside.length).toBeGreaterThan(0);
    const last = Number((base[159] as AutoBar).close);
    for (const ch of inside) expect(ch.base).toBeDefined(); // the base trend line travels with its channel
    const rocket = [...base, ...Array.from({ length: 4 }, (_, i) => bar(400 + i * 40, 380 + i * 40, 390 + i * 40))]; // a burst far above any channel
    expect(analyze(rocket).trends.filter((t) => t.kind === "channels" && t.label === "Channel top")).toHaveLength(0);
    expect(last).toBeGreaterThan(0);
  });
});

describe("countsOf", () => {
  it("counts trend lines and channel lines apart, so the Trend lines number is the lines you can see with Channels off", () => {
    const a = analyze(zig(200, 100, 0.4, 8, 12));
    const c = countsOf(a);
    expect(c.trend).toBe(a.trends.filter((t) => t.kind === "trend").length);
    expect(c.channels).toBe(a.trends.filter((t) => t.kind === "channels").length);
    expect(c.trend + c.channels).toBe(a.trends.length);
    expect(c.channels).toBeGreaterThan(0); // the fixture has unbroken lines, so the old count (trends.length) would have been too high
    expect(c.patterns).toBe(a.markers.length);
    expect(c.levels + c.pivots + c.fib + c.range + c.profile).toBe(a.lines.length);
  });
});
