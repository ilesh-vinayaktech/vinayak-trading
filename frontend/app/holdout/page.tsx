"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { ErrorBox, Loading } from "@/components/status/LoadState";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { ApiError, api } from "@/lib/api/client";
import type { Holdout } from "@/lib/schemas";

type Batch = Holdout["batches"][number];
const columns: Column<Batch>[] = [
  { key: "n", header: "Batch", cell: (b) => `#${b.batch_id}` },
  { key: "state", header: "State", cell: (b) => <StatusPill tone={b.state === "CONSUMED" ? "good" : b.state === "EVALUATION_FAILED" ? "bad" : "neutral"}>{b.state}</StatusPill> },
  { key: "c", header: "Strategies", cell: (b) => (b.members.length ? b.members.join(", ") : b.candidates) },
  { key: "r", header: "Read the holdout", cell: (b) => (b.first_read ? "Yes: slots used for good" : "Not yet") },
  { key: "f", header: "Frozen", hideBelow: "sm", cell: (b) => (b.frozen_at ? b.frozen_at.replace("T", " ").slice(0, 16) : "-") },
];

const GATES: Record<string, string> = { holdout_sharpe: "Sharpe", holdout_drawdown: "Drawdown vs index", holdout_beats_benchmark: "Beats the index" };
const verdictTone = (v: string) => (v === "PASS" ? "good" : v === "FAIL" ? "bad" : "neutral");

/** The holdout ledger, for the owner alone: how many of the 30 lifetime slots are used, the batches so far, and the strategies you can submit. Never a verdict or a figure. */
export default function HoldoutPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["holdout"], queryFn: api.holdout });
  const [picked, setPicked] = useState<string[]>([]);
  const [declaration, setDeclaration] = useState("");
  const submit = useMutation({
    mutationFn: () => api.submitHoldout(picked, declaration.trim()),
    onSuccess: (r) => {
      setPicked([]);
      void qc.invalidateQueries({ queryKey: ["holdout"] });
      toast.success(`Batch ${r.batch_id} frozen. Its slots are reserved and its seeds are committed.`);
    },
  });
  if (q.isLoading) return <Loading what="the holdout ledger" />;
  if (q.isError || !q.data) return <ErrorBox error={q.error} what="the holdout ledger" />;
  const d = q.data;
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
      {d.results.length ? (
        <Panel title="Outer holdout results (2025-2026)">
          <div className="space-y-3 text-sm" data-testid="results">
            {d.results.map((r) => (
              <div key={r.name} className="flex flex-wrap items-center gap-2">
                <span className="w-64 font-medium">{r.name}</span>
                <StatusPill tone={verdictTone(r.overall)}>{r.overall === "INCOMPLETE" ? "NOT COMPLETE" : r.overall}</StatusPill>
                {r.checks.map((c) => (
                  <span key={c.gate} className="text-ink-soft">
                    {GATES[c.gate] ?? c.gate}: <strong>{c.verdict === "INSUFFICIENT_EVIDENCE" ? "no evidence" : c.verdict}</strong>
                    {c.later ? " (completed later)" : ""}
                  </span>
                ))}
              </div>
            ))}
            {d.results.some((r) => r.checks.some((c) => c.later)) ? (
              <Alert tone="info">
                &quot;Completed later&quot; checks had no evidence at evaluation (the index lacked a day) and were completed afterwards with the same code and seeds. They are information only: the promotion path still reads the original verdicts.
              </Alert>
            ) : null}
          </div>
        </Panel>
      ) : null}
      <Panel title="Submit strategies to the outer holdout">
        {d.eligible.length === 0 ? (
          <p className="text-sm text-ink-soft">No strategy is waiting: each one needs a passed development verdict from a clean commit, and must not have used a slot yet.</p>
        ) : (
          <div className="space-y-3 text-sm" data-testid="eligible">
            <ul className="space-y-1">
              {d.eligible.map((e) => (
                <li key={e.candidate_id}>
                  <label className="flex flex-wrap items-center gap-2">
                    <input type="checkbox" checked={picked.includes(e.candidate_id)} onChange={() => setPicked((p) => (p.includes(e.candidate_id) ? p.filter((x) => x !== e.candidate_id) : [...p, e.candidate_id]))} />
                    <span className="font-medium">{e.candidate_id}</span>
                    {e.inner === null ? (
                      <span className="text-ink-soft">inner holdout (2023-2024) not run</span>
                    ) : (
                      <StatusPill tone={e.inner.passed ? "good" : "neutral"}>inner holdout {e.inner.passed ? "passed" : "not passed"}</StatusPill>
                    )}
                    {e.inner?.sharpe != null && e.inner.index_sharpe != null ? <span className="text-ink-soft">Sharpe {e.inner.sharpe.toFixed(2)} vs index {e.inner.index_sharpe.toFixed(2)}</span> : null}
                  </label>
                </li>
              ))}
            </ul>
            <div>
              <label htmlFor="declaration" className="block text-xs font-medium text-ink-soft">
                One line: this idea was not built from 2025-2026 results (including earlier verdicts)
              </label>
              <input id="declaration" className={inputFull} value={declaration} onChange={(e) => setDeclaration(e.target.value)} maxLength={300} />
            </div>
            <ConfirmButton
              question={`Submit ${picked.length} strateg${picked.length === 1 ? "y" : "ies"}? This reserves ${picked.length} of ${d.left} slots and commits the seeds. It cannot be undone.`}
              confirmLabel="Submit"
              disabled={picked.length === 0 || picked.length > d.left || declaration.trim() === "" || submit.isPending}
              onConfirm={() => submit.mutate()}
            >
              Submit {picked.length || ""} to the outer holdout
            </ConfirmButton>
            {submit.error ? <Alert tone="error">{submit.error instanceof ApiError ? submit.error.message : "Could not submit."}</Alert> : null}
          </div>
        )}
        {d.batches.some((b) => b.state === "FROZEN") ? (
          <Alert tone="info">
            A frozen batch is ready. Evaluating it reads 2025-2026 once and cannot be undone: run <code>research_holdout.py evaluate --batch N --yes</code> from the terminal.
          </Alert>
        ) : null}
      </Panel>
    </div>
  );
}
