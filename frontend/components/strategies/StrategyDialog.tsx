"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { SettingsSection } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";
import type { Strategies, StrategyConfig } from "@/lib/schemas";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Could not save. Try again.");
type Params = Required<StrategyConfig["params"]>;
export const DEFAULTS: Params = { trend_sma: 200, entry_rsi: 25, exit_rsi: 60, max_positions: 10 };

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

/** Create a strategy, or change one (then `strategy` is given). Changing one changes it for the trading account that uses it. */
export function StrategyDialog({ open, onClose, options, strategy }: { open: boolean; onClose: () => void; options: Strategies["options"]; strategy?: StrategyConfig }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [name, setName] = useState(strategy?.name ?? "");
  const [universe, setUniverse] = useState(strategy?.universe ?? "nifty200");
  const [cap, setCap] = useState(strategy?.max_instruments ? String(strategy.max_instruments) : "");
  const [timeframe, setTimeframe] = useState(strategy?.timeframe ?? "1D");
  const [params, setParams] = useState<Params>({ ...DEFAULTS, ...strategy?.params });
  const grid = options.params;
  const capNumber = cap.trim() === "" ? null : Number(cap);
  const capBad = capNumber !== null && (!Number.isInteger(capNumber) || capNumber < 5 || capNumber > 500);
  const body = { name: name.trim(), universe, max_instruments: capNumber, timeframe, params };
  const save = useMutation({
    mutationFn: async () => void (await (strategy ? api.changeStrategy(strategy.config_id, body) : api.createStrategy(body))),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["strategies"] });
      void qc.invalidateQueries({ queryKey: ["paper"] });
      toast.success(strategy ? "Strategy saved." : "Strategy created.");
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!capBad) save.mutate();
  };
  const set = <K extends keyof Params>(k: K) => (n: number) => setParams((p) => ({ ...p, [k]: n }));
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={strategy ? "Change strategy" : "New strategy"}
      description={strategy?.in_use ? "Your trading account uses this strategy. Changes apply from its next daily decision." : "A named set of choices you can run, test and give your paper account."}
      footer={
        <>
          <button type="button" onClick={onClose} className={buttonClass("secondary")}>Cancel</button>
          <button type="submit" form="strategy-form" disabled={capBad || !name.trim() || save.isPending} className={buttonClass("primary")}>{strategy ? "Save strategy" : "Create strategy"}</button>
        </>
      }
    >
      <form id="strategy-form" onSubmit={submit}>
        {save.isError ? <div className="mb-4"><Alert tone="error">{message(save.error)}</Alert></div> : null}
        <SettingsSection title="Name">
          <Field id="strategy-name" label="Name" hint="Up to 60 characters. It must differ from your other strategies.">
            <input id="strategy-name" required maxLength={60} value={name} onChange={(e) => setName(e.target.value)} className={inputFull} />
          </Field>
        </SettingsSection>
        <SettingsSection title="What it trades" description="The index the strategy picks from, and how many of its most liquid stocks to consider.">
          <div className="space-y-4">
            <Field id="universe" label="Index">
              <select id="universe" value={universe} onChange={(e) => setUniverse(e.target.value)} className={inputFull}>
                {options.universes.map((u) => (
                  <option key={u.key} value={u.key}>{u.label}</option>
                ))}
              </select>
            </Field>
            <Field id="cap" label="Number of stocks" hint="Leave empty to use the whole index. A number keeps only that many of the most traded stocks (5 to 500), which avoids thinly traded ones." error={capBad ? "Enter a whole number from 5 to 500, or leave it empty." : null}>
              <input id="cap" inputMode="numeric" placeholder="All" value={cap} onChange={(e) => setCap(e.target.value)} className={inputFull} />
            </Field>
            <Field id="timeframe" label="Time frame" hint="The bar size the strategy decides on. Only daily is supported today; shorter ones need intraday data in the strategy engine.">
              <select id="timeframe" value={timeframe} onChange={(e) => setTimeframe(e.target.value)} className={inputFull}>
                {options.timeframes.map((t) => (
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
      </form>
    </Dialog>
  );
}
