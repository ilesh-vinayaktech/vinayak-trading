"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { ApiError, api } from "@/lib/api/client";
import type { StockLevels as Levels } from "@/lib/schemas";

const STATE_TONE: Record<string, "good" | "bad" | "warn" | "neutral" | "info"> = {
  Breakout: "good",
  "Breakout, weak volume": "warn",
  Breakdown: "bad",
  "Breakdown, weak volume": "warn",
  "Testing resistance": "info",
  "Testing support": "info",
};
const money = (n: number) => n.toLocaleString("en-IN", { maximumFractionDigits: 2 });

const N = 20; // price bands in the ladder

/**
 * A price ladder, highest price at the top: one row per price band with the volume traded there (last 120 days), and the current price,
 * the nearest resistances and supports tagged on the row they fall in. Nothing is drawn on a time axis, so no label can sit on another.
 */
function Ladder({ d }: { d: Required<Pick<Levels, "series" | "supports" | "resistances" | "profile">> & Levels }) {
  const price = d.price ?? d.series[d.series.length - 1]?.close ?? 0;
  const levels = [...d.resistances.slice(0, 3).map((l) => ({ ...l, kind: "Resistance" as const })), ...d.supports.slice(0, 3).map((l) => ({ ...l, kind: "Support" as const }))];
  const bins = d.profile?.bins ?? [];
  const all = [price, ...levels.map((l) => l.price), ...bins.map((b) => b.price)];
  const lo = Math.min(...all), hi = Math.max(...all);
  const step = (hi - lo) / N || 1;
  const at = (v: number) => Math.min(N - 1, Math.floor((v - lo) / step));
  const vol = Array<number>(N).fill(0);
  for (const b of bins) vol[at(b.price)] = (vol[at(b.price)] ?? 0) + b.share;
  const maxVol = Math.max(...vol, 1e-9);
  const rows = Array.from({ length: N }, (_, k) => {
    const i = N - 1 - k, mid = lo + (i + 0.5) * step;
    return { i, lo: lo + i * step, hi: lo + (i + 1) * step, vol: vol[i] ?? 0, tags: levels.filter((l) => at(l.price) === i), now: at(price) === i, poc: !!d.profile && at(d.profile.poc) === i, value: !!d.profile && mid >= d.profile.value_low && mid <= d.profile.value_high };
  });
  return (
    <div role="img" aria-label={`${d.symbol} price ladder: support, resistance and volume by price`} className="text-xs">
      <div className="mb-1 grid grid-cols-[8.5rem_1fr] gap-2 text-ink-faint"><span>Price band</span><span>Volume traded in the band (last 120 days)</span></div>
      {rows.map((r) => (
        <div key={r.i} className={`grid grid-cols-[8.5rem_1fr] items-center gap-2 border-y border-transparent px-1 ${r.now ? "border-blue-300 bg-blue-50" : r.tags[0]?.kind === "Resistance" ? "bg-red-50" : r.tags[0]?.kind === "Support" ? "bg-emerald-50" : ""}`}>
          <span className="tabular-nums text-ink-soft">{money(r.lo)} – {money(r.hi)}</span>
          <div className="flex min-h-6 items-center gap-2">
            <span aria-hidden="true" className="relative h-3 w-[40%] shrink-0 rounded-sm bg-slate-100"><span className={`absolute inset-y-0 left-0 rounded-sm ${r.poc ? "bg-brand" : r.value ? "bg-slate-400" : "bg-slate-300"}`} style={{ width: `${(r.vol / maxVol) * 100}%` }} /></span>
            <span className="flex flex-wrap gap-1">
              {r.now ? <span className="rounded bg-blue-600 px-1.5 py-0.5 font-medium text-white">Price now {money(price)}</span> : null}
              {r.poc ? <span className="rounded bg-brand/10 px-1.5 py-0.5 font-medium text-brand">Most traded</span> : null}
              {r.tags.map((l) => <span key={l.price} className={`rounded px-1.5 py-0.5 font-medium ${l.kind === "Resistance" ? "bg-red-100 text-red-800" : "bg-emerald-100 text-emerald-800"}`}>{l.kind} {money(l.price)} · {l.distance_pct > 0 ? "+" : ""}{l.distance_pct.toFixed(1)}% · touched {l.touches}×</span>)}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

/** The same picture in words: where the price stands against the nearest level, the busiest price and the 52-week range. */
function Summary({ d }: { d: Required<Pick<Levels, "supports" | "resistances" | "profile">> & Levels }) {
  const price = d.price;
  const r = d.resistances[0], s = d.supports[0], p = d.profile;
  const away = (v: number) => (price ? `${Math.abs(((v - price) / price) * 100).toFixed(1)}% ${v >= price ? "above" : "below"}` : "");
  return (
    <ul className="space-y-2 text-sm">
      {r ? <li><span className="font-medium text-red-700">Next resistance {money(r.price)}</span>, {Math.abs(r.distance_pct).toFixed(1)}% above; the price turned back from it {r.touches} {r.touches === 1 ? "time" : "times"}. A close above it is a breakout.</li> : <li className="text-ink-soft">No resistance above: the price is at a high for this range.</li>}
      {s ? <li><span className="font-medium text-emerald-700">Next support {money(s.price)}</span>, {Math.abs(s.distance_pct).toFixed(1)}% below; held {s.touches} {s.touches === 1 ? "time" : "times"}. A close below it is a breakdown.</li> : <li className="text-ink-soft">No support below in range.</li>}
      {p ? <li><span className="font-medium">Most volume traded near {money(p.poc)}</span> ({away(p.poc)} the price); 70% of it between {money(p.value_low)} and {money(p.value_high)}. {price && price > p.value_high ? "The price is above that zone, which then acts as support." : price && price < p.value_low ? "The price is below that zone, which then acts as resistance." : "The price is inside that zone."}</li> : null}
      {d.high_52w && d.low_52w ? <li className="text-ink-soft">52-week range {money(d.low_52w)} to {money(d.high_52w)}{price ? `; the price is ${((1 - price / d.high_52w) * 100).toFixed(1)}% below the high` : ""}.</li> : null}
    </ul>
  );
}

/** What the picture means for this stock, from its own numbers: the state, what would confirm or cancel it, the next levels and the busiest price. Conditions, not forecasts. */
function Meaning({ d }: { d: Required<Pick<Levels, "supports" | "resistances" | "profile" | "status">> & Levels }) {
  const { status: st, price, profile: p } = d;
  const r = d.resistances[0], s = d.supports[0], r2 = d.resistances[1], s2 = d.supports[1];
  const vol = st.volume_ratio;
  const volNote = vol === null ? "" : vol >= 1.5 ? ` Volume is ${vol.toFixed(1)}× its norm, so the move has support.` : ` Volume is only ${vol.toFixed(1)}× its norm (1.5× is needed), so it is not yet confirmed.`;
  const lines: { head: string; body: string }[] = [];
  if (st.state.startsWith("Testing resistance") && r)
    lines.push({ head: "Right now", body: `${d.symbol} is pushing up against ${money(r.price)}, a price where it has stopped before. Buyers have to absorb the sellers there. A close above ${money(r.price * 1.005)} (0.5% beyond) would be a breakout;${volNote || " it should come on heavy volume."} A rejection would send it back toward ${s ? money(s.price) : "the support below"}.` });
  else if (st.state.startsWith("Testing support") && s)
    lines.push({ head: "Right now", body: `${d.symbol} is sitting on ${money(s.price)}, a price where buyers stepped in before. Holding it keeps the range intact; a close below ${money(s.price * 0.995)} (0.5% beyond) would be a breakdown.${volNote}` });
  else if (st.state.startsWith("Breakout") && st.level !== null)
    lines.push({ head: "Right now", body: `${d.symbol} closed above ${money(st.level)}, which now turns from resistance into support. Holding above it keeps the breakout valid; a close back below it would make it a failed breakout.${volNote}` });
  else if (st.state.startsWith("Breakdown") && st.level !== null)
    lines.push({ head: "Right now", body: `${d.symbol} closed below ${money(st.level)}, which now turns from support into resistance. A close back above it would make it a failed breakdown.${volNote}` });
  else
    lines.push({ head: "Right now", body: `${d.symbol} is between its levels and not testing either. ${r && s ? `It trades in a band from ${money(s.price)} to ${money(r.price)}; a close beyond either end is what would change the picture.` : ""}` });
  if (r) lines.push({ head: "If it goes up", body: `${money(r.price)} is the first hurdle${r2 ? `, then ${money(r2.price)} (${r2.distance_pct.toFixed(1)}% above)` : ", with no recorded resistance beyond it"}. Each is a place where sellers have appeared before, so the price may pause or turn there.` });
  if (s) lines.push({ head: "If it falls", body: `${money(s.price)} is the first floor${s2 ? `, then ${money(s2.price)} (${Math.abs(s2.distance_pct).toFixed(1)}% below)` : ""}. A level touched more often has held more often, but each test wears it down.` });
  if (p && price)
    lines.push({
      head: `"Most traded" ${money(p.poc)}`,
      body: p.poc < price
        ? `This is the price where the most shares changed hands in 120 days, so most holders bought near it. With the price ${(((price - p.poc) / price) * 100).toFixed(1)}% above, those holders are in profit; a fall back to it would likely meet buying (support) as holders defend their cost. It is a floor to watch, not a guarantee.`
        : `Most shares changed hands near this price in 120 days, so many holders bought here and are now at a loss. Rallies toward it tend to meet selling from holders wanting to get out even (resistance).`,
    });
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold text-ink-soft">What this means for {d.symbol}</h3>
      <ul className="space-y-2 text-sm">{lines.map((l) => <li key={l.head}><span className="font-medium">{l.head}: </span>{l.body}</li>)}</ul>
      <p className="mt-2 text-xs text-ink-faint">These describe where the price paused before. They are conditions to watch, not a forecast.</p>
    </div>
  );
}

function Histogram({ r }: { r: NonNullable<Levels["returns"]> }) {
  const max = Math.max(...r.bins.map((b) => b.count), 1);
  return (
    <div role="img" aria-label="Distribution of daily returns over the last year" className="flex h-20 items-end gap-0.5">
      {r.bins.map((b) => {
        const mid = (b.low + b.high) / 2;
        return <div key={b.low} className={`flex-1 ${mid >= 0 ? "bg-emerald-400" : "bg-red-400"}`} style={{ height: `${(b.count / max) * 100}%` }} title={`${b.low.toFixed(1)}% to ${b.high.toFixed(1)}%: ${b.count} days`} />;
      })}
    </div>
  );
}

/** Support, resistance, breakout status and the two histograms for one stock. */
export function LevelsPanel({ symbol }: { symbol: string }) {
  const q = useQuery({
    queryKey: ["market", "levels", symbol],
    queryFn: () => api.marketLevels(symbol),
    retry: false,
  });
  if (q.isLoading) return <div role="status" aria-label="Loading the levels"><Skeleton className="h-40 w-full" /></div>;
  if (q.isError) return q.error instanceof ApiError && q.error.status === 404 ? null : <Alert tone="error" title="Could not load the levels">Try again in a moment.</Alert>;
  const d = q.data;
  if (!d) return null;
  if (!d.enough_history || !d.series || !d.supports || !d.resistances || !d.status) return <Alert tone="info" title="Not enough history for levels">{d.symbol} has too few bars since its last split or bonus.</Alert>;
  const st = d.status;
  return (
    <Panel title="Support, resistance and volume by price">
      <div className="flex flex-wrap items-center gap-3 px-3 pt-2 text-sm">
        <StatusPill tone={STATE_TONE[st.state] ?? "neutral"}>{st.state}</StatusPill>
        {st.level !== null && <span className="text-ink-soft">level {money(st.level)}</span>}
        {st.volume_ratio !== null && <span className="text-ink-soft">volume {st.volume_ratio.toFixed(1)}× its norm</span>}
        {st.delivery_vs_avg !== null && <span className="text-ink-soft">delivery {st.delivery_vs_avg.toFixed(1)}× its norm</span>}
        <span className="text-xs text-ink-faint">as of {d.as_of}</span>
      </div>
      <div className="grid gap-6 p-3 lg:grid-cols-[3fr_2fr]">
        <Ladder d={{ ...d, series: d.series, supports: d.supports, resistances: d.resistances, profile: d.profile ?? null }} />
        <div className="space-y-5">
          <div><h3 className="mb-2 text-xs font-semibold text-ink-soft">In plain words</h3><Summary d={{ ...d, supports: d.supports, resistances: d.resistances, profile: d.profile ?? null }} /></div>
          <div>
            <h3 className="mb-1 text-xs font-semibold text-ink-soft">Daily returns, last year</h3>
            {d.returns ? <><Histogram r={d.returns} /><p className="mt-1 text-xs text-ink-soft">Last move {d.returns.last.toFixed(1)}%, bigger than {Math.round(d.returns.last_percentile)}% of days. Range {d.returns.worst.toFixed(1)}% to +{d.returns.best.toFixed(1)}%.</p></> : <p className="text-xs text-ink-faint">Not enough days</p>}
          </div>
          <Meaning d={{ ...d, supports: d.supports, resistances: d.resistances, profile: d.profile ?? null, status: st }} />
        </div>
      </div>
      <p className="border-t border-line px-3 py-2 text-xs text-ink-faint">Levels are swing highs and lows within 1.5% of each other (a broken resistance becomes support); a swing is only known 5 days after it. Up to three each side are tagged. Bar colour: the darkest bar is where most volume traded, grey bars are inside the zone holding 70% of the volume. A breakout is a close more than 0.5% beyond the nearest level; it is confirmed on volume at 1.5× its norm and, where known, delivery at 1.2×.</p>
    </Panel>
  );
}
