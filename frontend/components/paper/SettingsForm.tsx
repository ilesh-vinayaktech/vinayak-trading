"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Field } from "@/components/ui/Field";
import { Panel, SettingsSection } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";
import type { PaperAccount } from "@/lib/schemas";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Could not save. Try again.");
type Params = { trend_sma: number; entry_rsi: number; exit_rsi: number; max_positions: number };
const DEFAULTS: Params = { trend_sma: 200, entry_rsi: 25, exit_rsi: 60, max_positions: 10 };

function Choice({ id, label, hint, value, options, onChange }: { id: string; label: string; hint: string; value: number; options: number[]; onChange: (n: number) => void }) {
  return (
    <Field id={id} label={label} hint={hint}>
      <select id={id} value={value} onChange={(e) => onChange(Number(e.target.value))} className={inputFull}>
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </Field>
  );
}

/** What the strategy runs on and how it behaves. The same form starts an account (with a starting amount) and edits one. */
export function SettingsForm({ data }: { data: PaperAccount }) {
  const qc = useQueryClient();
  const toast = useToast();
  const acct = data.account;
  const [cash, setCash] = useState("1000000");
  const [universe, setUniverse] = useState(acct?.universe ?? "nifty200");
  const [cap, setCap] = useState(acct?.max_instruments ? String(acct.max_instruments) : "");
  const [timeframe, setTimeframe] = useState(acct?.timeframe ?? "1D");
  const [params, setParams] = useState<Params>(acct?.params ?? DEFAULTS);
  const grid = data.options.params;
  const capNumber = cap.trim() === "" ? null : Number(cap);
  const capBad = capNumber !== null && (!Number.isInteger(capNumber) || capNumber < 5 || capNumber > 500);
  const refresh = () => void qc.invalidateQueries({ queryKey: ["paper"] });
  const create = useMutation({
    mutationFn: () => api.createPaperAccount({ initial_cash: cash, universe, max_instruments: capNumber, timeframe, params }),
    onSuccess: () => { toast.success("Paper account started."); refresh(); },
  });
  const save = useMutation({
    mutationFn: () => api.updatePaperSettings({ universe, max_instruments: capNumber, timeframe, params }),
    onSuccess: () => { toast.success("Settings saved. They apply from the next daily decision."); refresh(); },
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.updatePaperSettings({ enabled }),
    onSuccess: (_d, enabled) => { toast.success(enabled ? "Paper trading is on." : "Paper trading is off. No new orders will be proposed."); refresh(); },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (capBad) return;
    (acct ? save : create).mutate();
  };
  const err = create.error ?? save.error ?? toggle.error;
  const set = <K extends keyof Params>(k: K) => (n: number) => setParams((p) => ({ ...p, [k]: n }));

  return (
    <Panel>
      <form onSubmit={submit} className="px-6 py-6">
        {err ? <div className="mb-4"><Alert tone="error">{message(err)}</Alert></div> : null}
        {acct ? (
          <SettingsSection title="Paper trading" description="Switch it off to stop new proposals. Orders already approved still fill.">
            <button type="button" role="switch" aria-checked={acct.enabled} aria-label="Paper trading" disabled={toggle.isPending} onClick={() => toggle.mutate(!acct.enabled)} className={`inline-flex h-7 w-12 items-center rounded-full border border-line p-0.5 transition-colors ${acct.enabled ? "bg-brand" : "bg-slate-200"}`}>
              <span className={`h-5 w-5 rounded-full bg-white shadow transition-transform ${acct.enabled ? "translate-x-5" : ""}`} />
            </button>
            <span className="ml-3 align-middle text-sm text-ink-soft">{acct.enabled ? "On" : "Off"}</span>
          </SettingsSection>
        ) : (
          <SettingsSection title="Starting money" description="Pretend cash for this account. No real money is involved.">
            <Field id="cash" label="Starting cash (₹)">
              <input id="cash" inputMode="decimal" required pattern="[0-9]+(\.[0-9]{1,2})?" value={cash} onChange={(e) => setCash(e.target.value)} className={inputFull} />
            </Field>
          </SettingsSection>
        )}
        <SettingsSection title="What it trades" description="The index the strategy picks from, and how many of its most liquid stocks to consider.">
          <div className="space-y-4">
            <Field id="universe" label="Index">
              <select id="universe" value={universe} onChange={(e) => setUniverse(e.target.value)} className={inputFull}>
                {data.options.universes.map((u) => (
                  <option key={u.key} value={u.key}>{u.label}</option>
                ))}
              </select>
            </Field>
            <Field id="cap" label="Number of stocks" hint="Leave empty to use the whole index. A number keeps only that many of the most traded stocks (5 to 500), which avoids thinly traded ones." error={capBad ? "Enter a whole number from 5 to 500, or leave it empty." : null}>
              <input id="cap" inputMode="numeric" placeholder="All" value={cap} onChange={(e) => setCap(e.target.value)} className={inputFull} />
            </Field>
            <Field id="timeframe" label="Time frame" hint="The bar size the strategy decides on. Only daily is supported today; shorter ones need intraday data in the strategy engine.">
              <select id="timeframe" value={timeframe} onChange={(e) => setTimeframe(e.target.value)} className={inputFull}>
                {data.options.timeframes.map((t) => (
                  <option key={t.key} value={t.key} disabled={!t.available}>{t.label}{t.available ? "" : " (not available yet)"}</option>
                ))}
              </select>
            </Field>
          </div>
        </SettingsSection>
        <SettingsSection title="How it behaves" description="The rules of the pullback strategy: buy a stock that has dipped inside an uptrend, sell it when it recovers.">
          <div className="grid gap-4 sm:grid-cols-2">
            <Choice id="trend" label="Uptrend test (days)" hint="Only buy a stock trading above its average of this many days." value={params.trend_sma} options={grid.trend_sma} onChange={set("trend_sma")} />
            <Choice id="max" label="Most stocks held at once" hint="Each gets an equal share of the account." value={params.max_positions} options={grid.max_positions} onChange={set("max_positions")} />
            <Choice id="entry" label="Buy when the 5-day RSI is below" hint="Lower means a deeper dip and fewer trades." value={params.entry_rsi} options={grid.entry_rsi} onChange={set("entry_rsi")} />
            <Choice id="exit" label="Sell when the 5-day RSI is above" hint="Higher means holding on for more of the recovery." value={params.exit_rsi} options={grid.exit_rsi} onChange={set("exit_rsi")} />
          </div>
        </SettingsSection>
        {acct ? <p className="mb-4 text-xs text-ink-soft">Changing the index or the number of stocks does not sell anything right away: holdings that no longer qualify are sold at the next daily decision.</p> : null}
        <button type="submit" disabled={capBad || create.isPending || save.isPending} className={buttonClass("primary")}>{acct ? "Save settings" : "Start paper trading"}</button>
      </form>
    </Panel>
  );
}
