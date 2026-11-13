"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Panel, SettingsSection } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { ApiError, api } from "@/lib/api/client";
import { studySpecSchema, type StudyOptions, type StudySpec } from "@/lib/schemas";
import { THRESHOLD_LABELS, holdoutFor, holdoutShare, orderSizeWarnings, trialCount } from "@/lib/studies";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Could not register the study. Try again.");
const SEGMENT_LABELS: Record<string, string> = { large: "Large cap (ranks 1-100)", mid: "Mid cap (101-250)", small: "Small cap (251-500)", micro: "Micro cap (501 and beyond)" };
const PARAM_LABELS: Record<string, string> = { trend_sma: "Uptrend test (days)", entry_rsi: "Buy when 5-day RSI is below", exit_rsi: "Sell when 5-day RSI is above", max_positions: "Most stocks held at once" };

const OPS: Record<string, string> = { gt: ">", gte: "≥", lt: "<", lte: "≤", eq: "=", ne: "≠", between: "between" };
type Screen = NonNullable<StudySpec["screen"]>;
/** The screen the Screener page hands over in the address, or null when there is none (or it is not one). */
function parseScreen(raw: string | null): Screen | null {
  try {
    const r = studySpecSchema.shape.screen.unwrap().unwrap().safeParse(JSON.parse(raw ?? "null"));
    return r.success && r.data.conditions.length > 0 ? r.data : null;
  } catch {
    return null;
  }
}

/** Every choice of an official backtest. Nothing here is fixed in code; all of it is locked once the study is registered. */
export function StudyForm({ options }: { options: StudyOptions }) {
  const router = useRouter();
  const params = useSearchParams();
  const fromScreener = parseScreen(params.get("screen"));
  const [source, setSource] = useState<"code" | "screen">(fromScreener ? "screen" : "code");
  const [screen, setScreen] = useState<Screen | null>(fromScreener);
  const strategy = options.strategies.find((s) => (s.id === "screener") === (source === "screen")) ?? options.strategies[0];
  const saved = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  const meta = useQuery({ queryKey: ["screener-meta"], queryFn: api.screenerMeta, staleTime: Infinity });
  const kind = (k: string) => meta.data?.fields.find((f) => f.key === k)?.kind;
  const label = (k: string) => meta.data?.fields.find((f) => f.key === k)?.label ?? k;
  const usable = (k: string) => ["technical", "fundamental"].includes(kind(k) ?? "");
  const backtestable = (meta.data?.presets ?? []).filter((p) => p.conditions.every((c) => usable(c.field)) && usable(p.sort));
  const end0 = options.frozen_through ?? "";
  const start0 = options.survivorship_safe_from;
  const [name, setName] = useState("");
  const [hypothesis, setHypothesis] = useState("");
  // arriving from "Backtest it" on a saved screener: its stock count and the caps it picks from come along with the screen
  const slots = Number(params.get("slots"));
  const [grid, setGrid] = useState<Record<string, number[]>>(() =>
    Object.fromEntries((strategy?.params ?? []).map((p) => [p.name, fromScreener && p.name === "max_positions" && p.choices?.includes(slots) ? [slots] : [p.default]])),
  );
  const [segments, setSegments] = useState<string[]>(() => {
    const given = fromScreener ? (params.get("segments") ?? "").split(",").filter((k) => options.segments.includes(k)) : [];
    return given.length > 0 ? given : ["large", "mid"];
  });
  const [beforeLists, setBeforeLists] = useState("traded_value_rank");
  const [minHistory, setMinHistory] = useState("252");
  const [start, setStart] = useState(start0);
  const [end, setEnd] = useState(end0);
  const [holdout, setHoldout] = useState(end0 ? holdoutFor(start0, end0, 25) : "");
  const [capital, setCapital] = useState("1000000");
  const [capacity, setCapacity] = useState("3");
  const [broker, setBroker] = useState(options.brokers[0] ? `${options.brokers[0].broker}|${options.brokers[0].product}` : "");
  const [slip, setSlip] = useState({ base_bps: "5", participation_bps_per_pct: "5", volatility_fraction: "0" });
  const [benchmark, setBenchmark] = useState(options.benchmarks.find((b) => b.default)?.name ?? options.benchmarks[0]?.name ?? "");
  const [minOrder, setMinOrder] = useState("");
  const [maxOrder, setMaxOrder] = useState("");
  const [thresholds, setThresholds] = useState<Record<string, string>>(options.thresholds);
  const [acceptBias, setAcceptBias] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const trials = trialCount(grid);
  const share = holdoutShare(start, end, holdout);
  const early = start !== "" && start < options.survivorship_safe_from;
  const beforeSegments = start !== "" && start < options.segment_lists_from;
  const [lo, hi] = options.holdout_share as [number, number];
  const problems = [
    source === "screen" && !screen && "Pick a screen to trade: start from a ready-made one below, or build one on the Screener page.",
    !name.trim() && "Give the study a name.",
    hypothesis.trim().length < 20 && "Write the hypothesis (at least 20 characters): what you expect, and why.",
    trials === 0 && "Pick at least one value for every parameter.",
    trials > options.max_trials && `${trials} trials is more than ${options.max_trials}: every combination counts against the strategy.`,
    segments.length === 0 && "Pick at least one market-cap segment.",
    (share === null || share < lo || share > hi) && `Keep the holdout between ${lo * 100}% and ${hi * 100}% of the study (the spec suggests 20-30%).`,
    options.frozen_through && end > options.frozen_through && `The study must end by ${options.frozen_through}, the end of the frozen history.`,
    Number(minOrder || 0) < 0 && "The minimum order cannot be negative.",
    maxOrder.trim() !== "" && !(Number(maxOrder) > 0) && "The maximum order must be more than zero, or left empty.",
    maxOrder.trim() !== "" && Number(maxOrder) > 0 && Number(maxOrder) < Number(minOrder || 0) && "The maximum order cannot be below the minimum.",
    early && !acceptBias && `Starting before ${options.survivorship_safe_from} needs the survivorship bias accepted below.`,
  ].filter((p): p is string => Boolean(p));

  const sizeAdvice = orderSizeWarnings(capital, grid.max_positions ?? [], minOrder, maxOrder);
  const [b, product] = broker.split("|");
  const body = {
    name: name.trim(), hypothesis: hypothesis.trim(), strategy_id: strategy?.id ?? "", grid, screen: source === "screen" ? screen : undefined,
    universe: { segments, before_segment_lists: beforeLists, min_history_sessions: Number(minHistory) || 0 },
    timeframe: "1D", start, end, holdout_start: holdout, capital, capacity_multiple: capacity, broker: b ?? "", product: product ?? "DELIVERY",
    slippage: slip, benchmark, min_order_value: minOrder.trim() || "0", max_order_value: maxOrder.trim() || null, thresholds, accept_survivorship_bias: acceptBias,
  };
  const register = useMutation({
    mutationFn: () => api.registerStudy(body),
    onSuccess: (r) => router.replace(`/research/studies/${r.experiment_id}`),
  });
  const defaults = (id: string) => Object.fromEntries((options.strategies.find((s) => s.id === id)?.params ?? []).map((p) => [p.name, [p.default]]));
  const switchSource = (next: "code" | "screen") => {
    setSource(next);
    setGrid(defaults(options.strategies.find((s) => (s.id === "screener") === (next === "screen"))?.id ?? ""));
  };
  const toggle = (param: string, v: number) => setGrid((g) => ({ ...g, [param]: (g[param] ?? []).includes(v) ? (g[param] ?? []).filter((x) => x !== v) : [...(g[param] ?? []), v].sort((x, y) => x - y) }));
  // a trend study starts from saved trend strategies, a screener study from saved screeners: never the other kind
  const savedOfKind = (saved.data?.strategies ?? []).filter((s) => (s.screen !== null) === (source === "screen"));
  const fromSaved = (id: string) => {
    const s = savedOfKind.find((x) => x.config_id === id);
    if (!s) return;
    setGrid(Object.fromEntries(Object.entries(s.params).map(([k, v]) => [k, [v as number]])));
    if (s.screen) {
      setScreen(parseScreen(JSON.stringify(s.screen.screen)));
      setSegments(s.screen.segments);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (problems.length === 0) setConfirming(true);
  };

  return (
    <Panel>
      <form onSubmit={submit} className="px-6 py-6" aria-label="New backtest study">
        <SettingsSection title="The idea" description="Written down before anything runs. It is what the result will be judged against.">
          <div className="space-y-4">
            <Field id="study-name" label="Name"><input id="study-name" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} className={inputFull} /></Field>
            <Field id="study-hypothesis" label="Hypothesis" hint="What you expect to happen and why, and how it could fail.">
              <textarea id="study-hypothesis" rows={3} maxLength={4000} value={hypothesis} onChange={(e) => setHypothesis(e.target.value)} className={inputFull} />
            </Field>
          </div>
        </SettingsSection>

        <SettingsSection title="Strategy and settings to try" description={`Every combination is one trial, and every trial counts against the strategy. ${trials} trial${trials === 1 ? "" : "s"} (at most ${options.max_trials}).`}>
          <div className="space-y-4">
            <fieldset>
              <legend className="text-sm font-medium">Where the strategy comes from</legend>
              <div className="mt-1 flex flex-wrap gap-4">
                <label className="flex items-center gap-1.5 text-sm"><input type="radio" name="study-source" checked={source === "code"} onChange={() => switchSource("code")} />A coded strategy</label>
                <label className="flex items-center gap-1.5 text-sm"><input type="radio" name="study-source" checked={source === "screen"} onChange={() => switchSource("screen")} />A screener</label>
              </div>
            </fieldset>
            {source === "screen" ? (
              <div className="space-y-3">
                <p className="text-sm text-ink-soft">Every trading day the screen runs on what was known that day (prices, and results as filed by then) and the best matches are held, equal weight, up to the number of slots. A market-cap class cannot be a condition here: choose the segments under Which stocks.</p>
                <Field id="study-screen" label="Start from a ready-made screen">
                  <select id="study-screen" value="" onChange={(e) => { const p = backtestable.find((x) => x.id === e.target.value); if (p) setScreen({ conditions: p.conditions, match: "all", sort: p.sort, descending: p.descending }); }} className={inputFull}>
                    <option value="">Choose...</option>
                    {backtestable.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                  </select>
                </Field>
                {screen ? (
                  <div className="rounded-lg border border-line p-3 text-sm">
                    <p className="font-medium">Match {screen.match === "all" ? "all" : "any"} of:</p>
                    <ul className="mt-1 list-disc pl-5" aria-label="Screen conditions">
                      {screen.conditions.map((c, i) => <li key={i}>{label(c.field)} {OPS[c.op] ?? c.op} {Array.isArray(c.value) ? c.value.join(" and ") : String(c.value)}</li>)}
                    </ul>
                    <p className="mt-1 text-ink-soft">Best first: {label(screen.sort)}, {screen.descending ? "highest" : "lowest"} first.</p>
                  </div>
                ) : null}
                <p className="text-sm text-ink-soft">Want your own conditions? Build them on the <Link href="/screener" className="text-brand hover:underline">Screener page</Link> and choose &ldquo;Backtest as a strategy&rdquo;.</p>
              </div>
            ) : null}
            {savedOfKind.length > 0 ? (
              <Field id="study-from" label="Start from a saved strategy" hint="Fills the settings below with that strategy's values; add more values to test around them.">
                <select id="study-from" defaultValue="" onChange={(e) => fromSaved(e.target.value)} className={inputFull}>
                  <option value="">Choose...</option>
                  {savedOfKind.map((s) => (
                    <option key={s.config_id} value={s.config_id}>{s.name}</option>
                  ))}
                </select>
              </Field>
            ) : null}
            {(strategy?.params ?? []).map((p) => (
              <fieldset key={p.name}>
                <legend className="text-sm font-medium">{PARAM_LABELS[p.name] ?? p.name}</legend>
                <div className="mt-1 flex flex-wrap gap-3">
                  {(p.choices ?? [p.default]).map((v) => (
                    <label key={v} className="flex items-center gap-1.5 text-sm">
                      <input type="checkbox" aria-label={`${p.name} ${v}`} checked={(grid[p.name] ?? []).includes(v)} onChange={() => toggle(p.name, v)} />
                      {v}
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
          </div>
        </SettingsSection>

        <SettingsSection title="Which stocks" description="By market-cap segment as AMFI ranked it at the time, so the study never uses today's list to pick yesterday's stocks.">
          <div className="space-y-4">
            <div className="flex flex-wrap gap-4">
              {options.segments.map((s) => (
                <label key={s} className="flex items-center gap-1.5 text-sm">
                  <input type="checkbox" checked={segments.includes(s)} onChange={() => setSegments((x) => (x.includes(s) ? x.filter((y) => y !== s) : [...x, s]))} />
                  {SEGMENT_LABELS[s] ?? s}
                </label>
              ))}
            </div>
            {beforeSegments ? (
              <Field id="study-before" label={`Before ${options.segment_lists_from} (no AMFI list yet)`}>
                <select id="study-before" value={beforeLists} onChange={(e) => setBeforeLists(e.target.value)} className={inputFull}>
                  <option value="traded_value_rank">Rank by traded value as a stand-in</option>
                  <option value="skip">Leave those days out</option>
                </select>
              </Field>
            ) : null}
            <Field id="study-history" label="History a stock needs before it can be traded (sessions)">
              <input id="study-history" inputMode="numeric" value={minHistory} onChange={(e) => setMinHistory(e.target.value)} className={inputFull} />
            </Field>
          </div>
        </SettingsSection>

        <SettingsSection title="Period and holdout" description="The holdout is the most recent part of the period. It stays untouched and is opened once, at the very end.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field id="study-timeframe" label="Time frame" hint="Daily until the engine runs intraday strategies.">
              <select id="study-timeframe" value="1D" disabled className={inputFull}>{options.timeframes.map((t) => <option key={t}>{t}</option>)}</select>
            </Field>
            <div />
            <Field id="study-start" label="From"><input id="study-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} className={inputFull} /></Field>
            <Field id="study-end" label="To" hint={options.frozen_through ? `Frozen history ends ${options.frozen_through}.` : "No frozen history yet."}>
              <input id="study-end" type="date" value={end} max={options.frozen_through ?? undefined} onChange={(e) => setEnd(e.target.value)} className={inputFull} />
            </Field>
            <Field id="study-holdout" label="Holdout starts" hint={share === null ? "" : `That keeps the last ${Math.round(share * 100)}% untouched.`}>
              <input id="study-holdout" type="date" value={holdout} onChange={(e) => setHoldout(e.target.value)} className={inputFull} />
            </Field>
            <div className="flex items-end gap-2 pb-1">
              {[20, 25, 30].map((pct) => (
                <button key={pct} type="button" disabled={!start || !end} onClick={() => setHoldout(holdoutFor(start, end, pct))} className={buttonClass("secondary")}>Last {pct}%</button>
              ))}
            </div>
          </div>
          {early ? (
            <div className="mt-4">
              <Alert tone="warn" title="Survivorship bias">Before {options.survivorship_safe_from} our data only holds stocks that are still listed today, which makes results look better than they were.</Alert>
              <label className="mt-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={acceptBias} onChange={(e) => setAcceptBias(e.target.checked)} />I accept this bias for this study</label>
            </div>
          ) : null}
        </SettingsSection>

        <SettingsSection title="Money and costs">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field id="study-capital" label="Capital (₹)"><input id="study-capital" inputMode="decimal" value={capital} onChange={(e) => setCapital(e.target.value)} className={inputFull} /></Field>
            <Field id="study-capacity" label="Capacity test (times capital)"><input id="study-capacity" inputMode="decimal" value={capacity} onChange={(e) => setCapacity(e.target.value)} className={inputFull} /></Field>
            <Field id="study-broker" label="Charges">
              <select id="study-broker" value={broker} onChange={(e) => setBroker(e.target.value)} className={inputFull}>
                {options.brokers.map((x) => (
                  <option key={`${x.broker}|${x.product}`} value={`${x.broker}|${x.product}`}>{x.broker}, {x.product.toLowerCase()}</option>
                ))}
              </select>
            </Field>
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-3">
            <Field id="slip-base" label="Slippage: fixed (bps)" hint="Cost of every order beyond charges. 100 bps = 1%."><input id="slip-base" inputMode="decimal" value={slip.base_bps} onChange={(e) => setSlip((s) => ({ ...s, base_bps: e.target.value }))} className={inputFull} /></Field>
            <Field id="slip-part" label="Slippage: per 1% of volume (bps)" hint="Extra cost for taking a larger share of the day's volume."><input id="slip-part" inputMode="decimal" value={slip.participation_bps_per_pct} onChange={(e) => setSlip((s) => ({ ...s, participation_bps_per_pct: e.target.value }))} className={inputFull} /></Field>
            <Field id="slip-vol" label="Slippage: share of the day's range (0-1)" hint="Wider-moving stocks cost more to trade."><input id="slip-vol" inputMode="decimal" value={slip.volatility_fraction} onChange={(e) => setSlip((s) => ({ ...s, volatility_fraction: e.target.value }))} className={inputFull} /></Field>
          </div>
          <div className="mt-4">
            <Field id="study-benchmark" label="Compare with (index)" hint="The total-return index the results are measured against, on the same days. Only an index whose stored data has passed its validation can back the checks.">
              <select id="study-benchmark" value={benchmark} onChange={(e) => setBenchmark(e.target.value)} className={inputFull}>
                {options.benchmarks.map((b) => <option key={b.name} value={b.name}>{b.name}{b.usable ? "" : " (not validated yet)"}</option>)}
              </select>
            </Field>
          </div>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <Field id="order-min" label="Smallest order (₹)" hint="Skip any order worth less than this, so the strategy does not pay charges on 1-share top-ups. Closing a whole position is always allowed. Empty means no minimum."><input id="order-min" inputMode="decimal" placeholder="no minimum" value={minOrder} onChange={(e) => setMinOrder(e.target.value)} className={inputFull} /></Field>
            <Field id="order-max" label="Largest order (₹)" hint="A bigger order is split over several days. Empty means no maximum."><input id="order-max" inputMode="decimal" placeholder="no maximum" value={maxOrder} onChange={(e) => setMaxOrder(e.target.value)} className={inputFull} /></Field>
          </div>
        </SettingsSection>

        <SettingsSection title="Pass or fail" description="Decided now, before any result. Each must hold for the study to pass.">
          <div className="grid gap-3 sm:grid-cols-2">
            {Object.keys(options.thresholds).map((k) => (
              <Field key={k} id={`th-${k}`} label={THRESHOLD_LABELS[k] ?? k}>
                <input id={`th-${k}`} inputMode="decimal" value={thresholds[k] ?? ""} onChange={(e) => setThresholds((t) => ({ ...t, [k]: e.target.value }))} className={inputFull} />
              </Field>
            ))}
          </div>
        </SettingsSection>

        {sizeAdvice.length > 0 ? (
          <div className="mb-4 space-y-2">
            {sizeAdvice.map((w) => <Alert key={w} tone="warn" title="Check the order sizes">{w}</Alert>)}
          </div>
        ) : null}
        {problems.length > 0 ? (
          <ul className="mb-4 list-disc space-y-1 pl-5 text-sm text-amber-800" aria-label="Before you can register">
            {problems.map((p) => <li key={p}>{p}</li>)}
          </ul>
        ) : null}
        {register.isError ? <div className="mb-4"><Alert tone="error">{message(register.error)}</Alert></div> : null}
        <button type="submit" disabled={problems.length > 0 || register.isPending} className={buttonClass("primary")}>Register study</button>
      </form>
      <Dialog
        open={confirming}
        onClose={() => setConfirming(false)}
        title={`Register "${name.trim()}"?`}
        description={`Once registered nothing about it can change. Its ${trials} trial${trials === 1 ? "" : "s"} will count against the strategy, and the holdout from ${holdout} can be opened only once.`}
        footer={
          <>
            <button type="button" onClick={() => setConfirming(false)} className={buttonClass("secondary")}>Cancel</button>
            <button type="button" onClick={() => { setConfirming(false); register.mutate(); }} className={buttonClass("primary")}>Register and lock</button>
          </>
        }
      >
        <p className="text-sm text-ink-soft">To change anything later you register a new study.</p>
      </Dialog>
    </Panel>
  );
}
