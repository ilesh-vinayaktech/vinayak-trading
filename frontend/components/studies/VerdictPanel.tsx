"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { NextSteps } from "@/components/studies/NextSteps";
import { Progress, StopButton } from "@/components/studies/Progress";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Panel, RelativeTime, StatusPill } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import type { StudyVerdict } from "@/lib/schemas";
import { GATE_LABELS, GATE_STATE_LABEL, GATE_STATE_TONE, gateRule, gateState, gateValue } from "@/lib/studies";

type Report = NonNullable<StudyVerdict["report"]>;
type Gate = Report["gates"][number];
type Window = Report["refs"]["windows"][number];

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");
const settings = (p: Record<string, number>) => Object.entries(p).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${k} ${v}`).join(" · ");

/** The pass/fail decision over the finished trials: every gate, the figure it judged, and the walk-forward windows behind it. */
export function VerdictPanel({ id }: { id: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useAuth();
  const q = useQuery({
    queryKey: ["study-verdict", id],
    queryFn: () => api.studyVerdict(id),
    refetchInterval: (query) => ([query.state.data?.run?.status, query.state.data?.holdout_run?.status].some((s) => s === "QUEUED" || s === "RUNNING") ? 3000 : false),
  });
  const start = useMutation({
    mutationFn: () => api.requestStudyVerdict(id),
    onSuccess: () => { toast.success("Judging queued."); void qc.invalidateQueries({ queryKey: ["study-verdict", id] }); },
  });
  const holdout = useMutation({
    mutationFn: () => api.requestStudyHoldout(id),
    onSuccess: () => { toast.success("Opening the holdout."); void qc.invalidateQueries({ queryKey: ["study-verdict", id] }); },
  });
  const v = q.data;
  const run = v?.run ?? null;
  const active = run !== null && ["QUEUED", "RUNNING"].includes(run.status);
  const ready = v !== undefined && v.trials_planned > 0 && v.trials_done >= v.trials_planned;
  const r = v?.report ?? null;
  const gateCols: Column<Gate>[] = [
    { key: "ok", header: "", cell: (g) => <StatusPill tone={GATE_STATE_TONE[gateState(g)]}>{GATE_STATE_LABEL[gateState(g)]}</StatusPill> },
    { key: "n", header: "Check", cell: (g) => GATE_LABELS[g.name] ?? g.name },
    { key: "v", header: "Result", className: "text-right", cell: (g) => (r ? gateValue(g.name, r.evidence) : "") },
    { key: "d", header: "Why", hideBelow: "md", cell: (g) => { const rule = r ? gateRule(g.name, r.evidence) : null; return rule ? <span className="text-xs text-ink-soft" data-testid="gate-rule">{rule}{g.passed ? "" : ` ${g.detail}`}</span> : g.passed ? "" : <span className="text-xs text-ink-soft">{g.detail}</span>; } },
  ];
  const unmeasured = r ? r.gates.filter((g) => gateState(g) === "INSUFFICIENT_EVIDENCE").length : 0;
  const winCols: Column<Window>[] = [
    { key: "tr", header: "Chose settings on", hideBelow: "md", cell: (w) => <span className="whitespace-nowrap text-xs">{w.train_from} to {w.train_to}</span> },
    { key: "te", header: "Judged on", cell: (w) => <span className="whitespace-nowrap text-xs">{w.test_from} to {w.test_to}</span> },
    { key: "c", header: "Settings chosen", cell: (w) => <span className="text-xs">{settings(w.chosen)}</span> },
    { key: "s", header: "Sharpe", className: "text-right", cell: (w) => (w.sharpe === null ? "-" : w.sharpe.toFixed(2)) },
    { key: "r", header: "Return", className: "text-right", cell: (w) => <span className={w.return < 0 ? "text-red-600" : "text-emerald-700"}>{(w.return * 100).toFixed(1)}%</span> },
  ];
  return (
    <Panel
      title="Pass or fail"
      actions={can("strategy:own") && !active ? <button type="button" onClick={() => start.mutate()} disabled={start.isPending || !ready} className={buttonClass("primary")}>{r ? "Judge again" : "Judge the results"}</button> : undefined}
    >
      <div className="space-y-4 px-5 py-4">
        <p className="text-sm text-ink-soft">
          Once every combination has run, the results are judged against the thresholds fixed when the study was registered: walk-forward testing, deflated Sharpe,
          overfitting probability, stability, costs, capacity and concentration. A check with no evidence fails. The holdout is not read.
        </p>
        {q.isError ? <Alert tone="error">Could not load the verdict.</Alert> : null}
        {start.error ? <Alert tone="error">{message(start.error)}</Alert> : null}
        {v && !ready && !r ? <Alert tone="info">{v.trials_done} of {v.trials_planned} combinations have finished. Run all the trials first.</Alert> : null}
        {run && active ? (
          <div className="flex flex-wrap items-center gap-2" aria-label="Verdict status">
            <StatusPill tone={run.status === "RUNNING" ? "info" : "neutral"}>{run.status === "RUNNING" ? "Judging" : "Waiting for a worker"}</StatusPill>
            {run.current ? <span className="text-xs text-ink-soft">now: re-running at {run.current}</span> : null}
            {can("strategy:own") ? <StopButton run={run} queryKey={["study-verdict", id]} /> : null}
          </div>
        ) : null}
        {run && active ? (
          <div aria-label="Verdict progress"><Progress run={run} unit="stress runs" stepUnit="day" /></div>
        ) : null}
        {run?.status === "FAILED" && run.error ? <Alert tone="error" title="The judging stopped">{run.error}</Alert> : null}
        {r ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <StatusPill tone={r.passed ? "good" : "bad"}>{r.passed ? "Passed every check" : `Failed ${r.gates.filter((g) => !g.passed).length} of ${r.gates.length} checks`}</StatusPill>
              {unmeasured > 0 ? <StatusPill tone="warn">{unmeasured} without evidence</StatusPill> : null}
              <span className="text-xs text-ink-soft">Thresholds {r.thresholds_status} · {r.n_trials} combinations tried across the whole research family · <RelativeTime iso={r.created_at} /></span>
            </div>
            <p className="text-xs text-ink-soft">
              Best settings over the whole research window: <strong>{settings(r.refs.chosen)}</strong>.{" "}
              <Link href={`/research/backtests/${r.run_id}`} className="text-brand hover:underline">Open that run</Link> ·{" "}
              <Link href={`/research/backtests/${r.refs.cost_2x_run}`} className="text-brand hover:underline">double-cost run</Link> ·{" "}
              <Link href={`/research/backtests/${r.refs.capital_run}`} className="text-brand hover:underline">{r.refs.capital_multiple}x capital run</Link>.
            </p>
            {r.refs.benchmark_note ? <Alert tone="warn" title={`No comparison with ${r.refs.benchmark}`}>{r.refs.benchmark_note}. The checks that need it fail until it is fixed.</Alert> : null}
            <DataTable caption="The checks" columns={gateCols} rows={r.gates} rowKey={(g) => g.name} empty={null} />
            <div>
              <h3 className="mb-1 text-sm font-medium">Walk-forward windows</h3>
              <p className="mb-2 text-xs text-ink-soft">In each window the best settings on the earlier days ({r.refs.walk_forward.train}) were picked, then judged only on the next {r.refs.walk_forward.test} days, after a gap of {r.refs.walk_forward.embargo}. Only those judged days count.</p>
              <DataTable caption="Walk-forward windows" columns={winCols} rows={r.refs.windows} rowKey={(w) => w.test_from} empty={null} />
            </div>
            <HoldoutSection id={id} h={v?.holdout ?? null} run={v?.holdout_run ?? null} passed={r.passed} canOpen={can("strategy:own")} opening={holdout.isPending} error={holdout.error} onOpen={() => holdout.mutate()} />
            {r.passed ? <NextSteps id={id} inner={v?.holdout ?? null} /> : null}
          </div>
        ) : !active && !run ? <EmptyState icon="flask" title="Not judged yet">When every combination has run, judge the results to see which checks pass.</EmptyState> : null}
      </div>
    </Panel>
  );
}

const holdoutValue = (name: string, e: Record<string, number | null>) => {
  const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
  if (name === "holdout_sharpe") return e.sharpe == null ? "no evidence" : e.sharpe.toFixed(2);
  if (name === "holdout_drawdown") return e.max_drawdown == null ? "no evidence" : pct(Math.abs(e.max_drawdown));
  return e.sharpe == null || e.benchmark_sharpe == null ? "no evidence" : `${e.sharpe.toFixed(2)} vs index ${e.benchmark_sharpe.toFixed(2)}`;
};

/** The final test: the chosen settings on days the study never saw. It can be opened once, and only after a verdict that passed. */
function HoldoutSection({ id, h, run, passed, canOpen, opening, error, onOpen }: { id: number; h: StudyVerdict["holdout"]; run: StudyVerdict["holdout_run"]; passed: boolean; canOpen: boolean; opening: boolean; error: unknown; onOpen: () => void }) {
  const active = run !== null && ["QUEUED", "RUNNING"].includes(run.status);
  const cols: Column<NonNullable<StudyVerdict["holdout"]>["gates"][number]>[] = [
    { key: "ok", header: "", cell: (g) => <StatusPill tone={GATE_STATE_TONE[gateState(g)]}>{GATE_STATE_LABEL[gateState(g)]}</StatusPill> },
    { key: "n", header: "Check", cell: (g) => GATE_LABELS[g.name] ?? g.name },
    { key: "v", header: "Result", className: "text-right", cell: (g) => (h ? holdoutValue(g.name, h.evidence) : "") },
    { key: "d", header: "Why", hideBelow: "md", cell: (g) => (g.passed ? "" : <span className="text-xs text-ink-soft">{g.detail}</span>) },
  ];
  return (
    <div className="space-y-3 border-t border-line pt-4">
      <h3 className="text-sm font-medium">The inner holdout: the study&apos;s own last test</h3>
      <p className="text-xs text-ink-soft">The chosen settings are run once on the last stretch of dates this study did not tune on (2023-2024). Those days were already seen when the features were chosen, so a pass here is a sanity check, not proof. It can be done a single time, and only after a verdict that passed every check. The truly sealed test is the global holdout, 2025 onward, opened separately.</p>
      {error ? <Alert tone="error">{message(error)}</Alert> : null}
      {h ? (
        <div className="space-y-2">
          <StatusPill tone={h.passed ? "good" : "bad"}>{h.passed ? "Passed the holdout" : "Failed the holdout"}</StatusPill>
          <p className="text-xs text-ink-soft">{h.refs.window[0]} to {h.refs.window[1]} · {h.evidence.days} days · return {h.evidence.total_return == null ? "-" : `${(h.evidence.total_return * 100).toFixed(1)}%`} · <Link href={`/research/backtests/${h.run_id}`} className="text-brand hover:underline">open the run</Link></p>
          {h.refs.benchmark_note ? <Alert tone="warn" title={`No comparison with ${h.refs.benchmark}`}>{h.refs.benchmark_note}.</Alert> : null}
          <DataTable caption="Holdout checks" columns={cols} rows={h.gates} rowKey={(g) => g.name} empty={null} />
        </div>
      ) : active ? (
        <div className="space-y-2">
          <StatusPill tone="info">{run?.status === "RUNNING" ? "Running the holdout" : "Waiting for a worker"}</StatusPill>
          {run ? <Progress run={run} unit="run" stepUnit="day" /> : null}
          {run && canOpen ? <StopButton run={run} queryKey={["study-verdict", id]} /> : null}
        </div>
      ) : (
        <div className="space-y-2">
          {run?.status === "FAILED" && run.error ? <Alert tone="error" title="The holdout did not run">{run.error}</Alert> : null}
          {passed ? (
            canOpen ? <ConfirmButton question="Open the holdout? It can only be done once." confirmLabel="Open it" onConfirm={onOpen} disabled={opening}>Open the holdout</ConfirmButton> : <p className="text-xs text-ink-soft">Someone who may run strategies can open it.</p>
          ) : (
            <p className="text-xs text-ink-soft">Not available: the research verdict has not passed every check, so the holdout stays unopened.</p>
          )}
        </div>
      )}
    </div>
  );
}
