"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";
import type { CostSchedule } from "@/lib/schemas";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Could not save. Try again.");
const TYPE_LABEL: Record<string, string> = { BROKERAGE: "Brokerage", STT: "STT", EXCHANGE_TRANSACTION: "Exchange charges", SEBI_TURNOVER: "SEBI fee", STAMP_DUTY: "Stamp duty", DP_CHARGE: "Demat (DP) charge", GST: "GST" };
export const typeLabel = (t: string) => TYPE_LABEL[t] ?? t;

function useDone(onClose: () => void, text: string) {
  const qc = useQueryClient();
  const toast = useToast();
  return () => {
    void qc.invalidateQueries({ queryKey: ["costs"] });
    toast.success(text);
    onClose();
  };
}

/** A price change: the new rates and the day they start. The old rates end the day before. */
export function NewVersionDialog({ open, onClose, schedule }: { open: boolean; onClose: () => void; schedule: CostSchedule }) {
  const [from, setFrom] = useState("");
  const [until, setUntil] = useState("");
  const [note, setNote] = useState("");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const key = (c: CostSchedule["components"][number]) => `${c.type}|${c.side}`;
  const original = (c: CostSchedule["components"][number]) => c.rate_pct ?? c.amount ?? "";
  const changed = schedule.components.filter((c) => edits[key(c)] !== undefined && edits[key(c)] !== original(c));
  const done = useDone(onClose, "New version saved. It needs checking before it counts as verified.");
  const save = useMutation({
    mutationFn: () => api.newCostVersion(schedule.schedule_id, schedule.version, { valid_from: from, valid_until: until || null, note, changes: changed.map((c) => (c.rate_pct !== null ? { type: c.type, side: c.side, rate_pct: edits[key(c)] } : { type: c.type, side: c.side, amount: edits[key(c)] })) }),
    onSuccess: done,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Enter a price change"
      description={`Starts from a copy of the ${schedule.broker} ${schedule.product.toLowerCase()} rates. Change only what changed.`}
      footer={
        <>
          <button type="button" onClick={onClose} className={buttonClass("secondary")}>Cancel</button>
          <button type="submit" form="cost-version" disabled={save.isPending || changed.length === 0 || !from || !note.trim()} className={buttonClass("primary")}>Save new version</button>
        </>
      }
    >
      <form id="cost-version" onSubmit={submit} className="space-y-4">
        {save.isError ? <Alert tone="error">{message(save.error)}</Alert> : null}
        <div className="grid grid-cols-2 gap-4">
          <Field id="cv-from" label="Effective from"><input id="cv-from" type="date" required value={from} onChange={(e) => setFrom(e.target.value)} className={inputFull} /></Field>
          <Field id="cv-until" label="Ends (optional)"><input id="cv-until" type="date" value={until} onChange={(e) => setUntil(e.target.value)} className={inputFull} /></Field>
        </div>
        <Field id="cv-note" label="Where do these rates come from?" hint="For example: Zerodha charges page, checked 12 Nov 2026. This is kept as the source of every rate you change."><input id="cv-note" required maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} className={inputFull} /></Field>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium text-ink">Rates</legend>
          {schedule.components.map((c) => {
            const id = `cv-${c.type}-${c.side}`;
            const percent = c.rate_pct !== null;
            return (
              <div key={id} className="grid grid-cols-[1fr_8rem] items-center gap-3">
                <label htmlFor={id} className="text-sm">{typeLabel(c.type)} <span className="text-xs text-ink-soft">({c.side === "BOTH" ? "buy and sell" : c.side.toLowerCase()}, {percent ? "% of value" : "₹ per order"})</span></label>
                <input id={id} inputMode="decimal" value={edits[key(c)] ?? original(c)} onChange={(e) => setEdits((s) => ({ ...s, [key(c)]: e.target.value }))} className={`${inputFull} text-right`} />
              </div>
            );
          })}
        </fieldset>
      </form>
    </Dialog>
  );
}

/** Use today's rates for earlier years too, as an assumption that every run using it reports. */
export function BackfillDialog({ open, onClose, schedule }: { open: boolean; onClose: () => void; schedule: CostSchedule }) {
  const [from, setFrom] = useState("2016-01-01");
  const done = useDone(onClose, "These rates now apply to the earlier period, marked as an assumption.");
  const save = useMutation({ mutationFn: () => api.backfillCostSchedule(schedule.schedule_id, schedule.version, from), onSuccess: done });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Use these rates for earlier history"
      description={`The ${schedule.broker} ${schedule.product.toLowerCase()} rates that start on ${schedule.valid_from} will also be used for every earlier day from the date below, flagged as an assumption on every backtest that relies on it.`}
      footer={
        <>
          <button type="button" onClick={onClose} className={buttonClass("secondary")}>Cancel</button>
          <button type="submit" form="cost-backfill" disabled={save.isPending || !from} className={buttonClass("primary")}>Apply to earlier history</button>
        </>
      }
    >
      <form id="cost-backfill" onSubmit={submit} className="space-y-4">
        {save.isError ? <Alert tone="error">{message(save.error)}</Alert> : null}
        <Field id="bf-from" label="From" hint="If an earlier assumed period already exists, remove it first."><input id="bf-from" type="date" required value={from} onChange={(e) => setFrom(e.target.value)} className={inputFull} /></Field>
      </form>
    </Dialog>
  );
}

/** A new provider starts as a copy of another's structure, with no claim about where its rates come from. */
export function ProviderDialog({ open, onClose, brokers }: { open: boolean; onClose: () => void; brokers: string[] }) {
  const [name, setName] = useState("");
  const [template, setTemplate] = useState(brokers[0] ?? "");
  const [from, setFrom] = useState("");
  const [note, setNote] = useState("");
  const done = useDone(onClose, "Provider added. Enter its real rates with Enter a price change.");
  const save = useMutation({ mutationFn: () => api.addCostProvider({ name, template_broker: template, valid_from: from, note }), onSuccess: done });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Add a provider"
      description="Starts as a copy of another provider's charge structure, marked as unchecked. Then enter the provider's real rates."
      footer={
        <>
          <button type="button" onClick={onClose} className={buttonClass("secondary")}>Cancel</button>
          <button type="submit" form="cost-provider" disabled={save.isPending || !name.trim() || !from} className={buttonClass("primary")}>Add provider</button>
        </>
      }
    >
      <form id="cost-provider" onSubmit={submit} className="space-y-4">
        {save.isError ? <Alert tone="error">{message(save.error)}</Alert> : null}
        <Field id="pv-name" label="Provider name"><input id="pv-name" required maxLength={60} value={name} onChange={(e) => setName(e.target.value)} className={inputFull} /></Field>
        <Field id="pv-template" label="Copy the structure of">
          <select id="pv-template" value={template} onChange={(e) => setTemplate(e.target.value)} className={inputFull}>
            {brokers.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
        </Field>
        <Field id="pv-from" label="Effective from"><input id="pv-from" type="date" required value={from} onChange={(e) => setFrom(e.target.value)} className={inputFull} /></Field>
        <Field id="pv-note" label="Note (optional)"><input id="pv-note" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} className={inputFull} /></Field>
      </form>
    </Dialog>
  );
}
