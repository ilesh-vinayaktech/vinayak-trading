"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import type { MarketZone } from "@/lib/schemas";

// the five zones, as widths of the 0 to 100 scale; the colours run from fear (red) to greed (green)
const ZONES = [
  { w: 25, cls: "bg-red-500", label: "Extreme fear" },
  { w: 20, cls: "bg-orange-400", label: "Fear" },
  { w: 10, cls: "bg-slate-300", label: "Neutral" },
  { w: 20, cls: "bg-lime-500", label: "Greed" },
  { w: 25, cls: "bg-emerald-600", label: "Extreme greed" },
] as const;
const TREND_TONE = { BULL: "good", BEAR: "bad", SIDEWAYS: "warn", UNKNOWN: "neutral" } as const;
const VOL_TONE = { CALM: "good", NORMAL: "neutral", STRESSED: "bad", UNKNOWN: "neutral" } as const;
const TREND_TEXT: Record<string, string> = { BULL: "Bull market", BEAR: "Bear market", SIDEWAYS: "Sideways market" };
const VOL_TEXT: Record<string, string> = { STRESSED: "Stressed volatility", CALM: "Calm volatility", NORMAL: "Normal volatility" };

function ZoneBar({ score }: { score: number }) {
  return (
    <div className="relative pt-4" role="img" aria-label={`Fear and greed ${Math.round(score)} out of 100`}>
      <div className="flex h-3 overflow-hidden rounded-full">
        {ZONES.map((z) => <div key={z.label} className={z.cls} style={{ width: `${z.w}%` }} title={z.label} />)}
      </div>
      <div className="absolute top-0 -translate-x-1/2 text-xs font-semibold" style={{ left: `${Math.min(100, Math.max(0, score))}%` }}>▼</div>
      <div className="mt-1 flex justify-between text-[11px] text-ink-faint"><span>Extreme fear</span><span>Neutral</span><span>Extreme greed</span></div>
    </div>
  );
}

/** A year of the score as a line over the five zone bands. */
function History({ points }: { points: MarketZone["history"] }) {
  const ys = points.filter((p) => p.fear_greed !== null);
  if (ys.length < 2) return null;
  const W = 520, H = 70;
  const x = (i: number) => (i / (ys.length - 1)) * W;
  const y = (v: number) => H - (v / 100) * H;
  const line = ys.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.fear_greed ?? 0).toFixed(1)}`).join(" ");
  let at = 0;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-20 w-full" role="img" aria-label={`Fear and greed over the last ${ys.length} trading days`} preserveAspectRatio="none">
      {ZONES.map((z) => {
        const top = y(at + z.w);
        const r = <rect key={z.label} x={0} y={top} width={W} height={(z.w / 100) * H} className={z.cls} opacity={0.14} />;
        at += z.w;
        return r;
      })}
      <path d={line} fill="none" stroke="currentColor" strokeWidth={1.6} className="text-ink" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

const barColour = (n: number) => (n >= 55 ? "bg-emerald-500" : n >= 40 ? "bg-slate-400" : "bg-red-500");

/** How fearful or greedy the whole market is, what kind of market it is, the breadth behind it, and which signals pull it. */
export function ZonePanel() {
  const q = useQuery({ queryKey: ["market", "zone"], queryFn: api.marketZone, refetchInterval: 60_000 });
  if (q.isError) return <Alert tone="error" title="Could not load the market zone">Try again in a moment.</Alert>;
  if (q.isLoading || !q.data) return <div role="status" aria-label="Loading the market zone"><Skeleton className="h-48 w-full" /></div>;
  const { latest: l, drivers, history } = q.data;
  if (!l) return <Alert tone="info" title="Market zone not built yet">It is built each evening after the market closes.</Alert>;
  const upShare = l.advancers + l.decliners > 0 ? (100 * l.advancers) / (l.advancers + l.decliners) : 50;
  return (
    <Panel title="Market zone">
      <div className="grid gap-6 px-6 py-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="space-y-4">
          <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
            <div>
              <div className="text-4xl font-semibold tabular-nums">{l.fear_greed === null ? "–" : Math.round(l.fear_greed)}</div>
              <div className="text-sm text-ink-soft">{l.label ?? "Not enough history yet"}</div>
            </div>
            <div className="flex flex-wrap gap-2 pb-1">
              <StatusPill tone={TREND_TONE[l.trend as keyof typeof TREND_TONE] ?? "neutral"}>{TREND_TEXT[l.trend ?? ""] ?? "Trend unknown"}</StatusPill>
              <StatusPill tone={VOL_TONE[l.volatility as keyof typeof VOL_TONE] ?? "neutral"}>{VOL_TEXT[l.volatility ?? ""] ?? "Volatility unknown"}</StatusPill>
            </div>
          </div>
          {l.fear_greed !== null ? <ZoneBar score={l.fear_greed} /> : null}
          {l.age_days > 3 ? <Alert tone="warn" title="The zone is out of date">Last built for {l.day}, {l.age_days} days ago.</Alert> : l.live ? <p className="text-xs text-ink-faint"><span className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-500 align-middle" aria-hidden="true" />Live{l.as_of ? `, worked out at ${new Date(l.as_of).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" })} IST` : ""} from today&apos;s prices. {l.universe.toLocaleString("en-IN")} liquid stocks.</p> : <p className="text-xs text-ink-faint">As of the close on {l.day}. {l.universe.toLocaleString("en-IN")} liquid stocks.</p>}
          <History points={history} />
          <p className="text-xs text-ink-faint">The last year of the score. Each signal is read against the market&apos;s own three-year history, so this says how unusual today is, not whether to buy.</p>
        </div>
        <div className="space-y-4">
          <div>
            <div className="mb-1 flex justify-between text-xs text-ink-soft"><span>{l.advancers.toLocaleString("en-IN")} up</span><span>{l.decliners.toLocaleString("en-IN")} down</span></div>
            <div className="flex h-2 overflow-hidden rounded-full bg-red-400" role="img" aria-label={`${l.advancers} stocks up, ${l.decliners} down`}><div className="bg-emerald-500" style={{ width: `${upShare}%` }} /></div>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <dt className="text-ink-soft">Above 50-day average</dt><dd className="text-right tabular-nums">{l.pct_above_50 === null ? "–" : `${l.pct_above_50}%`}</dd>
              <dt className="text-ink-soft">Above 200-day average</dt><dd className="text-right tabular-nums">{l.pct_above_200 === null ? "–" : `${l.pct_above_200}%`}</dd>
              <dt className="text-ink-soft">New 52-week highs / lows</dt><dd className="text-right tabular-nums">{l.highs} / {l.lows}</dd>
            </dl>
          </div>
          {drivers.length > 0 ? (
            <div>
              <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-soft">What is moving it</h3>
              <ul className="space-y-1.5">
                {drivers.map((d) => (
                  <li key={d.key} className="text-xs">
                    <div className="flex justify-between"><span>{d.name}</span><span className="tabular-nums text-ink-soft">{Math.round(d.score)}</span></div>
                    <div className="h-1.5 rounded-full bg-slate-100"><div className={`h-1.5 rounded-full ${barColour(d.score)}`} style={{ width: `${d.score}%` }} /></div>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      </div>
    </Panel>
  );
}
