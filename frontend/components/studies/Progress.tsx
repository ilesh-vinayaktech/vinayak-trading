"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Alert } from "@/components/ui/Alert";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { StatusPill } from "@/components/ui/Layout";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";
import { fmtDuration } from "@/lib/formatting";
import type { StudyRun } from "@/lib/schemas";

const QUEUED_HINT_AFTER_MS = 60_000;

/** How far a job has got: a bar with a real percentage, what it is doing now, the time spent and an estimate of the time left.
 *  The estimate comes from the job's own pace, so it is "working it out" at first and settles as more of the work is done. */
export function Progress({ run, unit, stepUnit, now = Date.now() }: { run: StudyRun; unit: string; stepUnit: string; now?: number }) {
  if (run.status === "QUEUED") {
    const waited = now - new Date(run.created_at).getTime();
    return waited > QUEUED_HINT_AFTER_MS ? (
      <Alert tone="warn" title="Waiting for the worker">
        Nothing has picked this up for {fmtDuration(waited / 1000)}. The worker runs the jobs: start it with <code>./start_all.sh</code> (or <code>scripts/study_worker.py</code>).
      </Alert>
    ) : null;
  }
  if (run.status === "DONE" && run.started_at && run.finished_at) {
    return <p className="text-xs text-ink-soft">Took {fmtDuration((new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()) / 1000)}.</p>;
  }
  if (run.status !== "RUNNING") return null;
  const p = run.progress;
  const fraction = p?.fraction ?? (run.total > 0 ? run.done / run.total : 0);
  const percent = Math.min(100, Math.round(fraction * 100));
  const inUnit = p && p.step_total > 0 ? ` · ${stepUnit} ${p.step_done.toLocaleString("en-IN")} of ${p.step_total.toLocaleString("en-IN")}` : "";
  return (
    <div className="space-y-1.5">
      <div className="h-2.5 w-full overflow-hidden rounded bg-slate-200" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label="Progress">
        <div className="h-full bg-brand transition-all" style={{ width: `${percent}%` }} />
      </div>
      <p className="text-sm">
        <span className="font-medium">{percent}%</span>
        <span className="text-ink-soft"> · {run.done} of {run.total} {unit} done{inUnit}</span>
      </p>
      {p ? (
        <p className="text-xs text-ink-soft">
          Running for {fmtDuration(p.elapsed_seconds)} ·{" "}
          {p.eta_seconds === null ? "working out the time left…" : <>about <strong className="text-ink">{fmtDuration(p.eta_seconds)}</strong> left (an estimate that sharpens as it goes)</>}
        </p>
      ) : null}
    </div>
  );
}

/** Stop a job that is running. The worker ends it within a couple of seconds; finished combinations are kept. */
export function StopButton({ run, queryKey }: { run: StudyRun; queryKey: (string | number)[] }) {
  const qc = useQueryClient();
  const toast = useToast();
  const stop = useMutation({
    mutationFn: () => api.cancelStudyRun(run.run_id),
    onSuccess: () => { toast.success("Asked it to stop."); void qc.invalidateQueries({ queryKey }); },
  });
  if (run.status !== "RUNNING") return null;
  if (run.cancel_requested) return <StatusPill tone="warn">Stopping…</StatusPill>;
  return (
    <span className="inline-flex flex-col gap-1">
      <ConfirmButton question="Stop this run? Finished work is kept; the part in progress is discarded." confirmLabel="Stop it" tone="danger" onConfirm={() => stop.mutate()} disabled={stop.isPending}>Stop</ConfirmButton>
      {stop.isError ? <span className="text-xs text-red-600">{stop.error instanceof ApiError ? stop.error.message : "Could not stop it."}</span> : null}
    </span>
  );
}
