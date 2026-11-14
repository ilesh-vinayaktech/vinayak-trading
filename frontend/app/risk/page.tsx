"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { ErrorBox, Loading } from "@/components/status/LoadState";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Field } from "@/components/ui/Field";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { ApiError, api } from "@/lib/api/client";
import type { RiskState, SwitchAction } from "@/lib/schemas";

type Event = RiskState["events"][number];
const TONE = { RUNNING: "good", PAUSE: "warn", CANCEL: "bad", FLATTEN: "bad" } as const;
const MEANING: Record<string, string> = {
  RUNNING: "Orders can be proposed and approved as usual.",
  PAUSE: "No new orders: proposals are skipped and approvals are refused. Orders already approved can still fill.",
  CANCEL: "No new orders, and approved orders that have not filled are cancelled.",
  FLATTEN: "Everything CANCEL does, and closing the positions was requested. On paper, closing them is still your decision.",
};
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Could not save. Try again.");

const columns: Column<Event>[] = [
  { key: "ts", header: "When", cell: (e) => e.ts.replace("T", " ").slice(0, 16) },
  { key: "scope", header: "Applies to", cell: (e) => (e.scope === null ? "Everyone" : e.scope) },
  { key: "mode", header: "Became", cell: (e) => <StatusPill tone={TONE[e.mode as keyof typeof TONE] ?? "neutral"}>{e.mode}</StatusPill> },
  { key: "by", header: "By", hideBelow: "sm", cell: (e) => e.by },
  { key: "reason", header: "Why", cell: (e) => <span className="text-ink-soft">{e.reason}</span> },
];

/** Pause, cancel, resume or flatten: the reason is required and stored with who did it. */
function Controls({ scope, label }: { scope: "own" | "global"; label: string }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const run = useMutation({
    mutationFn: (v: { action: SwitchAction; override: boolean }) => api.riskSwitch(scope, v.action, reason, v.override),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["risk"] });
      setReason("");
      toast.success(`${label}: now ${r.effective}`);
    },
  });
  const need = reason.trim() === "";
  const go = (action: SwitchAction, override = false) => () => run.mutate({ action, override });
  return (
    <div className="space-y-3">
      <Field id={`reason-${scope}`} label={`Why (${label})`} hint="Required. Stored with your name.">
        <input id={`reason-${scope}`} className={inputFull} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} />
      </Field>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={buttonClass("secondary")} disabled={need || run.isPending} onClick={go("pause")}>
          Pause
        </button>
        <ConfirmButton question="Cancel every approved order that has not filled?" confirmLabel="Cancel orders" onConfirm={go("cancel")} disabled={need || run.isPending}>
          Cancel open orders
        </ConfirmButton>
        <button type="button" className={buttonClass("primary")} disabled={need || run.isPending} onClick={go("resume")}>
          Resume
        </button>
        <ConfirmButton question="Flatten is an emergency step. Record it?" confirmLabel="Flatten (emergency)" tone="danger" onConfirm={go("flatten", true)} disabled={need || run.isPending}>
          Flatten
        </ConfirmButton>
      </div>
      {run.error ? <Alert tone="error">{message(run.error)}</Alert> : null}
    </div>
  );
}

function Limits({ state }: { state: RiskState }) {
  const qc = useQueryClient();
  const toast = useToast();
  const current = JSON.stringify(state.limits ?? {}, null, 2);
  const [text, setText] = useState(current);
  useEffect(() => setText(current), [current]);
  const save = useMutation({
    mutationFn: () => api.setRiskLimits(JSON.parse(text) as Record<string, unknown>),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["risk"] });
      toast.success("Limits saved");
    },
  });
  const invalid = (() => {
    try {
      const v: unknown = JSON.parse(text);
      return typeof v === "object" && v !== null && !Array.isArray(v) ? null : "Limits must be a JSON object.";
    } catch {
      return "That is not valid JSON.";
    }
  })();
  return (
    <Panel title="Limits for your paper account">
      <div className="space-y-3 p-4">
        <p className="text-sm text-ink-soft">Checked when you approve an order: a breach refuses the approval and the order stays pending. A limit left out is not checked. Values are at cost on paper.</p>
        <Field id="limits-json" label="Limits (JSON)" error={invalid}>
          <textarea id="limits-json" className={`${inputFull} h-40 font-mono text-xs`} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
        </Field>
        <div className="flex items-center gap-2">
          <button type="button" className={buttonClass("primary")} disabled={invalid !== null || save.isPending || text === current} onClick={() => save.mutate()}>
            Save limits
          </button>
          <span className="text-xs text-ink-soft">An empty object {"{}"} removes every limit.</span>
        </div>
        {save.error ? <Alert tone="error">{message(save.error)}</Alert> : null}
        <details className="text-sm">
          <summary className="cursor-pointer font-medium">What can be limited</summary>
          <ul className="mt-2 space-y-1 text-ink-soft">
            {state.limit_keys.map((k) => (
              <li key={k.key}>
                <code className="text-xs">{k.key}</code> ({k.kind}): {k.help}
              </li>
            ))}
          </ul>
        </details>
      </div>
    </Panel>
  );
}

export default function RiskPage() {
  const q = useQuery({ queryKey: ["risk"], queryFn: api.riskState });
  const d = q.data;
  return (
    <div className="space-y-4">
      <PageHeader title="Risk and kill switch" subtitle="Stop new orders, cancel the open ones, or record an emergency flatten. Every change is stored with who made it and why. UNVALIDATED paper trading: nothing here places a real order." />
      {q.isLoading ? <Loading what="the kill switch" /> : null}
      {q.error ? <ErrorBox error={q.error} what="the kill switch" /> : null}
      {d ? (
        <>
          <Panel title="Now">
            <div className="space-y-3 p-4">
              <p className="flex flex-wrap items-center gap-2 text-sm">
                <StatusPill tone={TONE[d.switch.effective]}>{d.switch.effective}</StatusPill>
                <span>{MEANING[d.switch.effective]}</span>
              </p>
              <dl className="grid gap-2 text-sm sm:grid-cols-2">
                {[
                  ["Everyone", d.switch.global],
                  ["Your strategy", d.switch.strategy],
                ].map(([name, s]) => (
                  <div key={String(name)}>
                    <dt className="text-ink-soft">{String(name)}</dt>
                    <dd>{s ? `${(s as NonNullable<typeof d.switch.global>).mode} by ${(s as NonNullable<typeof d.switch.global>).by}: ${(s as NonNullable<typeof d.switch.global>).reason}` : "never changed"}</dd>
                  </div>
                ))}
              </dl>
            </div>
          </Panel>
          {d.account ? (
            <Panel title={`Your strategy (${d.account.strategy_id})`}>
              <div className="p-4">
                <Controls scope="own" label="your strategy" />
              </div>
            </Panel>
          ) : (
            <Panel>
              <EmptyState icon="info" title="No paper account yet">
                Create one on the Paper trading page to switch your own strategy and set limits.
              </EmptyState>
            </Panel>
          )}
          {d.can_global ? (
            <Panel title="Everyone (operators)">
              <div className="p-4">
                <Controls scope="global" label="everyone" />
              </div>
            </Panel>
          ) : null}
          {d.account ? <Limits state={d} /> : null}
          <Panel title="History">
            <DataTable caption="Kill switch changes" columns={columns} rows={d.events} rowKey={(e) => `${e.ts}-${e.scope}-${e.mode}`} empty={<EmptyState icon="info" title="Nothing yet">The switch has never been used.</EmptyState>} />
          </Panel>
        </>
      ) : null}
    </div>
  );
}
