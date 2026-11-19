import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { Period } from "@/lib/fundamentals";
import { formatRatio, readingText, snapshot, versusYearAgo, type RatioRow } from "@/lib/ratios";
import { crore, summarize, type Tile, type Tone } from "@/lib/fundamentalsSummary";

const TEXT: Record<Tone, string> = { good: "text-emerald-700", bad: "text-red-700", neutral: "text-slate-600" };
const BORDER: Record<Tone, string> = { good: "border-emerald-500", bad: "border-red-500", neutral: "border-slate-300" };
const BANNER = {
  good: "border-emerald-200 bg-emerald-50 text-emerald-900",
  mixed: "border-amber-200 bg-amber-50 text-amber-900",
  weak: "border-red-200 bg-red-50 text-red-900",
  unknown: "border-line bg-slate-50 text-slate-700",
} as const;
const ARROW: Record<Tone, string> = { good: "▲", bad: "▼", neutral: "●" };

const CHIP = { good: "bg-emerald-100 text-emerald-800", ok: "bg-amber-100 text-amber-800", weak: "bg-red-100 text-red-800" } as const;

const fmtTile = (key: Tile["key"], n: number) => (key === "sales" || key === "profit" ? crore(n) : key === "margin" ? `${n.toFixed(1)}%` : `₹${n.toFixed(1)}`);

/** The last quarters as bars with the quarter under each: the latest in the tile's colour, the same quarter a year earlier in dark grey, the rest light; both of those carry their value. Losses hang below the zero line. */
function Bars({ tile }: { tile: Tile }) {
  const v = tile.series.map((s) => s.value);
  if (v.length < 2) return null;
  const W = 240, H = 104, top = 18, bot = 16, ph = H - top - bot;
  const hi = Math.max(0, ...v), lo = Math.min(0, ...v), span = hi - lo || 1;
  const y = (n: number) => top + ((hi - n) / span) * ph;
  const slot = W / v.length, bw = slot * 0.66;
  const color = tile.tone === "good" ? "fill-emerald-600" : tile.tone === "bad" ? "fill-red-600" : "fill-slate-600";
  const ago = v.length > 4 ? v.length - 5 : -1;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`${tile.title}, ${v.length} quarters from ${tile.series[0]?.label} to ${tile.series[v.length - 1]?.label}`}>
      <line x1={0} x2={W} y1={y(0)} y2={y(0)} className="stroke-slate-300" />
      {v.map((n, i) => {
        const x = i * slot + (slot - bw) / 2, shown = i === v.length - 1 || i === ago;
        return (
          <g key={i}>
            <rect x={x} y={Math.min(y(n), y(0))} width={bw} height={Math.max(1, Math.abs(y(n) - y(0)))} className={i === v.length - 1 ? color : i === ago ? "fill-slate-500" : "fill-slate-200"}><title>{`${tile.series[i]?.label}: ${fmtTile(tile.key, n)}`}</title></rect>
            {shown ? <text x={x + bw / 2} y={(n >= 0 ? y(n) : y(0)) - 3} textAnchor="middle" fontSize={9} fontWeight={600} className="fill-slate-700">{fmtTile(tile.key, n).replace(" cr", "")}</text> : null}
            <text x={x + bw / 2} y={H - 4} textAnchor="middle" fontSize={8} className={shown ? "fill-slate-700" : "fill-slate-400"}>{tile.series[i]?.label.replace(" 20", " ’")}</text>
          </g>
        );
      })}
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
      <div className="mt-2"><Bars tile={tile} /></div>
      <p className="mt-1 text-xs text-ink-soft">{tile.meaning}</p>
    </div>
  );
}

const ORDER = { weak: 0, ok: 1, good: 2 } as const;

/** How this quarter ranks against the same ratio in the company's earlier quarters, in words: "better than 5 of the last 8 quarters". Null without enough history or a good direction. */
export function rankAmongPast(r: RatioRow): { fraction: number; text: string } | null {
  const now = Number(r.value);
  const earlier = r.history.flatMap((h) => (h.value === null ? [] : [Number(h.value)]));
  if (earlier.length > 0 && earlier[earlier.length - 1] === now) earlier.pop(); // the history ends with this quarter
  if (!Number.isFinite(now) || r.better === null || earlier.length < 3) return null;
  const worse = earlier.filter((h) => (r.better === "high" ? h < now : h > now)).length;
  const n = earlier.length, cheap = r.group === "valuation";
  const [best, worst, mid] = cheap ? ["the cheapest", "the dearest", "cheaper than"] : ["the best", "the worst", "better than"];
  return { fraction: worse / n, text: worse === n ? `${best} of the last ${n} quarters` : worse === 0 ? `${worst} of the last ${n} quarters` : `${mid} ${worse} of the last ${n} quarters` };
}

/** One ratio: its value and reading, then a meter from worse (left, red) to better (right, green) with the dot where this quarter ranks against the company's own earlier quarters. */
function RankRow({ r }: { r: RatioRow }) {
  const rank = rankAmongPast(r);
  const vs = versusYearAgo(r);
  const cheap = r.group === "valuation";
  return (
    <li className="py-2.5" title={r.meaning}>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm">{r.label}</span>
        <span className="whitespace-nowrap">
          <span className="text-sm font-semibold tabular-nums">{formatRatio(r.unit, r.value)}</span>
          {r.reading ? <span className={`ml-1.5 rounded-full px-1.5 py-0.5 text-[11px] font-medium ${CHIP[r.reading]}`}>{readingText(r)}</span> : null}
        </span>
      </div>
      {rank ? (
        <div className="mt-1.5" role="img" aria-label={`${r.label}: ${formatRatio(r.unit, r.value)}, ${rank.text}`}>
          <div className="relative h-2 rounded-full bg-gradient-to-r from-red-300 via-amber-200 to-emerald-300">
            <span className="absolute top-1/2 h-4 w-4 -translate-y-1/2 rounded-full bg-slate-800 ring-2 ring-white" style={{ left: `calc(${Math.min(0.97, Math.max(0.03, rank.fraction)) * 100}% - 0.5rem)` }} />
          </div>
          <div className="mt-1 flex justify-between text-[11px] text-ink-soft">
            <span>{cheap ? "dearer" : "worse"}</span>
            <span className="text-ink">{rank.text}{vs ? `; ${vs.text} vs a year ago` : ""}</span>
            <span>{cheap ? "cheaper" : "better"}</span>
          </div>
        </div>
      ) : vs ? <p className="mt-0.5 text-[11px] text-ink-soft">{vs.text} vs a year ago</p> : null}
    </li>
  );
}

const usable = (x: RatioRow) => x.value !== null && x.reading !== null;
const byReading = (a: RatioRow, b: RatioRow) => ORDER[a.reading ?? "ok"] - ORDER[b.reading ?? "ok"];

/** Valuation and quality at a glance, then a scorecard of every rated ratio against its own range. Silent if ratios cannot be loaded. */
function RatioOverview({ instrumentId, basis }: { instrumentId: number; basis: string | undefined }) {
  const q = useQuery({ queryKey: ["ratios", instrumentId, basis], queryFn: () => api.ratios(instrumentId, basis), retry: false });
  const r = q.data;
  if (!r || !Array.isArray(r.ratios) || r.ratios.length === 0) return null;
  const quality = r.ratios.filter((x) => x.group !== "valuation" && usable(x)).sort(byReading).slice(0, 9);
  const val = r.ratios.filter((x) => x.group === "valuation" && usable(x)).sort(byReading);
  return (
    <div className="space-y-4">
      <div>
        <h3 className="mb-2 text-xs font-semibold text-ink-soft">Valuation and quality now{r.price ? ` · price ₹${Number(r.price.value).toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : ""}</h3>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {snapshot(r).map((x) => (
            <div key={x.key} className="rounded-lg border border-line bg-panel p-3" data-testid={`overview-${x.key}`} title={x.meaning}>
              <div className="text-xs text-ink-soft">{x.label}</div>
              <div className="text-lg font-semibold tabular-nums">{formatRatio(x.unit, x.value)}</div>
              {x.reading ? <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${CHIP[x.reading]}`}>{readingText(x)}</span> : null}
            </div>
          ))}
        </div>
      </div>
      {quality.length > 0 || val.length > 0 ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="rounded-lg border border-line bg-panel p-4" aria-label="Quality and growth scorecard">
            <h3 className="text-sm font-semibold">Quality and growth</h3>
            <p className="mb-1 text-xs text-ink-soft">Weakest first. The dot shows where this quarter ranks against the company&apos;s own earlier quarters: left is its worst, right its best.</p>
            <ul className="divide-y divide-line/60">{quality.map((x) => <RankRow key={x.key} r={x} />)}</ul>
            {quality.length === 0 ? <p className="text-sm text-ink-faint">Nothing is rated yet.</p> : null}
          </section>
          <section className="rounded-lg border border-line bg-panel p-4" aria-label="Valuation scorecard">
            <h3 className="text-sm font-semibold">Price against its own past</h3>
            <p className="mb-1 text-xs text-ink-soft">The dot shows whether the price is dear or cheap against the company&apos;s own earlier quarters. It says nothing about other companies.</p>
            <ul className="divide-y divide-line/60">{val.map((x) => <RankRow key={x.key} r={x} />)}</ul>
            {val.length === 0 ? <p className="text-sm text-ink-faint">Not enough history to compare.</p> : null}
          </section>
        </div>
      ) : null}
    </div>
  );
}

export function SummaryView({ periods, instrumentId, basis }: { periods: Period[]; instrumentId?: number; basis?: string }) {
  const s = summarize(periods);
  return (
    <div className="space-y-4" data-testid="fundamentals-summary">
      <div className={`rounded-lg border p-4 text-base font-medium ${BANNER[s.verdict]}`} role="status">{s.headline}</div>
      {instrumentId !== undefined ? <RatioOverview instrumentId={instrumentId} basis={basis} /> : null}
      {s.tiles.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {s.tiles.map((t) => <TileCard key={t.key} tile={t} />)}
        </div>
      ) : null}
      {s.checks.length > 0 ? (
        <ul className="grid gap-3 md:grid-cols-3" aria-label="Health checks">
          {s.checks.map((c) => (
            <li key={c.text} className={`rounded-lg border-l-4 bg-panel p-3 text-sm shadow-card ${BORDER[c.tone]}`}>
              <span className={`mr-1 font-semibold ${TEXT[c.tone]}`} aria-hidden="true">{c.tone === "good" ? "✓" : c.tone === "bad" ? "!" : "•"}</span>{c.text}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="text-xs leading-relaxed text-ink-soft">
        Each quarter is compared with the same quarter a year earlier, because many businesses are seasonal; in the bars, dark grey is that year-ago quarter and a bar below the line is a loss. This is a reading of the filed numbers, not advice. Switch to “All figures” for the full statements.
      </p>
    </div>
  );
}
