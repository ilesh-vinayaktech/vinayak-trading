"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { DefinitionsSection } from "@/components/paper/DefinitionsSection";
import { DEFAULTS } from "@/components/strategies/StrategyDialog";
import { Alert } from "@/components/ui/Alert";
import { Field } from "@/components/ui/Field";
import { Panel, SettingsSection } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";
import type { PaperAccount } from "@/lib/schemas";
import { useVenue } from "@/lib/venue";

const message = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : "Could not save. Try again.");
const CUSTOM = "";

/** Starts a paper account (with a starting amount) or edits one: on/off and which saved strategy it runs. The strategy's own
 *  choices (stocks, rules) are made on the Strategies page. */
export function SettingsForm({ data }: { data: PaperAccount }) {
  const qc = useQueryClient();
  const toast = useToast();
  const acct = data.account;
  const mode = useVenue();
  const live = mode === "live";
  const strategies = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  const saved = (strategies.data?.strategies ?? []).filter((s) => !live || s.stage === "LIVE"); // a live account runs only what was promoted to the LIVE stage
  const inUse = saved.find((s) => s.in_use)?.config_id ?? CUSTOM;
  const [cash, setCash] = useState(live ? "100000" : "1000000");
  const [pick, setPick] = useState<string | null>(null);
  const chosen = pick ?? (acct ? inUse : (saved[0]?.config_id ?? CUSTOM));
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["paper"] });
    void qc.invalidateQueries({ queryKey: ["strategies"] });
  };
  const create = useMutation({
    mutationFn: async () => {
      const s = saved.find((x) => x.config_id === chosen);
      if (live && !s) throw new Error("Pick a strategy that has been promoted to the LIVE stage first.");
      // an account always starts on the standard settings; a saved strategy (a screener too) is then put on it by `use`
      const plain = !s || s.screen !== null;
      await api.createPaperAccount({ initial_cash: cash, universe: plain ? "nifty200" : s.universe, max_instruments: plain ? null : s.max_instruments, timeframe: "1D", params: plain ? DEFAULTS : { ...DEFAULTS, ...s.params }, ...(live ? { mode } : {}) });
      if (s) await api.useStrategy(s.config_id, mode);
    },
    onSuccess: () => { toast.success(live ? "Live account started." : "Paper account started."); refresh(); },
  });
  const switchTo = useMutation({
    mutationFn: (id: string) => api.useStrategy(id, mode),
    onSuccess: () => { toast.success("Strategy changed. It applies from the next daily decision."); setPick(null); refresh(); },
  });
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => api.updatePaperSettings({ enabled }, mode),
    onSuccess: (_d, enabled) => { toast.success(enabled ? "Trading is on." : "Trading is off. No new orders will be proposed."); refresh(); },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!acct) create.mutate();
  };
  const err = create.error ?? switchTo.error ?? toggle.error;
  const picker = saved.length > 0 && (
    <Field id="strategy" label="Strategy" hint="Saved on the Strategies page, where you choose the index, the number of stocks and the rules.">
      <select
        id="strategy"
        value={chosen}
        onChange={(e) => { setPick(e.target.value); if (acct && e.target.value !== CUSTOM) switchTo.mutate(e.target.value); }}
        className={inputFull}
      >
        {!acct ? null : <option value={CUSTOM} disabled>Custom (not a saved strategy)</option>}
        {saved.map((s) => (
          <option key={s.config_id} value={s.config_id}>{s.name}</option>
        ))}
      </select>
    </Field>
  );

  return (
    <Panel>
      <form onSubmit={submit} className="px-6 py-6">
        {err ? <div className="mb-4"><Alert tone="error">{message(err)}</Alert></div> : null}
        {acct ? (
          <SettingsSection title="Trading" description="Switch it off to stop new proposals. Orders already approved still fill.">
            <button type="button" role="switch" aria-checked={acct.enabled} aria-label="Trading" disabled={toggle.isPending} onClick={() => toggle.mutate(!acct.enabled)} className={`inline-flex h-7 w-12 items-center rounded-full border border-line p-0.5 transition-colors ${acct.enabled ? "bg-brand" : "bg-slate-200"}`}>
              <span className={`h-5 w-5 rounded-full bg-white shadow transition-transform ${acct.enabled ? "translate-x-5" : ""}`} />
            </button>
            <span className="ml-3 align-middle text-sm text-ink-soft">{acct.enabled ? "On" : "Off"}</span>
          </SettingsSection>
        ) : (
          <SettingsSection title={live ? "Capital" : "Starting money"} description={live ? "The most money the platform may use for live orders. Real money: it never touches shares you bought yourself." : "Pretend cash for this account. No real money is involved."}>
            <Field id="cash" label={live ? "Capital (₹)" : "Starting cash (₹)"}>
              <input id="cash" inputMode="decimal" required pattern="[0-9]+(\.[0-9]{1,2})?" value={cash} onChange={(e) => setCash(e.target.value)} className={inputFull} />
            </Field>
          </SettingsSection>
        )}
        <SettingsSection title="What it runs" description={acct ? (acct.definition ? `Strategy definition ${acct.definition}: its rules and settings are fixed by the study that passed.` : acct.screen ? `Screener: holds up to ${acct.params.max_positions} stocks that match the screen, from ${acct.screen.segments.join(" + ")} caps.` : `Index: ${data.options.universes.find((u) => u.key === acct.universe)?.label ?? acct.universe}, ${acct.max_instruments ? `top ${acct.max_instruments} stocks` : "all stocks"}.`) : "Pick a saved strategy, or start with the standard settings (Nifty 200, all stocks)."}>
          {picker || <p className="text-sm text-ink-soft">You have no saved strategies yet.</p>}
          <p className="mt-3 text-sm"><Link href="/strategies" className="font-medium text-brand underline">{saved.length > 0 ? "Manage strategies" : "Create a strategy"}</Link></p>
        </SettingsSection>
        {live ? null : <DefinitionsSection hasAccount={!!acct} current={acct?.definition ?? null} />}
        {acct ? <p className="mb-4 text-xs text-ink-soft">Changing the strategy does not sell anything right away: holdings that no longer qualify are sold at the next daily decision.</p> : null}
        {acct ? null : <button type="submit" disabled={create.isPending} className={buttonClass("primary")}>{live ? "Start live trading" : "Start paper trading"}</button>}
      </form>
    </Panel>
  );
}
