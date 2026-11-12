"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Progress, StopButton } from "@/components/studies/Progress";
import Link from "next/link";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Panel, RelativeTime, StatusPill } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import type { StudyTrial } from "@/lib/schemas";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "-" : `${(v * 100).toFixed(1)}%`);
const num = (v: number | null | undefined, d = 2) => (v === null || v === undefined ? "-" : v.toFixed(d));
const TONE = { QUEUED: "neutral", RUNNING: "info", DONE: "good", FAILED: "bad", CANCELLED: "warn" } as const;
const LABEL = { QUEUED: "Waiting for a worker", RUNNING: "Running", DONE: "Finished", FAILED: "Stopped with an error", CANCELLED: "Cancelled" } as const;
const params = (t: StudyTrial) => Object.entries(t.params).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => `${k} ${v}`).join(" · ");

const columns: Column<StudyTrial>[] = [
  { key: "p", header: "Settings", cell: (t) => <span className="text-xs">{params(t)}</span> },
  { key: "st", header: "Result", cell: (t) => (t.status === "DONE" ? <StatusPill tone="good">Done</StatusPill> : <span title={t.error ?? ""}><StatusPill tone="bad">Failed</StatusPill></span>) },
  { key: "sh", header: "Sharpe", className: "text-right", cell: (t) => num(t.metrics?.sharpe) },
  { key: "cagr", header: "Yearly return", className: "text-right", cell: (t) => pct(t.metrics?.cagr) },
  { key: "dd", header: "Worst drop", className: "text-right", hideBelow: "sm", cell: (t) => pct(t.metrics?.max_drawdown) },
  { key: "tr", header: "Trades", className: "text-right", hideBelow: "md", cell: (t) => num(t.metrics?.trades, 0) },
  { key: "co", header: "Costs paid (₹)", className: "text-right", hideBelow: "lg", cell: (t) => num(t.metrics?.costs, 0) },
  { key: "rep", header: "", className: "text-right", cell: (t) => (t.backtest_run === null ? null : <Link href={`/research/backtests/${t.backtest_run}`} className="text-brand hover:underline">Trades and P&L</Link>) },
  { key: "sec", header: "Took", className: "text-right", hideBelow: "lg", cell: (t) => (t.seconds === null ? "-" : `${Math.round(t.seconds)} s`) },
];

const SORTS = {
  settings: { label: "Settings", by: null },
  sharpe: { label: "Sharpe, best first", by: (t: StudyTrial) => t.metrics?.sharpe },
  cagr: { label: "Yearly return, best first", by: (t: StudyTrial) => t.metrics?.cagr },
  drawdown: { label: "Worst drop, smallest first", by: (t: StudyTrial) => t.metrics?.max_drawdown },
} as const;
type SortKey = keyof typeof SORTS;

/** Failed or undefined results sink to the bottom; ties keep the settings order. */
function sorted(rows: StudyTrial[] | undefined, key: SortKey): StudyTrial[] | undefined {
  const by = SORTS[key].by;
  if (!rows || !by) return rows;
  return [...rows].sort((a, b) => (by(b) ?? Number.NEGATIVE_INFINITY) - (by(a) ?? Number.NEGATIVE_INFINITY));
}

/** Start a study's trials, watch them run, and read what each combination did over the research window (never the holdout). */
export function RunPanel({ id }: { id: number }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { can } = useAuth();
  const q = useQuery({
    queryKey: ["study-results", id],
    queryFn: () => api.studyResults(id),
    refetchInterval: (query) => (["QUEUED", "RUNNING"].includes(query.state.data?.run?.status ?? "") ? 3000 : false),
  });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["study-results", id] });
  const start = useMutation({ mutationFn: () => api.requestStudyRun(id), onSuccess: () => { toast.success("Run queued."); refresh(); } });
  const cancel = useMutation({ mutationFn: (runId: number) => api.cancelStudyRun(runId), onSuccess: () => { toast.success("Run cancelled."); refresh(); } });
  const [sort, setSort] = useState<SortKey>("settings");
  const run = q.data?.run ?? null;
  const active = run !== null && ["QUEUED", "RUNNING"].includes(run.status);
  const err = start.error ?? cancel.error;
  return (
    <Panel
      title="Run the trials"
      actions={can("strategy:own") && !active ? <button type="button" onClick={() => start.mutate()} disabled={start.isPending} className={buttonClass("primary")}>{run ? "Run again" : "Run the trials"}</button> : undefined}
    >
      <div className="space-y-4 px-5 py-4">
        <p className="text-sm text-ink-soft">Each combination of settings is run over the research window only. The holdout is never read here. A worker process does the running, so it can take hours.</p>
        {err ? <Alert tone="error">{message(err)}</Alert> : null}
        {q.isError ? <Alert tone="error">Could not load the results.</Alert> : null}
        {run ? (
          <div className="space-y-2" aria-label="Run status">
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill tone={TONE[run.status]}>{LABEL[run.status]}</StatusPill>
              {run.status === "RUNNING" ? null : <span className="text-sm">{run.done} of {run.total} combinations</span>}
              {run.current ? <span className="text-xs text-ink-soft">now: {run.current}</span> : null}
              {run.status === "QUEUED" && can("strategy:own") ? <button type="button" onClick={() => cancel.mutate(run.run_id)} className={buttonClass("secondary")}>Cancel</button> : null}
              {can("strategy:own") ? <StopButton run={run} queryKey={["study-results", id]} /> : null}
              {run.finished_at ? <span className="text-xs text-ink-soft"><RelativeTime iso={run.finished_at} /></span> : null}
            </div>
            <Progress run={run} unit="combinations" stepUnit="day" />
            {run.error ? <Alert tone="error" title="The run stopped">{run.error}</Alert> : null}
          </div>
        ) : null}
        {(q.data?.trials.length ?? 0) > 1 ? (
          <label className="flex items-center gap-2 text-xs text-ink-soft">
            Order by
            <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} className="rounded border border-line bg-white px-2 py-1 text-sm text-ink">
              {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </label>
        ) : null}
        <DataTable caption="Results by settings" columns={columns} rows={sorted(q.data?.trials, sort)} rowKey={(t) => String(t.trial_id)} loading={q.isLoading}
          empty={<EmptyState icon="flask" title="No trials run yet">Start a run to see how each combination did.</EmptyState>} />
        {q.data && q.data.universe_coverage.length > 0 ? (
          <div>
            <h3 className="mb-1 text-sm font-medium">Which stocks were available</h3>
            <p className="mb-2 text-xs text-ink-soft">Per AMFI list: companies in your segments, how many matched one of ours, and how many have Kite history. The gap is mostly stocks delisted or merged since, which this study cannot see: a survivorship effect.</p>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead><tr className="text-ink-soft"><th className="py-1 pr-3">List</th><th className="pr-3">From</th><th className="pr-3">Until</th><th className="pr-3 text-right">In segments</th><th className="pr-3 text-right">Matched</th><th className="text-right">Usable</th></tr></thead>
                <tbody>
                  {q.data.universe_coverage.map((c) => (
                    <tr key={`${c.list}-${c.from}`} className="border-t border-line"><td className="py-1 pr-3">{c.list}</td><td className="pr-3">{c.from}</td><td className="pr-3">{c.until}</td><td className="pr-3 text-right">{c.in_segments}</td><td className="pr-3 text-right">{c.matched}</td><td className="text-right">{c.usable}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        ) : null}
      </div>
    </Panel>
  );
}
