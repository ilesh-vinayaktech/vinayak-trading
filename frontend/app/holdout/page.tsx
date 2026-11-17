"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/PageHeader";
import { ErrorBox, Loading } from "@/components/status/LoadState";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { useToast } from "@/components/ui/Toast";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { ApiError, api } from "@/lib/api/client";
import type { Holdout } from "@/lib/schemas";

type Batch = Holdout["batches"][number];
const columns: Column<Batch>[] = [
  { key: "n", header: "Batch", cell: (b) => `#${b.batch_id}` },
  { key: "state", header: "State", cell: (b) => <StatusPill tone={b.state === "CONSUMED" ? "good" : b.state === "EVALUATION_FAILED" ? "bad" : "neutral"}>{b.state}</StatusPill> },
  { key: "c", header: "Strategies", cell: (b) => b.candidates },
  { key: "r", header: "Read the holdout", cell: (b) => (b.first_read ? "Yes: slots used for good" : "Not yet") },
  { key: "f", header: "Frozen", hideBelow: "sm", cell: (b) => (b.frozen_at ? b.frozen_at.replace("T", " ").slice(0, 16) : "-") },
];

/** The holdout ledger, for the owner alone: how many of the 30 lifetime slots are used, the batches so far, and the plan for the next one. Never a verdict or a figure. */
export default function HoldoutPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["holdout"], queryFn: api.holdout });
  const freeze = useMutation({
    mutationFn: (cutoffId: number) => api.freezeHoldoutBatch(cutoffId),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["holdout"] });
      toast.success(`Batch ${r.batch_id} frozen. Its slots are reserved and its seeds are committed.`);
    },
  });
  if (q.isLoading) return <Loading what="the holdout ledger" />;
  if (q.isError || !q.data) return <ErrorBox error={q.error} what="the holdout ledger" />;
  const d = q.data;
  const plan = d.cutoff?.plan ?? null;
  return (
    <div className="space-y-6">
      <PageHeader title="Holdout ledger" subtitle="Every strategy tested on 2025-2026 uses one of 30 lifetime slots. Only you can see this page." />
      {d.warnings.map((w) => (
        <Alert key={w} tone="warn">
          {w}
        </Alert>
      ))}
      <Panel title="Slots">
        <p className="text-sm" data-testid="slots">
          <strong>{d.consumed}</strong> used, <strong>{d.reserved}</strong> reserved, <strong>{d.left}</strong> left of {d.budget}. Previously tested strategies: <strong>{d.previously_tested}</strong>.
        </p>
      </Panel>
      <Panel title="Batches">
        <DataTable caption="Holdout batches" columns={columns} rows={d.batches} rowKey={(b) => String(b.batch_id)} empty={<EmptyState title="No batch yet">The first batch is frozen after the audit is signed.</EmptyState>} />
      </Panel>
      <Panel title="Next batch">
        {d.cutoff === null || plan === null ? (
          <p className="text-sm text-ink-soft">The cutoff has not fired yet: it fires by itself when the last study of the round ends.</p>
        ) : (
          <div className="space-y-3 text-sm" data-testid="plan">
            <p>
              Cutoff {d.cutoff.cutoff_id} fired {d.cutoff.fired_at.replace("T", " ").slice(0, 16)}. Audit {d.audit_signed ? "signed" : "not signed"}.
            </p>
            <p>
              In the batch ({plan.members.length}): {plan.members.length ? plan.members.join(", ") : "none"}.
              {plan.carry_over.length ? ` Carried over to the next cutoff: ${plan.carry_over.join(", ")}.` : ""}
            </p>
            {Object.keys(plan.excluded).length ? (
              <ul className="list-disc pl-5 text-ink-soft">
                {Object.entries(plan.excluded).map(([id, why]) => (
                  <li key={id}>
                    {id} excluded (ineligible): {why}
                  </li>
                ))}
              </ul>
            ) : null}
            {plan.problems.map((p) => (
              <Alert key={p} tone="info">
                {p}
              </Alert>
            ))}
            <ConfirmButton
              question={`Freeze this batch? It reserves ${plan.members.length} of ${d.left} slots for good and commits the seeds. It cannot be undone.`}
              confirmLabel="Freeze the batch"
              disabled={!plan.can_freeze || freeze.isPending}
              onConfirm={() => freeze.mutate(d.cutoff!.cutoff_id)}
            >
              Freeze the batch
            </ConfirmButton>
            {freeze.error ? <Alert tone="error">{freeze.error instanceof ApiError ? freeze.error.message : "Could not freeze."}</Alert> : null}
          </div>
        )}
      </Panel>
    </div>
  );
}
