"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import type { Forecast } from "@/lib/schemas";

const LEAN = 0.03; // within 3 points of 50% there is no lean worth stating
const FLAT = 0.1; // a move under 0.1% is not a move
const pct = (p: number) => `${Math.round(p * 100)}%`;
const signed = (v: number) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`;
type Call = "up" | "down" | "none";
const call = (p: number | null): Call => (p === null ? "none" : p >= 0.5 + LEAN ? "up" : p <= 0.5 - LEAN ? "down" : "none");
const CALL_TEXT = { up: "Expects a rise", down: "Expects a fall", none: "No clear lean" } as const;
const WHEN: Record<number, string> = { 1: "Tomorrow", 5: "Next 5 days" };
const todayIST = () => new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });

type Verdict = "right" | "wrong" | "flat" | "none";
/** Is the live move going the way the call said? */
function verdict(expected: "up" | "down" | "none", change: number | undefined | null): Verdict {
  if (expected === "none" || change === undefined || change === null) return "none";
  if (Math.abs(change) < FLAT) return "flat";
  return (expected === "up") === change > 0 ? "right" : "wrong";
}
const VERDICT_TEXT: Record<Verdict, string> = { right: "Going as expected", wrong: "Going against it", flat: "Flat so far", none: "–" };
const VERDICT_TONE = { right: "good", wrong: "bad", flat: "neutral", none: "neutral" } as const;

function why(ev: Forecast["market"][number]["evidence"], labels: Record<string, string>) {
  return ev.map((e) => `${labels[e.feature] ?? e.feature} points ${e.effect >= 0 ? "up" : "down"}`).join("; ");
}

/** Now against the call: what the model expected for today and what the live prices are doing. */
function Today({ d }: { d: Forecast }) {
  const live = d.today ?? null;
  const m1 = d.market.find((m) => m.horizon_days === 1);
  const forToday = d.as_of !== null && d.as_of < todayIST(); // made after an earlier close, so its "tomorrow" is the session being traded now
  if (!m1) return null;
  const expected = call(m1.p_up);
  const change = live?.market_change_pct ?? null;
  const v = forToday ? verdict(expected, change) : "none";
  const mine = d.record.filter((r) => !d.product || r.product === d.product); // only the record of the forecast being shown
  const usual = mine.find((r) => r.subject === "Market" && r.horizon_days === 1 && !r.live);
  const rows = d.sectors.map((s) => ({ s, exp: call(s.p_1d), chg: live?.sectors[s.name] ?? null }));
  const judged = rows.filter((r) => forToday && verdict(r.exp, r.chg) !== "none" && verdict(r.exp, r.chg) !== "flat");
  const right = judged.filter((r) => verdict(r.exp, r.chg) === "right").length;
  return (
    <div className="px-3 pb-3">
      <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-soft">{forToday ? "Today: what we expected and what is happening" : "Next session"}</h3>
      <div className="rounded border border-line p-3">
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span className="font-medium">Nifty 500</span>
          {forToday && change !== null ? <StatusPill tone={VERDICT_TONE[v]}>{VERDICT_TEXT[v]}</StatusPill> : null}
        </div>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <div>
            <div className="text-xs text-ink-soft">What we expected {forToday ? "for today" : "for the next session"}</div>
            <div className="text-lg font-semibold" aria-label={`${pct(m1.p_up)} chance up`}>{CALL_TEXT[expected]} <span className="text-sm font-normal text-ink-soft">({pct(m1.p_up)} chance of a rise)</span></div>
            {m1.evidence.length > 0 && <p className="mt-1 text-xs text-ink-soft">{why(m1.evidence, d.labels ?? {})}</p>}
            {d.overnight?.sp !== null && d.overnight?.sp !== undefined && (
              <p className="mt-1 text-xs text-ink-soft">
                {Math.abs(d.overnight.sp) < 0.5
                  ? `The US S&P 500 moved only ${move(d.overnight.sp)} overnight. On days like that the model has shown no skill over the market's usual tendency, so read this call as little more than that.`
                  : `The US S&P 500 moved ${move(d.overnight.sp)} overnight. That is the kind of day this model has had some skill on in past data, but it is still a mild lean.`}
              </p>
            )}
            {usual && <p className="mt-1 text-xs text-ink-faint">For reference, the market has closed higher on {pct(usual.base_rate)} of days.{!usual.beats_guessing ? " The call has not yet beaten that." : ""}</p>}
          </div>
          <div>
            <div className="text-xs text-ink-soft">What is happening</div>
            {forToday && change !== null ? (
              <div className={`text-lg font-semibold tabular-nums ${change >= 0 ? "text-emerald-700" : "text-red-600"}`}>{signed(change)} <span className="text-sm font-normal text-ink-soft">since yesterday&apos;s close{live?.as_of ? `, at ${new Date(live.as_of).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" })} IST` : ""}</span></div>
            ) : (
              <div className="text-sm text-ink-soft">{forToday ? "No live prices right now (the market is closed or the feed is off)." : "The session has not started."}</div>
            )}
          </div>
        </div>
      </div>
      {rows.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <p className="mb-1 text-xs text-ink-soft">
            Sectors{judged.length > 0 ? `: ${right} of ${judged.length} that had a lean are moving the way we expected` : ""}.
          </p>
          <table className="w-full min-w-[420px] text-left text-sm">
            <caption className="sr-only">What was expected of each sector today and what it is doing, most bullish first</caption>
            <thead className="border-y border-line text-xs text-ink-soft"><tr><th scope="col" className="px-2 py-1.5">Sector</th><th scope="col" className="px-2">We expected</th><th scope="col" className="px-2 text-right">Today so far</th><th scope="col" className="px-2">&nbsp;</th></tr></thead>
            <tbody>
              {rows.map(({ s, exp, chg }) => {
                const sv = forToday ? verdict(exp, chg) : "none";
                return (
                  <tr key={s.name} className="border-b border-line last:border-0">
                    <th scope="row" className="whitespace-nowrap px-2 py-1.5 font-medium">{s.name}</th>
                    <td className="px-2 text-xs text-ink-soft">{s.p_1d === null ? "–" : `${CALL_TEXT[exp]} (${pct(s.p_1d)})`}</td>
                    <td className="px-2 text-right tabular-nums">{forToday && chg !== null ? signed(chg) : "–"}</td>
                    <td className="px-2 text-xs">{sv === "right" ? <span className="text-emerald-700">✓ as expected</span> : sv === "wrong" ? <span className="text-red-600">✗ against</span> : sv === "flat" ? <span className="text-ink-faint">flat</span> : null}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const move = (v: number | null | undefined) => (v === null || v === undefined ? "not in yet" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`);
const moveTone = (v: number | null | undefined, inverse = false) => (v === null || v === undefined ? "" : (v >= 0) !== inverse ? "text-emerald-700" : "text-red-600");

/** Before the open: what the US did overnight and what GIFT Nifty indicated at 08:45, and how often the day went that way before. */
function Overnight({ d }: { d: Forecast }) {
  const o = d.overnight;
  if (!o) return null;
  const rows = o.gift_history.filter((r) => r.days > 0);
  return (
    <div className="px-3 pb-3">
      <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-soft">Overnight, before the open</h3>
      <div className="grid gap-2 rounded border border-line p-3 text-sm sm:grid-cols-4">
        <div><div className="text-xs text-ink-soft">GIFT Nifty at 08:45 IST</div><div className={`text-lg font-semibold tabular-nums ${moveTone(o.gift_gap_pct)}`}>{move(o.gift_gap_pct)}</div><div className="text-xs text-ink-faint">against yesterday&apos;s close</div></div>
        <div><div className="text-xs text-ink-soft">US S&amp;P 500</div><div className={`text-lg font-semibold tabular-nums ${moveTone(o.sp)}`}>{move(o.sp)}</div></div>
        <div><div className="text-xs text-ink-soft">US Nasdaq</div><div className={`text-lg font-semibold tabular-nums ${moveTone(o.nq)}`}>{move(o.nq)}</div></div>
        <div><div className="text-xs text-ink-soft">US volatility (VIX)</div><div className={`text-lg font-semibold tabular-nums ${moveTone(o.vix, true)}`}>{move(o.vix)}</div><div className="text-xs text-ink-faint">a rise is nervous</div></div>
      </div>
      {rows.length > 0 && (
        <div className="mt-2 overflow-x-auto">
          <p className="mb-1 text-xs text-ink-soft">On mornings when GIFT Nifty indicated this, the Nifty 500 went on to close:</p>
          <table className="w-full min-w-[360px] text-left text-sm">
            <caption className="sr-only">How the Nifty 500 closed after each size of GIFT Nifty indication</caption>
            <thead className="border-y border-line text-xs text-ink-soft"><tr><th scope="col" className="px-2 py-1.5">GIFT Nifty indicated</th><th scope="col" className="px-2 text-right">Mornings</th><th scope="col" className="px-2 text-right">Closed higher</th><th scope="col" className="px-2 text-right">Average move</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.label} className="border-b border-line last:border-0">
                  <th scope="row" className="whitespace-nowrap px-2 py-1.5 font-medium">{r.label}</th>
                  <td className="px-2 text-right tabular-nums">{r.days}</td>
                  <td className="px-2 text-right tabular-nums">{r.up_pct === null ? "–" : `${Math.round(r.up_pct)}%`}</td>
                  <td className="px-2 text-right tabular-nums">{r.avg_pct === null ? "–" : move(r.avg_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-xs text-ink-faint">Mornings since GIFT Nifty readings began to be kept (January 2024). The call below is refreshed each morning with the US close; the GIFT reading is shown beside it, not mixed into it.</p>
        </div>
      )}
    </div>
  );
}

/** How big a day's range is likely to be: a research forecast under forward validation, shown beside the simple 5-session average, never as a trading signal. */
function ExpectedRange() {
  const q = useQuery({ queryKey: ["market", "range-forecast"], queryFn: api.rangeForecast, refetchInterval: 5 * 60_000 });
  if (q.isError || !q.data) return null;
  const d = q.data, l = d.latest;
  const when = (iso: string) => new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata" });
  const day = (iso: string) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  const pct = (v: number) => `${v.toFixed(2)}%`;
  return (
    <div className="border-t border-line px-3 py-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-ink-soft">Expected Nifty 500 range</h3>
        <StatusPill tone="warn">Research forecast, forward validation in progress</StatusPill>
      </div>
      {l === null ? (
        <p className="text-sm text-ink-soft">No range forecast yet. It is made at 08:55 IST on trading days, once the previous evening&apos;s index candles and the US close are in.</p>
      ) : (
        <>
          <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
            <div className="text-2xl font-semibold tabular-nums" aria-label={`Expected range ${pct(l.forecast_range)}`}>{pct(l.forecast_range)} <span className="text-sm font-normal text-ink-soft">expected high-low range for {day(l.for_day)}, as a share of the open</span></div>
            {l.actual_range !== null && <div className="text-sm text-ink-soft">Actual: <b className="tabular-nums text-ink">{pct(l.actual_range)}</b></div>}
          </div>
          <p className="mt-1 text-xs text-ink-soft">
            {d.five_session_avg !== null ? `For comparison, the average of the last five sessions is ${pct(d.five_session_avg)}${d.yesterday_range !== null ? ` and yesterday's range was ${pct(d.yesterday_range)}` : ""}. ` : ""}
            Forecast generated {when(l.made_at)} IST on {day(l.made_at)}.
          </p>
        </>
      )}
      <p className="mt-1 text-xs text-ink-faint">This estimates how big the day&apos;s range is likely to be, not which way the market moves, and it is not a trading signal. {d.resolved} of {d.needed} forecasts have resolved towards its one-time forward test.</p>
      {d.record.length > 0 && (
        <details className="mt-2 text-xs text-ink-soft">
          <summary className="cursor-pointer font-medium">Latest resolved forecasts</summary>
          <table className="mt-1 w-full max-w-md text-left">
            <caption className="sr-only">Expected range against the actual range, latest sessions</caption>
            <thead className="border-b border-line text-ink-faint"><tr><th scope="col" className="py-1 font-normal">Session</th><th scope="col" className="text-right font-normal">Expected</th><th scope="col" className="text-right font-normal">Actual</th></tr></thead>
            <tbody>{d.record.slice(0, 5).map((r) => <tr key={r.target_day} className="border-b border-line last:border-0"><th scope="row" className="py-1 font-normal">{day(r.target_day)}</th><td className="text-right tabular-nums">{pct(r.forecast)}</td><td className="text-right tabular-nums">{pct(r.actual)}</td></tr>)}</tbody>
          </table>
        </details>
      )}
    </div>
  );
}

/** What history says about days like today: how the Nifty 50 did after earlier days in the same market zone. */
function History() {
  const zone = useQuery({ queryKey: ["market", "zone"], queryFn: api.marketZone, refetchInterval: 60_000 });
  const perf = useQuery({ queryKey: ["market", "zone", "performance"], queryFn: api.zonePerformance, staleTime: 5 * 60_000 });
  const label = zone.data?.latest?.label;
  const row = perf.data?.zones.find((z) => z.zone === label);
  const all = perf.data?.zones.find((z) => z.zone === "All days");
  if (!label || !row || !all) return null;
  const f = (r: typeof row, h: number) => r.forward.find((x) => x.horizon === h);
  const line = (h: number) => {
    const a = f(row, h), b = f(all, h);
    if (!a || !b || a.avg_pct === null || a.up_pct === null || b.up_pct === null) return null;
    return `${h} days later it was higher ${Math.round(a.up_pct)}% of the time (average ${a.avg_pct >= 0 ? "+" : "−"}${Math.abs(a.avg_pct).toFixed(1)}%), against ${Math.round(b.up_pct)}% on any day`;
  };
  const lines = [20, 60].map(line).filter((x): x is string => x !== null);
  if (lines.length === 0) return null;
  return (
    <div className="border-t border-line px-3 py-3">
      <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-soft">What history says about days like today</h3>
      <p className="text-sm">The market zone is <b>{label}</b>. Since 2016 that has happened on {row.days.toLocaleString("en-IN")} days. After those days, the Nifty 50:</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">{lines.map((l) => <li key={l}>{l}.</li>)}</ul>
      <p className="mt-1 text-xs text-ink-faint">These figures cover the whole of 2016 to now, so they describe the past, not a tested forecast: when we predicted each day using only what was known at the time, this zone tendency did not beat simply assuming the market&apos;s usual pattern. Days next to each other also overlap, so it is weaker evidence than the counts suggest.</p>
    </div>
  );
}

/** Can the day-ahead call be trusted? Said plainly, with the numbers. */
function Trust({ d }: { d: Forecast }) {
  const mine = d.record.filter((r) => !d.product || r.product === d.product); // night and morning are never mixed
  const walk = mine.filter((r) => !r.live);
  const live = mine.filter((r) => r.live);
  const beats = mine.some((r) => r.beats_guessing);
  const w1 = walk.find((r) => r.horizon_days === 1);
  return (
    <div className="border-t border-line px-3 py-3">
      <h3 className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-soft">Can the day-ahead call be trusted?</h3>
      {w1 && !beats ? (
        <Alert tone="warn" title="Not yet: it has not beaten plain guessing">
          On {w1.n.toLocaleString("en-IN")} past days it called the direction right {pct(w1.hit_rate)} of the time. Simply saying &quot;{w1.base_rate >= 0.5 ? "up" : "down"}&quot; every day would have been right {pct(w1.base_hit)}. Treat the percentages above as a mild lean and watch how today goes, not as a signal to act on.
        </Alert>
      ) : w1 ? (
        <p className="text-sm">On {w1.n.toLocaleString("en-IN")} past days it called the direction right {pct(w1.hit_rate)} of the time, against {pct(w1.base_hit)} for always saying the same direction.</p>
      ) : null}
      {live.length > 0 && <p className="mt-1 text-xs text-ink-soft">Live since it started: {live.map((r) => `${WHEN[r.horizon_days] ?? `${r.horizon_days} days`} right ${pct(r.hit_rate)} of ${r.n} days`).join("; ")}.</p>}
    </div>
  );
}

/** What to expect, what history says about conditions like today, whether the call can be trusted, and how today is going against it. */
export function ForecastPanel() {
  const q = useQuery({ queryKey: ["market", "forecast"], queryFn: api.marketForecast, refetchInterval: 60_000 });
  if (q.isError) return <Alert tone="error" title="Could not load the forecast">Try again in a moment.</Alert>;
  if (q.isLoading || !q.data) return <div role="status" aria-label="Loading the forecast"><Skeleton className="h-40 w-full" /></div>;
  const d = q.data;
  if (!d.as_of) return <Alert tone="info" title="No forecast yet">The nightly job has not made one.</Alert>;
  const mine = d.record.filter((r) => !d.product || r.product === d.product);
  const walk = mine.filter((r) => !r.live);
  const live = mine.filter((r) => r.live);
  return (
    <Panel title="Outlook">
      {d.product && <p className="px-3 pt-2 text-xs font-medium text-ink">{d.product === "morning" ? "Morning forecast" : "Night forecast"}{d.cutoff ? `, made at ${d.cutoff}` : ""}.{d.product === "night" ? " It cannot see the US session; the morning forecast replaces it at 08:50 IST." : ""}</p>}
      <p className="px-3 pb-2 pt-1 text-xs text-ink-soft">Made after the close of {d.as_of} from the market zone, the index trend and sector rotation. It says which way the market leans, not how far it will go, and it is shown beside what is actually happening.</p>
      <Overnight d={d} />
      <Today d={d} />
      <ExpectedRange />
      <History />
      <Trust d={d} />
      <details className="border-t border-line px-3 py-2 text-xs text-ink-soft">
        <summary className="cursor-pointer font-medium">Details: the 5-day call, the record, and the biggest misses</summary>
        <ul className="mt-2 space-y-1">
          {d.market.filter((m) => m.horizon_days !== 1).map((m) => <li key={m.horizon_days}>{WHEN[m.horizon_days] ?? `${m.horizon_days} days`}: {CALL_TEXT[call(m.p_up)]} ({pct(m.p_up)} chance of a rise){m.evidence.length > 0 ? `; ${why(m.evidence, d.labels ?? {})}` : ""}.</li>)}
          {[...walk, ...live].map((r) => (
            <li key={`${r.horizon_days}-${r.live}`}>{WHEN[r.horizon_days] ?? `${r.horizon_days} days`}, {r.live ? "live" : "tested on past days it had not seen"}: right {pct(r.hit_rate)} of {r.n} days; always saying {r.base_rate >= 0.5 ? "up" : "down"} {pct(r.base_hit)}.</li>
          ))}
        </ul>
        {d.misses.length > 0 && (
          <>
            <p className="mt-2 font-medium">Most confident wrong calls (market, 1 day)</p>
            <ul className="mt-1 space-y-1">
              {d.misses.map((m) => <li key={m.as_of}>{m.as_of}: said {pct(m.p_up)} up, the market {m.went_up ? "rose" : "fell"} {(Math.abs(m.realized) * 100).toFixed(1)}%.</li>)}
            </ul>
          </>
        )}
        <p className="mt-2">The model is refitted as every outcome becomes known and never scored on days it was trained on.</p>
      </details>
    </Panel>
  );
}
