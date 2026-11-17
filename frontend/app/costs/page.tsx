"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { BackfillDialog, NewVersionDialog, ProviderDialog, typeLabel } from "@/components/costs/Dialogs";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, Skeleton, type Column } from "@/components/ui/DataTable";
import { Field } from "@/components/ui/Field";
import { Panel, StatusPill, Tabs, type Tab } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtMoney } from "@/lib/formatting";
import type { CostPreview, CostSchedule } from "@/lib/schemas";

type Component = CostSchedule["components"][number];
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Could not save. Try again.");
const STATUS: Record<CostSchedule["status"], { text: string; tone: "good" | "warn" | "info" }> = { verified: { text: "Verified", tone: "good" }, extracted_unverified: { text: "Needs checking", tone: "warn" }, assumed_backfill: { text: "Assumed", tone: "info" } };
const rate = (c: Component) => (c.rate_pct !== null ? `${c.rate_pct}% of value` : c.amount !== null ? `₹${c.amount} per order` : "");
const same = (a: CostSchedule, b: CostSchedule | undefined) => b !== undefined && a.schedule_id === b.schedule_id && a.version === b.version;

const componentColumns: Column<Component>[] = [
  { key: "type", header: "Charge", cell: (c) => <span className="font-medium">{typeLabel(c.type)}</span> },
  { key: "side", header: "Applies to", cell: (c) => (c.side === "BOTH" ? "Buy and sell" : c.side === "BUY" ? "Buy only" : "Sell only") },
  { key: "rate", header: "Rate", className: "text-right", cell: (c) => rate(c) },
  { key: "limits", header: "Limits", hideBelow: "sm", className: "text-right", cell: (c) => <span className="text-ink-soft">{[c.minimum ? `min ₹${c.minimum}` : "", c.maximum ? `max ₹${c.maximum}` : ""].filter(Boolean).join(", ")}</span> },
];

/** Try a trade through the calculator: what it would cost on a day, and which schedule (and how reliable) was used. */
function Calculator({ broker }: { broker: string }) {
  const [form, setForm] = useState({ product: "DELIVERY", side: "BUY", qty: "100", price: "1000", day: new Date().toISOString().slice(0, 10) });
  const run = useMutation({ mutationFn: () => api.costPreview({ broker, ...form }) });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run.mutate();
  };
  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));
  const r: CostPreview | undefined = run.data;
  return (
    <Panel title="Try a trade">
      <form onSubmit={submit} className="grid gap-4 p-5 sm:grid-cols-5">
        <Field id="pv-product" label="Product"><select id="pv-product" value={form.product} onChange={(e) => set("product")(e.target.value)} className={inputFull}><option value="DELIVERY">Delivery</option><option value="INTRADAY">Intraday</option></select></Field>
        <Field id="pv-side" label="Action"><select id="pv-side" value={form.side} onChange={(e) => set("side")(e.target.value)} className={inputFull}><option value="BUY">Buy</option><option value="SELL">Sell</option></select></Field>
        <Field id="pv-qty" label="Shares"><input id="pv-qty" inputMode="numeric" required value={form.qty} onChange={(e) => set("qty")(e.target.value)} className={inputFull} /></Field>
        <Field id="pv-price" label="Price (₹)"><input id="pv-price" inputMode="decimal" required value={form.price} onChange={(e) => set("price")(e.target.value)} className={inputFull} /></Field>
        <Field id="pv-day" label="On"><input id="pv-day" type="date" required value={form.day} onChange={(e) => set("day")(e.target.value)} className={inputFull} /></Field>
        <div className="sm:col-span-5"><button type="submit" disabled={run.isPending} className={buttonClass("secondary")}>Work out the charges</button></div>
      </form>
      {run.isError ? <div className="px-5 pb-5"><Alert tone="error">{message(run.error)}</Alert></div> : null}
      {r ? (
        <div className="border-t border-line px-5 py-4" data-testid="preview">
          <p className="text-sm">Trade value ₹{fmtMoney(r.value)} on schedule <span className="font-medium">{r.schedule.id}</span> <StatusPill tone={STATUS[r.schedule.status].tone}>{STATUS[r.schedule.status].text}</StatusPill></p>
          {r.schedule.status !== "verified" ? <p className="mt-1 text-xs text-ink-soft">{r.schedule.status === "assumed_backfill" ? "These are today's rates assumed for this date." : "These rates have not been checked by a person yet."}</p> : null}
          <table className="mt-3 w-full max-w-xl text-sm">
            <tbody>
              {r.lines.map((l) => (
                <tr key={l.type} className="border-t border-line"><td className="py-1.5 pr-3">{typeLabel(l.type)}</td><td className="py-1.5 pr-3 text-xs text-ink-soft">{l.formula}</td><td className="py-1.5 text-right">₹{fmtMoney(l.amount)}</td></tr>
              ))}
              <tr className="border-t border-line font-semibold"><td className="py-1.5" colSpan={2}>Total</td><td className="py-1.5 text-right">₹{fmtMoney(r.total)}</td></tr>
            </tbody>
          </table>
        </div>
      ) : null}
    </Panel>
  );
}

export default function CostsPage() {
  const { can } = useAuth();
  const manage = can("system:settings");
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["costs"], queryFn: api.costSchedules });
  const [chosen, setChosen] = useState<string | null>(null);
  const [product, setProduct] = useState<"DELIVERY" | "INTRADAY">("DELIVERY");
  const [selected, setSelected] = useState<CostSchedule | undefined>();
  const [accepted, setAccepted] = useState<string | null>(null); // the schedule whose assumptions were ticked
  const [dialog, setDialog] = useState<"version" | "backfill" | "provider" | null>(null);
  const all = q.data?.schedules ?? [];
  const brokers = [...new Set(all.map((s) => s.broker))];
  const broker = chosen && brokers.includes(chosen) ? chosen : brokers[0];
  const rows = all.filter((s) => s.broker === broker && s.product === product).sort((a, b) => b.valid_from.localeCompare(a.valid_from));
  const current = rows.find((s) => same(s, selected)) ?? rows[0];
  const done = (text: string) => { void qc.invalidateQueries({ queryKey: ["costs"] }); toast.success(text); };
  const verify = useMutation({ mutationFn: (s: CostSchedule) => api.verifyCostSchedule(s.schedule_id, s.version, s.assumptions.length > 0), onSuccess: () => done("Verified. Your name and the time are recorded.") });
  const remove = useMutation({ mutationFn: (s: CostSchedule) => api.removeCostSchedule(s.schedule_id, s.version), onSuccess: () => done("Removed.") });
  const flagged = rows.filter((s) => s.status !== "verified");
  const tabs: Tab<string>[] = brokers.map((b) => ({ key: b, label: b }));

  const columns: Column<CostSchedule>[] = [
    { key: "from", header: "Effective from", cell: (s) => <button type="button" onClick={() => setSelected(s)} className="font-medium text-brand hover:underline">{s.valid_from}</button> },
    { key: "until", header: "Until", cell: (s) => s.valid_until ?? <span className="text-ink-soft">now</span> },
    { key: "status", header: "Status", cell: (s) => <StatusPill tone={STATUS[s.status].tone}>{STATUS[s.status].text}</StatusPill> },
    { key: "by", header: "Checked by", hideBelow: "sm", cell: (s) => (s.verified_by ? s.verified_by : <span className="text-ink-faint">nobody yet</span>) },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Trading costs"
        subtitle="The charges every backtest and trade pays, by provider and the date they start. Each rate cites where it came from."
        actions={manage && brokers.length > 0 ? <button type="button" onClick={() => setDialog("provider")} className={buttonClass("secondary")}>Add provider</button> : null}
      />
      {q.isError ? <Alert tone="error" title="Could not load the costs">Try again in a moment.</Alert> : null}
      {q.isLoading ? <div role="status" aria-label="Loading the costs"><Skeleton className="h-40 w-full" /></div> : null}
      {q.data && brokers.length === 0 ? <Panel><EmptyState icon="info" title="No cost schedules yet">An administrator loads them with the import script (scripts/costs_import.py).</EmptyState></Panel> : null}
      {broker ? (
        <>
          <Tabs tabs={tabs} value={broker} onChange={(b) => { setChosen(b); setSelected(undefined); }} label="Providers" />
          <Tabs tabs={[{ key: "DELIVERY", label: "Delivery" }, { key: "INTRADAY", label: "Intraday" }]} value={product} onChange={(p) => { setProduct(p); setSelected(undefined); }} label="Product" />
          {flagged.length > 0 ? (
            <Alert tone="warn" title={`${flagged.length} of ${rows.length} schedule${rows.length === 1 ? "" : "s"} not verified`}>
              A backtest or trade that uses a schedule marked Needs checking or Assumed says so in its results. Check the rates against the cited sources, then verify.
            </Alert>
          ) : null}
          <Panel title="Rates over time">
            <DataTable caption="Schedules over time" columns={columns} rows={rows} rowKey={(s) => `${s.schedule_id}|${s.version}`} empty={<EmptyState icon="info" title="No schedule for this product">Add a price change or extend another period.</EmptyState>} />
          </Panel>
          {current ? (
            <Panel title={`${current.valid_from} to ${current.valid_until ?? "now"}`} actions={<StatusPill tone={STATUS[current.status].tone}>{STATUS[current.status].text}</StatusPill>}>
              {current.notes ? <p className="border-b border-line px-5 py-3 text-sm text-ink-soft">{current.notes}</p> : null}
              {current.assumptions.length > 0 && current.status !== "verified" ? (
                <div className="border-b border-line bg-amber-50 px-5 py-3">
                  <h3 className="text-sm font-semibold text-amber-900">What this schedule takes on trust</h3>
                  <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-amber-900" aria-label="Assumptions">
                    {current.assumptions.map((a) => <li key={a}>{a}</li>)}
                  </ul>
                  {manage ? (
                    <label className="mt-2 flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={accepted === current.schedule_id} onChange={(e) => setAccepted(e.target.checked ? current.schedule_id : null)} />
                      I accept these {current.assumptions.length} assumption{current.assumptions.length === 1 ? "" : "s"}
                    </label>
                  ) : null}
                </div>
              ) : null}
              <DataTable caption="Charges in this schedule" columns={componentColumns} rows={current.components} rowKey={(c) => `${c.type}|${c.side}`} empty="No components." />
              <div className="border-t border-line px-5 py-4">
                <h3 className="text-sm font-semibold">Where the rates come from</h3>
                <ul className="mt-2 space-y-2 text-sm" aria-label="Sources">
                  {current.sources.map((s) => (
                    <li key={s.key}>
                      <span className="text-ink-soft">{s.locator}: </span>&ldquo;{s.quote}&rdquo;{" "}
                      {s.url.startsWith("http") ? <a href={s.url} target="_blank" rel="noreferrer" className="text-brand hover:underline">source</a> : <span className="text-xs text-ink-soft">(entered by hand)</span>}
                    </li>
                  ))}
                </ul>
              </div>
              {manage ? (
                <div className="flex flex-wrap items-center gap-2 border-t border-line px-5 py-4">
                  {current.status === "extracted_unverified" ? <ConfirmButton disabled={current.assumptions.length > 0 && accepted !== current.schedule_id} question="I checked every rate against its source" confirmLabel="Verify" onConfirm={() => verify.mutate(current)}>Verify</ConfirmButton> : null}
                  <button type="button" onClick={() => setDialog("version")} className={buttonClass("secondary")}>Enter a price change</button>
                  {current.status !== "assumed_backfill" ? <button type="button" onClick={() => setDialog("backfill")} className={buttonClass("secondary")}>Use for earlier history</button> : null}
                  {current.status !== "verified" ? <ConfirmButton tone="danger" question="Remove this schedule?" confirmLabel="Remove" onConfirm={() => remove.mutate(current)}>Remove</ConfirmButton> : null}
                </div>
              ) : null}
              {verify.isError || remove.isError ? <div className="px-5 pb-4"><Alert tone="error">{message(verify.error ?? remove.error)}</Alert></div> : null}
            </Panel>
          ) : null}
          <Calculator broker={broker} />
          {current && dialog === "version" ? <NewVersionDialog open onClose={() => setDialog(null)} schedule={current} /> : null}
          {current && dialog === "backfill" ? <BackfillDialog open onClose={() => setDialog(null)} schedule={current} /> : null}
          {dialog === "provider" ? <ProviderDialog open onClose={() => setDialog(null)} brokers={brokers} /> : null}
        </>
      ) : null}
    </div>
  );
}
