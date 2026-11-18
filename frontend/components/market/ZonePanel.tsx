"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { ZoneDrivers } from "@/components/market/ZoneDrivers";
import { zoneEvents } from "@/lib/zoneEvents";
import { api } from "@/lib/api/client";
import type { MarketZone, ZonePerformance } from "@/lib/schemas";

// the four zones (cutoffs 30, 50, 70): fear is where buyers find bargains (green), greed is where the risk is (red)
const ZONES = [
  { from: 0, to: 30, w: 30, cls: "bg-emerald-600", fill: "#059669", label: "Extreme fear" },
  { from: 30, to: 50, w: 20, cls: "bg-lime-500", fill: "#84cc16", label: "Fear" },
  { from: 50, to: 70, w: 20, cls: "bg-orange-400", fill: "#fb923c", label: "Greed" },
  { from: 70, to: 100, w: 30, cls: "bg-red-500", fill: "#ef4444", label: "Extreme greed" },
] as const;
const zoneOf = (n: number) => ZONES.find((z) => n < z.to) ?? ZONES[3];
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
      <div className="mt-1 flex justify-between text-[11px] text-ink-faint"><span>Extreme fear</span><span>Extreme greed</span></div>
    </div>
  );
}

/** Nifty 50 above, the score below it over the four zone bands: labelled bands, year or month ticks, the range shown, and a hover read-out of any day. */
function History({ points, nifty }: { points: MarketZone["history"]; nifty: ZonePerformance["nifty"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const [range, setRange] = useState<number>(756); // trading days shown (3 years to start); 0 is all of them
  const scored = points.filter((p) => p.fear_greed !== null);
  const ys = range > 0 ? scored.slice(-range) : scored;
  if (ys.length < 2) return null;
  const W = 560, H = 250, L = 4, R = 66, B = 18, T1 = 6, B1 = 104, T2 = 116; // Nifty 50 above, the score below it
  const Hs = H - B - T2;
  const x = (i: number) => L + (i / (ys.length - 1)) * (W - L - R);
  const y = (v: number) => T2 + (1 - v / 100) * Hs;
  const vals = ys.map((p) => p.fear_greed ?? 0);
  const line = vals.map((v, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const closes = new Map(nifty.map((n) => [n.day, n.close]));
  const nv = ys.map((p) => closes.get(p.day) ?? null);
  const known = nv.filter((v): v is number => v !== null);
  const nLo = Math.min(...known), nHi = Math.max(...known);
  const ny = (v: number) => T1 + (1 - (v - nLo) / (nHi - nLo || 1)) * (B1 - T1);
  const nPath = known.length > 1 ? nv.flatMap((v, i) => (v === null ? [] : [`${i === 0 || nv[i - 1] === null ? "M" : "L"}${x(i).toFixed(1)},${ny(v).toFixed(1)}`])).join(" ") : "";
  const events = zoneEvents(vals);
  const last = ys.length - 1, shown = hover ?? last;
  const lo = Math.min(...vals), hi = Math.max(...vals), avg = vals.reduce((s, v) => s + v, 0) / vals.length;
  const years = ys.length > 600; // a long stretch is labelled by year, a short one by month
  const months = ys.flatMap((p, i) => {
    const prev = ys[i - 1]?.day;
    if (i === 0 || prev === undefined) return [];
    if (years) return p.day.slice(0, 4) !== prev.slice(0, 4) ? [{ i, m: p.day.slice(0, 4) }] : [];
    return p.day.slice(0, 7) !== prev.slice(0, 7) ? [{ i, m: new Date(p.day).toLocaleString("en-IN", { month: "short" }) }] : [];
  });
  const d = new Date(ys[shown]?.day ?? "").toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2 text-xs text-ink-soft">
        <span>{hover === null ? "Hover for any day" : <><b className="tabular-nums text-ink">{Math.round(vals[shown] ?? 0)}</b> {zoneOf(vals[shown] ?? 0).label}{nv[shown] != null ? ` · Nifty 50 ${nv[shown]?.toLocaleString("en-IN", { maximumFractionDigits: 0 })}` : ""} · {d}</>}</span>
        <span className="tabular-nums"><span className="mr-3 inline-flex gap-1" role="group" aria-label="Chart range">{([["1Y", 252], ["3Y", 756], ["All", 0]] as const).map(([l, n]) => <button key={l} type="button" aria-pressed={range === n} onClick={() => setRange(n)} className={`rounded px-1.5 py-0.5 ${range === n ? "bg-slate-200 font-medium text-ink" : "text-ink-faint hover:text-ink"}`}>{l}</button>)}</span><span className="mr-3"><span className="mr-1 inline-block h-0.5 w-4 bg-ink align-middle" />Score <span className="ml-2 mr-1 inline-block h-0.5 w-4 bg-orange-600 align-middle" />Nifty 50<span className="ml-2 mr-1 inline-block h-2 w-2 rounded-full bg-red-600 align-middle" />Left extreme greed<span className="ml-2 mr-1 inline-block h-2 w-2 rounded-full bg-green-600 align-middle" />Left extreme fear</span>Low {Math.round(lo)} · average {Math.round(avg)} · high {Math.round(hi)}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label={`Fear and greed over the last ${ys.length} trading days, now ${Math.round(vals[last] ?? 0)}`}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHover(Math.max(0, Math.min(last, Math.round((((e.clientX - r.left) / r.width) * W - L) / (W - L - R) * last)))); }}>
        {ZONES.map((z) => (
          <g key={z.label}>
            <rect x={L} y={y(z.to)} width={W - L - R} height={y(z.from) - y(z.to)} fill={z.fill} opacity={0.16} />
            <text x={W - R + 4} y={(y(z.from) + y(z.to)) / 2 + 3} fontSize={9} className="fill-slate-500">{z.label.replace("Extreme ", "Ext. ")}</text>
          </g>
        ))}
        {[30, 50, 70].map((v) => <line key={v} x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke="#94a3b8" strokeWidth={0.5} strokeDasharray="3 3" />)}
        {months.map((m) => <text key={m.i} x={x(m.i)} y={H - 4} fontSize={9} textAnchor="middle" className="fill-slate-500">{m.m}</text>)}
        {nPath ? <><text x={W - R + 4} y={T1 + 10} fontSize={9} className="fill-slate-500">Nifty 50</text><text x={W - R + 4} y={(T2 + T1 + B1) / 2 - 2} fontSize={9} className="fill-slate-500">Score</text><path d={nPath} fill="none" stroke="#ea580c" strokeWidth={1.4} /></> : null}
        <path d={line} fill="none" stroke="#0f172a" strokeWidth={1.6} strokeLinejoin="round" />
        <line x1={x(shown)} x2={x(shown)} y1={T1} y2={H - B} stroke="#0f172a" strokeWidth={0.6} opacity={hover === null ? 0 : 0.5} />
        {events.map((e) => {
          const top = e.kind === "top", c = nv[e.index], colour = top ? "#dc2626" : "#16a34a";
          const cy = c == null ? T1 + 6 : ny(c) + (top ? -8 : 8);
          return (
            <g key={e.index}>
              <title>{`${top ? "Score left extreme greed" : "Score left extreme fear"} · ${ys[e.index]?.day}`}</title>
              <line x1={x(e.index)} x2={x(e.index)} y1={cy} y2={y(vals[e.index] ?? 0)} stroke={colour} strokeWidth={0.7} strokeDasharray="2 2" opacity={0.7} />
              <circle cx={x(e.index)} cy={cy} r={3.5} fill={colour} />
            </g>
          );
        })}
        <circle cx={x(shown)} cy={y(vals[shown] ?? 0)} r={3.5} fill={zoneOf(vals[shown] ?? 0).fill} stroke="#0f172a" strokeWidth={1.2} />
      </svg>
    </div>
  );
}

/** Nifty 50's average return after each zone, over every stored day, against all days. */
function Performance({ rows }: { rows: ZonePerformance["zones"] }) {
  if (rows.length === 0) return null;
  const pct = (v: number | null) => (v === null ? "–" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`);
  const horizons = rows[0]?.forward.map((f) => f.horizon) ?? [];
  return (
    <div>
      <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-soft">Nifty 50 after each zone</h3>
      <table className="w-full text-xs">
        <thead><tr className="text-ink-faint"><th className="py-1 text-left font-normal">Zone</th><th className="text-right font-normal">Days</th>{horizons.map((h) => <th key={h} className="text-right font-normal">{h} days later</th>)}</tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.zone} className={`border-t border-slate-100 ${r.zone === "All days" ? "text-ink-soft" : ""}`}>
              <td className="py-1">{r.zone}</td><td className="text-right tabular-nums">{r.days.toLocaleString("en-IN")}</td>
              {r.forward.map((f) => <td key={f.horizon} className="text-right tabular-nums">{pct(f.avg_pct)} <span className="text-ink-faint">({f.up_pct === null ? "–" : Math.round(f.up_pct)}% up)</span></td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-1 text-xs text-ink-faint">Average return, and how often it was positive. Days overlap, so read it as a tendency, not proof.</p>
    </div>
  );
}

/** How fearful or greedy the whole market is, what kind of market it is, the breadth behind it, and which signals pull it. */
export function ZonePanel() {
  const q = useQuery({ queryKey: ["market", "zone"], queryFn: api.marketZone, refetchInterval: 60_000 });
  const perf = useQuery({ queryKey: ["market", "zone", "performance"], queryFn: api.zonePerformance, staleTime: 5 * 60_000 });
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
          <History points={history} nifty={perf.data?.nifty ?? []} />
          <p className="text-xs text-ink-faint">Every day of the score since 2016 (pick 1Y, 3Y or All). Each signal is read against its own previous 45 days, so this says how unusual today is, not whether to buy. Green is fear, red is greed. A red dot marks the day the score came back out of extreme greed, a green dot out of extreme fear. These are not calls that the market has topped or bottomed.</p>
          {perf.data ? <Performance rows={perf.data.zones} /> : null}
        </div>
        <div className="space-y-4">
          <div>
            <div className="mb-1 flex justify-between text-xs text-ink-soft"><span>{l.advancers.toLocaleString("en-IN")} up</span><span>{l.decliners.toLocaleString("en-IN")} down</span></div>
            <div className="flex h-2 overflow-hidden rounded-full bg-red-400" role="img" aria-label={`${l.advancers} stocks up, ${l.decliners} down`}><div className="bg-emerald-500" style={{ width: `${upShare}%` }} /></div>
            <p className="mt-1 text-xs text-ink-faint">{l.live ? "Today so far. " : "On the day. "}The score is compared with the last 45 days, so a down day after a strong run can still read greedy.</p>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <dt className="text-ink-soft">Above 50-day average</dt><dd className="text-right tabular-nums">{l.pct_above_50 === null ? "–" : `${l.pct_above_50}%`}</dd>
              <dt className="text-ink-soft">Above 200-day average</dt><dd className="text-right tabular-nums">{l.pct_above_200 === null ? "–" : `${l.pct_above_200}%`}</dd>
              <dt className="text-ink-soft">New 52-week highs / lows</dt><dd className="text-right tabular-nums">{l.highs} / {l.lows}</dd>
            </dl>
          </div>
          <ZoneDrivers drivers={drivers} />
        </div>
      </div>
    </Panel>
  );
}
