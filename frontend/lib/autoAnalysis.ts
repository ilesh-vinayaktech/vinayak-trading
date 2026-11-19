/** Everything the chart can draw by itself from the bars it already has: support and resistance, trend lines, pivot points,
 * Fibonacci retracement, range high and low, and the volume profile's busiest price and value area. Pure: bars in, lines out.
 * The lines describe where the price paused before; they are not forecasts. */

export type AutoKind = "levels" | "trend" | "channels" | "pivots" | "fib" | "range" | "profile" | "patterns";
export type AutoBar = { open: string; high: string; low: string; close: string; volume: string };
export type AutoLine = { kind: AutoKind; label: string; color: string; dash: "solid" | "dashed" | "dotted"; width: 1 | 2; price: number };
/** A slanted line between two bars (by index), ending on the last bar: a trend line, or the parallel line that makes it a channel. */
export type AutoTrend = { kind: "trend" | "channels"; label: string; color: string; dash: "solid" | "dashed" | "dotted"; width: 1 | 2; fromIndex: number; fromPrice: number; toIndex: number; toPrice: number; base?: AutoTrend };
/** A candlestick pattern, marked on the bar that completes it. */
export type AutoMarker = { index: number; text: string; position: "aboveBar" | "belowBar"; shape: "arrowUp" | "arrowDown" | "circle"; color: string };
export type Analysis = { lines: AutoLine[]; trends: AutoTrend[]; markers: AutoMarker[] };

export const KINDS: { kind: AutoKind; label: string; color: string; hint: string }[] = [
  { kind: "levels", label: "Support and resistance", color: "#059669", hint: "Prices where swings turned before: the 3 nearest each side, with how often they were touched" },
  { kind: "trend", label: "Trend lines", color: "#2563eb", hint: "Rising support through the last two higher swing lows, falling resistance through the last two lower swing highs, at two scales: major (thick, big swings) and minor (thin). A line a close has broken through stays in grey, marked broken, for 120 bars" },
  { kind: "channels", label: "Channels", color: "#64748b", hint: "A parallel line to each unbroken trend line through the furthest opposite price between the two swings the line is drawn through, so the trend reads as a channel. Shown only while the price is still inside it; with Trend lines off, its base line is drawn too" },
  { kind: "pivots", label: "Pivot points", color: "#7c3aed", hint: "Classic pivot, R1, R2, S1, S2 from the previous bar" },
  { kind: "fib", label: "Fibonacci retracement", color: "#d97706", hint: "23.6 to 78.6% retracements of the main swing in the last 120 bars" },
  { kind: "range", label: "Range high and low", color: "#0ea5e9", hint: "Highest high and lowest low of the last 252 bars (a year of daily bars)" },
  { kind: "patterns", label: "Candlestick patterns", color: "#0f172a", hint: "Hammer, shooting star, engulfing, morning and evening star, three soldiers or crows, doji, and inside-bar breaks. Tested on 7 years of NSE data, none of them beat a random stock except an inside-bar breakout that goes with an existing uptrend, so only that one is green; every other pattern is shown in grey as a shape, not a signal. Marked on every bar loaded; reversal patterns only where the trend before them fits" },
  { kind: "profile", label: "Volume profile", color: "#c026d3", hint: "Busiest price and the zone holding 70% of the volume, last 120 bars" },
];

const num = Number;
const RED = "#dc2626", GREEN = "#059669";
type Swing = { i: number; p: number };

/** Swing highs and lows: a bar that is the highest (lowest) of the `k` bars either side. A swing is only known `k` bars later. */
export function swings(bars: AutoBar[], k = 5): { highs: Swing[]; lows: Swing[] } {
  const highs: Swing[] = [], lows: Swing[] = [];
  for (let i = k; i < bars.length - k; i++) {
    const h = num(bars[i]?.high), l = num(bars[i]?.low);
    let isHigh = true, isLow = true;
    for (let j = i - k; j <= i + k; j++) {
      const b = bars[j];
      if (j === i || !b) continue;
      if (num(b.high) > h || (j < i && num(b.high) === h)) isHigh = false; // of equal highs the first counts
      if (num(b.low) < l || (j < i && num(b.low) === l)) isLow = false;
    }
    if (isHigh) highs.push({ i, p: h });
    if (isLow) lows.push({ i, p: l });
  }
  return { highs, lows };
}

/** Swing prices within 1.5% of the first of a group are one level; its price is the group's mean and its strength the number of swings. */
export function cluster(prices: number[], within = 0.015): { price: number; touches: number }[] {
  const sorted = [...prices].sort((a, b) => a - b);
  const out: { price: number; touches: number }[] = [];
  let group: number[] = [];
  const flush = () => {
    if (group.length) out.push({ price: group.reduce((s, v) => s + v, 0) / group.length, touches: group.length });
    group = [];
  };
  for (const p of sorted) {
    if (group.length && p > (group[0] as number) * (1 + within)) flush();
    group.push(p);
  }
  flush();
  return out;
}

const GOOD = "#059669";

/** Candlestick patterns on every bar loaded, one per bar at most (a longer pattern wins over a shorter one). A reversal pattern counts only after the
 * kind of move it reverses (4 bars of fall before a bullish one, of rise before a bearish one), and a bar must be a fair size against the recent average range. */
export function patterns(bars: AutoBar[]): AutoMarker[] {
  const n = bars.length, out: AutoMarker[] = [];
  const o = (i: number) => num((bars[i] as AutoBar).open), h = (i: number) => num((bars[i] as AutoBar).high), l = (i: number) => num((bars[i] as AutoBar).low), c = (i: number) => num((bars[i] as AutoBar).close);
  const body = (i: number) => Math.abs(c(i) - o(i)), rng = (i: number) => h(i) - l(i);
  const up = (i: number) => c(i) > o(i), down = (i: number) => c(i) < o(i);
  const avg = (i: number) => { let t = 0; for (let j = i - 14; j < i; j++) t += rng(j); return t / 14; };
  /** An inside bar sits wholly inside the bar before it (the "mother"), and is clearly compressed: at most 60% of the mother's range. A run of such bars counts as one setup.
   * The bar that closes beyond the mother's high or low after the run is the break. The mother must be at least as big as the recent average bar, or the setup is just noise. */
  const inside = (j: number) => j >= 1 && h(j) < h(j - 1) && l(j) > l(j - 1);
  const insideBreak = (i: number): "up" | "down" | null => {
    let m = i - 1;
    while (inside(m)) m--;
    if (m === i - 1 || m < 0 || rng(m) < avg(i)) return null; // no inside bar just before, or the mother bar is smaller than a normal one
    for (let j = m + 1; j < i; j++) if (rng(j) > 0.6 * rng(m)) return null; // an inside bar that is not clearly smaller than its mother is not a squeeze
    return c(i) > h(m) ? "up" : c(i) < l(m) ? "down" : null;
  };
  /** The trend the study used: the bar before closed above its 50-bar average, and that average is higher than it was 10 bars ago. */
  const sma = (i: number) => { let t = 0; for (let j = i - 49; j <= i; j++) t += c(j); return t / 50; };
  const uptrend = (i: number) => i >= 60 && c(i - 1) > sma(i) && sma(i) > sma(i - 10);
  const after = (i: number, dir: "fall" | "rise") => (dir === "fall" ? c(i - 1) < c(i - 5) : c(i - 1) > c(i - 5));
  for (let i = 14; i < n; i++) {
    const a = avg(i);
    if (!(a > 0)) continue;
    const big = (j: number) => body(j) >= 0.5 * a;
    const lower = Math.min(o(i), c(i)) - l(i), upper = h(i) - Math.max(o(i), c(i));
    // scripts/study_candle_patterns.py (every liquid NSE stock since 2019, 5/10/20 sessions): none of these beat a random stock by a usable margin (the bullish
    // reversals did slightly worse), so they are drawn grey: the shape is shown, but not as a signal. Only the inside-bar breakout with the trend (below) is green.
    const mark = (text: string, kind: "bull" | "bear" | "flat") => out.push({ index: i, text, position: kind === "bull" ? "belowBar" : "aboveBar", shape: kind === "bull" ? "arrowUp" : kind === "bear" ? "arrowDown" : "circle", color: "#94a3b8" });
    if (up(i) && up(i - 1) && up(i - 2) && big(i) && big(i - 1) && big(i - 2) && c(i) > c(i - 1) && c(i - 1) > c(i - 2) && o(i) > o(i - 1) && o(i - 1) > o(i - 2) && after(i - 2, "fall")) mark("3 soldiers", "bull");
    else if (down(i) && down(i - 1) && down(i - 2) && big(i) && big(i - 1) && big(i - 2) && c(i) < c(i - 1) && c(i - 1) < c(i - 2) && o(i) < o(i - 1) && o(i - 1) < o(i - 2) && after(i - 2, "rise")) mark("3 crows", "bear");
    else if (insideBreak(i) !== null) {
      // scripts/study_inside_bar.py (every liquid NSE stock since 2019, 5/10/20 sessions): only a breakout with an existing uptrend beat a random stock; breakdowns and
      // breakouts against or without a trend did not (48% against 50%), and heavy volume did not help. So only that one is drawn as a real signal, the rest grey.
      const dir = insideBreak(i);
      const strong = dir === "up" && uptrend(i);
      out.push({ index: i, text: strong ? "IB breakout, with trend" : `IB ${dir === "up" ? "breakout" : "breakdown"} (weak)`, position: dir === "up" ? "belowBar" : "aboveBar", shape: dir === "up" ? "arrowUp" : "arrowDown", color: strong ? GOOD : "#94a3b8" });
    }
    else if (down(i - 2) && big(i - 2) && body(i - 1) <= 0.3 * body(i - 2) && up(i) && c(i) > (o(i - 2) + c(i - 2)) / 2 && after(i - 2, "fall")) mark("Morning star", "bull");
    else if (up(i - 2) && big(i - 2) && body(i - 1) <= 0.3 * body(i - 2) && down(i) && c(i) < (o(i - 2) + c(i - 2)) / 2 && after(i - 2, "rise")) mark("Evening star", "bear");
    else if (down(i - 1) && up(i) && o(i) <= c(i - 1) && c(i) >= o(i - 1) && body(i) > body(i - 1) && big(i) && after(i, "fall")) mark("Engulfing", "bull");
    else if (up(i - 1) && down(i) && o(i) >= c(i - 1) && c(i) <= o(i - 1) && body(i) > body(i - 1) && big(i) && after(i, "rise")) mark("Engulfing", "bear");
    else if (rng(i) >= 0.5 * a && lower >= 2 * body(i) && upper <= 0.5 * body(i) && body(i) > 0) { if (after(i, "fall")) mark("Hammer", "bull"); else if (after(i, "rise")) mark("Hanging man", "bear"); }
    else if (rng(i) >= 0.5 * a && upper >= 2 * body(i) && lower <= 0.5 * body(i) && body(i) > 0 && after(i, "rise")) mark("Shooting star", "bear");
    else if (rng(i) >= 0.7 * a && body(i) <= 0.1 * rng(i)) mark("Doji", "flat");
  }
  return out;
}

/** How many of each layer the analysis drew, for the checkbox list: trend lines and channel lines are counted apart, though they share one list. */
export function countsOf(a: Analysis): Record<AutoKind, number> {
  const c = Object.fromEntries(KINDS.map((k) => [k.kind, 0])) as Record<AutoKind, number>;
  for (const l of a.lines) c[l.kind] += 1;
  for (const t of a.trends) c[t.kind] += 1;
  c.patterns = a.markers.length;
  return c;
}

const money = (n: number) => n.toLocaleString("en-IN", { maximumFractionDigits: 2 });

export function analyze(bars: AutoBar[]): Analysis {
  const n = bars.length;
  const lines: AutoLine[] = [], trends: AutoTrend[] = [];
  if (n < 30) return { lines, trends, markers: [] };
  const last = num((bars[n - 1] as AutoBar).close);
  const sw = swings(bars);

  // support and resistance
  const lv = cluster([...sw.highs.map((s) => s.p), ...sw.lows.map((s) => s.p)]);
  const above = lv.filter((l) => l.price > last).sort((a, b) => a.price - b.price).slice(0, 3);
  const below = lv.filter((l) => l.price <= last).sort((a, b) => b.price - a.price).slice(0, 3);
  for (const l of above) lines.push({ kind: "levels", label: `R ${money(l.price)} · ${l.touches}×`, color: RED, dash: "dashed", width: l.touches >= 3 ? 2 : 1, price: l.price });
  for (const l of below) lines.push({ kind: "levels", label: `S ${money(l.price)} · ${l.touches}×`, color: GREEN, dash: "dashed", width: l.touches >= 3 ? 2 : 1, price: l.price });

  // trend lines at two scales: through the last two swing lows (must rise) and the last two swing highs (must fall). One a close has broken through stays, grey and
  // marked broken, for 120 bars. A channel is the parallel line through the furthest opposite price between the line's two anchor swings.
  const seen = new Set<string>();
  const trendsAt = (k: number, scale: "major" | "minor") => {
    const s2 = swings(bars, k);
    const make = (a: Swing, b: Swing, rising: boolean) => {
      const key = `${rising}-${a.i}-${b.i}`;
      if (seen.has(key)) return; // the same two swings already gave a minor line
      seen.add(key);
      const slope = (b.p - a.p) / (b.i - a.i);
      const at = (i: number) => a.p + slope * (i - a.i);
      let broke = -1;
      for (let i = b.i + 1; i < n && broke < 0; i++) {
        const cl = num((bars[i] as AutoBar).close);
        if (rising ? cl < at(i) * 0.995 : cl > at(i) * 1.005) broke = i;
      }
      if (broke >= 0 && n - 1 - broke > 120) return; // broken long ago: not worth drawing
      const name = `${rising ? "Rising support" : "Falling resistance"}${scale === "major" ? " (major)" : ""}${broke >= 0 ? ", broken" : ""}`;
      const color = broke >= 0 ? "#94a3b8" : rising ? GREEN : RED;
      const line: AutoTrend = { kind: "trend", label: name, color, dash: broke >= 0 ? "dotted" : scale === "major" ? "solid" : "dashed", width: scale === "major" && broke < 0 ? 2 : 1, fromIndex: a.i, fromPrice: a.p, toIndex: n - 1, toPrice: at(n - 1) };
      trends.push(line);
      if (broke >= 0) return;
      let off = 0;
      for (let i = a.i; i <= b.i; i++) off = Math.max(off, rising ? num((bars[i] as AutoBar).high) - at(i) : at(i) - num((bars[i] as AutoBar).low)); // the furthest price BETWEEN the two anchor swings, as a channel is drawn; a later spike must not stretch it
      // a channel the price has already left (closed beyond its far edge by more than 1%) no longer describes where it trades: not drawn
      const lastClose = num((bars[n - 1] as AutoBar).close), far = rising ? at(n - 1) + off : at(n - 1) - off;
      if (off <= 0 || (rising ? lastClose > far * 1.01 : lastClose < far * 0.99)) return;
      trends.push({ kind: "channels", label: rising ? "Channel top" : "Channel bottom", color: "#64748b", dash: "dotted", width: 1, fromIndex: a.i, fromPrice: rising ? a.p + off : a.p - off, toIndex: n - 1, toPrice: far, base: line });
    };
    const [l1, l2] = s2.lows.slice(-2), [h1, h2] = s2.highs.slice(-2);
    if (l1 && l2 && l2.p > l1.p) make(l1, l2, true);
    if (h1 && h2 && h2.p < h1.p) make(h1, h2, false);
  };
  trendsAt(5, "minor");
  trendsAt(15, "major");

  // classic pivot points from the previous bar
  const prev = bars[n - 2] as AutoBar;
  const H = num(prev.high), L = num(prev.low), P = (H + L + num(prev.close)) / 3;
  const piv: [string, number][] = [["R2", P + (H - L)], ["R1", 2 * P - L], ["Pivot", P], ["S1", 2 * P - H], ["S2", P - (H - L)]];
  for (const [name, price] of piv) lines.push({ kind: "pivots", label: `${name} ${money(price)}`, color: "#7c3aed", dash: "dotted", width: 1, price });

  // Fibonacci retracement of the main swing in the last 120 bars
  const w = bars.slice(-120);
  const hi = Math.max(...w.map((b) => num(b.high))), lo = Math.min(...w.map((b) => num(b.low)));
  if (hi > lo) {
    const up = w.findIndex((b) => num(b.low) === lo) < w.findIndex((b) => num(b.high) === hi); // the low came first: it rose, so it retraces down from the high
    for (const r of [0.236, 0.382, 0.5, 0.618, 0.786]) {
      const price = up ? hi - r * (hi - lo) : lo + r * (hi - lo);
      lines.push({ kind: "fib", label: `Fib ${Math.round(r * 1000) / 10}% ${money(price)}`, color: "#d97706", dash: "dotted", width: r === 0.618 ? 2 : 1, price });
    }
  }

  // range high and low
  const yr = bars.slice(-252);
  const top = Math.max(...yr.map((b) => num(b.high))), bottom = Math.min(...yr.map((b) => num(b.low)));
  lines.push({ kind: "range", label: `High ${money(top)} (${yr.length} bars)`, color: "#0ea5e9", dash: "solid", width: 1, price: top });
  lines.push({ kind: "range", label: `Low ${money(bottom)} (${yr.length} bars)`, color: "#0ea5e9", dash: "solid", width: 1, price: bottom });

  // volume profile: volume by price band; the busiest band, and the smallest run of bands around it holding 70% of the volume
  const total = w.reduce((s, b) => s + num(b.volume), 0);
  if (hi > lo && total > 0) {
    const N = 24, step = (hi - lo) / N;
    const vol = Array<number>(N).fill(0);
    for (const b of w) {
      const band = Math.min(N - 1, Math.floor(((num(b.high) + num(b.low) + num(b.close)) / 3 - lo) / step));
      vol[band] = (vol[band] as number) + num(b.volume);
    }
    const poc = vol.indexOf(Math.max(...vol));
    let a = poc, z = poc, got = vol[poc] as number;
    while (got < 0.7 * total && (a > 0 || z < N - 1)) {
      const below = a > 0 ? (vol[a - 1] as number) : -1, over = z < N - 1 ? (vol[z + 1] as number) : -1;
      if (over >= below) got += vol[++z] as number;
      else got += vol[--a] as number;
    }
    lines.push({ kind: "profile", label: `Most traded ${money(lo + (poc + 0.5) * step)}`, color: "#c026d3", dash: "solid", width: 2, price: lo + (poc + 0.5) * step });
    lines.push({ kind: "profile", label: `Value area high ${money(lo + (z + 1) * step)}`, color: "#c026d3", dash: "dashed", width: 1, price: lo + (z + 1) * step });
    lines.push({ kind: "profile", label: `Value area low ${money(lo + a * step)}`, color: "#c026d3", dash: "dashed", width: 1, price: lo + a * step });
  }
  return { lines, trends, markers: patterns(bars) };
}
