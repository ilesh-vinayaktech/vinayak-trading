"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { STAGE_LABEL, StageDialog } from "@/components/strategies/StageDialog";
import { StrategyDialog } from "@/components/strategies/StrategyDialog";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { ApiError, api } from "@/lib/api/client";
import type { Strategies, StrategyConfig } from "@/lib/schemas";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");
const rules = (s: StrategyConfig) => {
  const p = s.params;
  return s.screen
    ? `Screener: ${s.screen.screen.conditions.length} condition${s.screen.screen.conditions.length === 1 ? "" : "s"}, ranked by ${s.screen.screen.sort}, up to ${p.max_positions} stocks`
    : `Uptrend ${p.trend_sma} days · buy RSI < ${p.entry_rsi} · sell RSI > ${p.exit_rsi} · up to ${p.max_positions} stocks`;
};

export default function StrategiesPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  const [editing, setEditing] = useState<StrategyConfig | "new" | null>(null);
  const [staging, setStaging] = useState<StrategyConfig | null>(null);
  const done = (text: string) => {
    void qc.invalidateQueries({ queryKey: ["strategies"] });
    void qc.invalidateQueries({ queryKey: ["paper"] });
    toast.success(text);
  };
  const use = useMutation({ mutationFn: (id: string) => api.useStrategy(id), onSuccess: () => done("Your paper account now uses this strategy.") });
  const remove = useMutation({ mutationFn: (id: string) => api.deleteStrategy(id), onSuccess: () => done("Strategy deleted.") });
  const options = q.data?.options as Strategies["options"] | undefined;
  const err = use.error ?? remove.error;
  const columns: Column<StrategyConfig>[] = [
    { key: "name", header: "Name", cell: (s) => <span className="font-medium">{s.name}</span> },
    { key: "on", header: "Trades", cell: (s) => s.screen ? `${s.screen.segments.join(" + ")} caps` : `${options?.universes.find((u) => u.key === s.universe)?.label ?? s.universe}, ${s.max_instruments ? `top ${s.max_instruments} stocks` : "all stocks"}` },
    { key: "rules", header: "Rules", hideBelow: "md", cell: (s) => <span className="text-ink-soft">{rules(s)}</span> },
    { key: "stage", header: "Stage", cell: (s) => <StatusPill tone={s.stage === "LIVE" ? "bad" : s.stage === "PAPER" ? "info" : "neutral"}>{STAGE_LABEL[s.stage]}</StatusPill> },
    { key: "used", header: "Paper account", cell: (s) => (s.in_use ? <StatusPill tone="good">In use</StatusPill> : <span className="text-ink-soft">Not used</span>) },
    {
      key: "actions",
      header: "",
      className: "text-right",
      cell: (s) => (
        <span className="inline-flex flex-wrap justify-end gap-2">
          {!s.screen ? <button type="button" onClick={() => setEditing(s)} className={buttonClass("secondary")}>Change</button> : null}
          <button type="button" onClick={() => setStaging(s)} className={buttonClass("secondary")}>Stage</button>
          {!s.in_use ? <button type="button" onClick={() => use.mutate(s.config_id)} disabled={use.isPending} className={buttonClass("secondary")}>Use for paper trading</button> : null}
          {!s.in_use ? <ConfirmButton tone="danger" question={`Delete ${s.name}?`} confirmLabel="Delete" onConfirm={() => remove.mutate(s.config_id)}>Delete</ConfirmButton> : null}
        </span>
      ),
    },
  ];
  return (
    <div className="space-y-6">
      <PageHeader
        title="Strategies"
        subtitle="Save named sets of choices: which stocks, how many, and the rules. Your paper account runs the one you pick."
        actions={options ? <button type="button" onClick={() => setEditing("new")} className={buttonClass("primary")}>New strategy</button> : undefined}
      />
      <Alert tone="warn" title="Unvalidated research">
        None of these strategies has passed validation. They show whether the plumbing works, not that a strategy makes money.
      </Alert>
      {q.isError ? <Alert tone="error" title="Could not load your strategies">Try again in a moment.</Alert> : null}
      {err ? <Alert tone="error">{message(err)}</Alert> : null}
      <Panel title="Your strategies">
        <DataTable
          caption="Your strategies"
          columns={columns}
          rows={q.data?.strategies}
          rowKey={(s) => s.config_id}
          loading={q.isLoading}
          empty={<EmptyState icon="flask" title="No strategies yet">Create one to choose the stocks and rules, then give it to your paper account.</EmptyState>}
        />
      </Panel>
      {staging ? <StageDialog key={staging.config_id} strategy={staging} onClose={() => setStaging(null)} /> : null}
      {editing && options ? <StrategyDialog key={editing === "new" ? "new" : editing.config_id} open onClose={() => setEditing(null)} options={options} strategy={editing === "new" ? undefined : editing} /> : null}
    </div>
  );
}
