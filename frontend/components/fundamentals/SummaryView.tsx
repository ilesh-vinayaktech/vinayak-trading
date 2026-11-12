import type { Period } from "@/lib/fundamentals";
import { summarize, type Tile, type Tone } from "@/lib/fundamentalsSummary";

const TEXT: Record<Tone, string> = { good: "text-emerald-700", bad: "text-red-700", neutral: "text-slate-600" };
const DOT: Record<Tone, string> = { good: "bg-emerald-500", bad: "bg-red-500", neutral: "bg-slate-400" };
const BANNER = {
  good: "border-emerald-200 bg-emerald-50 text-emerald-900",
  mixed: "border-amber-200 bg-amber-50 text-amber-900",
  weak: "border-red-200 bg-red-50 text-red-900",
  unknown: "border-line bg-slate-50 text-slate-700",
} as const;
const ARROW: Record<Tone, string> = { good: "▲", bad: "▼", neutral: "●" };

/** The last quarters as a small line, oldest to newest; the final point is marked. */
function Sparkline({ tile }: { tile: Tile }) {
  const v = tile.series.map((s) => s.value);
  if (v.length < 2) return null;
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
  const x = (i: number) => (i / (v.length - 1)) * 100;
  const y = (n: number) => 22 - ((n - lo) / span) * 20;
  const last = v[v.length - 1] as number;
  const color = tile.tone === "good" ? "#047857" : tile.tone === "bad" ? "#b91c1c" : "#475569";
  const first = tile.series[0]?.label, end = tile.series[tile.series.length - 1]?.label;
  return (
    <svg viewBox="0 0 100 24" className="h-10 w-full" role="img" aria-label={`${tile.title}, ${v.length} quarters from ${first} to ${end}`} preserveAspectRatio="none">
      <polyline points={v.map((n, i) => `${x(i)},${y(n)}`).join(" ")} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
      <circle cx={100} cy={y(last)} r="2" fill={color} />
    </svg>
  );
}

function TileCard({ tile }: { tile: Tile }) {
  return (
    <div className="rounded-lg border border-line bg-panel p-4" data-testid={`tile-${tile.key}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">{tile.title}</h3>
        <span className="text-xs text-ink-soft">{tile.quarter}</span>
      </div>
      <div className="mt-1 text-2xl font-semibold tabular-nums tracking-tight">{tile.latest}</div>
      <p className={`mt-1 text-sm ${TEXT[tile.tone]}`}>
        <span aria-hidden="true">{ARROW[tile.tone]} </span>
        {tile.vsYear}
      </p>
      {tile.momentum ? <p className="text-xs text-ink-soft">{tile.momentum.charAt(0).toUpperCase() + tile.momentum.slice(1)}.</p> : null}
      <div className="mt-2"><Sparkline tile={tile} /></div>
      <p className="mt-1 text-xs text-ink-soft">{tile.meaning}</p>
    </div>
  );
}

export function SummaryView({ periods }: { periods: Period[] }) {
  const s = summarize(periods);
  return (
    <div className="space-y-4" data-testid="fundamentals-summary">
      <div className={`rounded-lg border p-4 text-base font-medium ${BANNER[s.verdict]}`} role="status">{s.headline}</div>
      {s.tiles.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {s.tiles.map((t) => <TileCard key={t.key} tile={t} />)}
        </div>
      ) : null}
      {s.checks.length > 0 ? (
        <ul className="space-y-2 rounded-lg border border-line bg-panel p-4 text-sm" aria-label="Health checks">
          {s.checks.map((c) => (
            <li key={c.text} className="flex gap-2">
              <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[c.tone]}`} aria-hidden="true" />
              <span>{c.text}</span>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="text-xs leading-relaxed text-ink-soft">
        Each quarter is compared with the same quarter a year earlier, because many businesses are seasonal. This is a reading of the filed numbers, not advice. Switch to “All figures” for the full statements.
      </p>
    </div>
  );
}
