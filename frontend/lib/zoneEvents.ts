export type ZoneEvent = { index: number; kind: "top" | "bottom" };

const GAP = 10; // trading days a mark needs to stay clear of the one before it

/**
 * Where the market "tops out" or "bottoms out": the day the score comes back out of extreme greed (below 70) or extreme fear (above 30) after being in it
 * within the last 5 days. Marked on the day it is known, never earlier, so nothing here looks ahead. Marks closer than 10 days to the last one are dropped.
 */
export function zoneEvents(scores: readonly number[]): ZoneEvent[] {
  const out: ZoneEvent[] = [];
  let lastAt = -GAP;
  scores.forEach((v, i) => {
    if (i === 0 || i - lastAt < GAP) return;
    const recent = scores.slice(Math.max(0, i - 5), i);
    const kind = v < 70 && recent.some((r) => r >= 70) ? "top" : v > 30 && recent.some((r) => r <= 30) ? "bottom" : null;
    if (kind === null) return;
    out.push({ index: i, kind });
    lastAt = i;
  });
  return out;
}
