"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { FeatureList } from "@/components/research/Features";
import { Funnel, type LoopCounts, PipelineStrip } from "@/components/research/Pipeline";
import { Card, ErrorBox, Loading, Stat } from "@/components/status/LoadState";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { DefinitionsPanel } from "@/components/strategies/DefinitionsPanel";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { inputFull } from "@/components/ui/styles";
import { api } from "@/lib/api/client";
import type { IntelAlpha, IntelDefinitions, IntelNotes, IntelOverview, IntelProgress } from "@/lib/schemas";

type Hypothesis = IntelAlpha["hypotheses"][number];
type Note = IntelNotes["notes"][number];
type Job = IntelProgress["jobs"][number];

const day = (iso: string) => iso.replace("T", " ").slice(0, 16);
const num = (v: number | null, digits = 4) => (v === null ? "–" : v.toFixed(digits));
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
const duration = (s: number) => (s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : s >= 60 ? `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s` : `${s}s`);
const KIND_TONE = { FINDING: "good", FAILURE: "bad", DECISION: "info", LESSON: "neutral" } as const;

const hypothesisColumns: Column<Hypothesis>[] = [
  { key: "feature", header: "Feature", cell: (h) => `${h.feature} v${h.version}` },
  { key: "horizon", header: "Days ahead", cell: (h) => h.horizon },
  { key: "ic", header: "Mean rank IC", cell: (h) => num(h.mean_ic) },
  { key: "icir", header: "IC / its spread", hideBelow: "md", cell: (h) => num(h.icir, 2) },
  { key: "p", header: "Corrected p", hideBelow: "md", cell: (h) => num(h.p_adjusted) },
  { key: "dir", header: "Direction", hideBelow: "sm", cell: (h) => h.direction ?? "–" },
  { key: "status", header: "Verdict", cell: (h) => <StatusPill tone={h.status === "CANDIDATE" ? "good" : "neutral"}>{h.status === "CANDIDATE" ? "Worth validating" : "Rejected"}</StatusPill> },
];

const noteColumns: Column<Note>[] = [
  { key: "kind", header: "Kind", cell: (n) => <StatusPill tone={KIND_TONE[n.kind]}>{n.kind.toLowerCase()}</StatusPill> },
  { key: "subject", header: "Subject", cell: (n) => n.subject },
  { key: "body", header: "Note", cell: (n) => <span className="text-ink-soft">{n.body}</span> },
  { key: "by", header: "By", hideBelow: "md", cell: (n) => n.by },
  { key: "at", header: "When", hideBelow: "md", cell: (n) => day(n.at) },
];

/** Time left, from how long the finished steps actually took. It says plainly when it cannot give one, instead of showing a made-up number. */
function Estimate({ j }: { j: Job }) {
  if (j.estimate === "ok" && j.eta_s !== null && j.per_step_s !== null) {
    const at = new Date(Date.now() + j.eta_s * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return (
      <p className="text-xs text-ink-soft" data-testid="estimate">
        About {duration(j.eta_s)} left, around {at}. Based on {duration(j.per_step_s)} per finished step; later steps may differ.
      </p>
    );
  }
  const why = {
    waiting: "Estimating: needs two finished steps to predict the rest.",
    uneven: "No estimate: this job's steps are very different in size.",
    overrun: j.per_step_s !== null ? `Taking longer than the average step (${duration(j.per_step_s)}), so no reliable estimate.` : "Taking longer than the average step.",
    none: "",
    ok: "",
  }[j.estimate];
  return why ? (
    <p className="text-xs text-ink-faint" data-testid="estimate">
      {why}
    </p>
  ) : null;
}

/** One long job: where it is (steps done of total), what it is doing right now, how long it has run, and a warning when it has gone quiet or its process is gone. */
function JobRow({ j }: { j: Job }) {
  const share = j.total > 0 ? Math.round((j.done / j.total) * 100) : 0;
  const tone = j.status === "FAILED" || j.stalled ? "bad" : j.status === "DONE" ? "good" : "info";
  const word = j.status === "RUNNING" ? (j.stalled ? "May be stuck" : "Running") : j.status === "DONE" ? "Finished" : "Failed";
  return (
    <li className="space-y-2 px-5 py-4 text-sm" data-testid={`job-${j.job}`}>
      <div className="flex flex-wrap items-center gap-3">
        <StatusPill tone={tone}>{word}</StatusPill>
        <span className="font-medium">{j.label}</span>
        <span className="text-ink-soft">
          {j.done} of {j.total} done
        </span>
        <span className="ml-auto text-xs text-ink-faint">
          {j.status === "RUNNING" ? `running for ${duration(j.elapsed_s)}` : `took ${duration(j.elapsed_s)}`}
        </span>
      </div>
      <div role="progressbar" aria-label={`${j.label} progress`} aria-valuemin={0} aria-valuemax={j.total} aria-valuenow={j.done} className="h-2 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full ${tone === "bad" ? "bg-red-500" : tone === "good" ? "bg-emerald-500" : "bg-blue-500"}`} style={{ width: `${share}%` }} />
      </div>
      <p className="text-ink-soft">
        {j.phase}
        {j.message ? `: ${j.message}` : ""}
      </p>
      {j.status === "RUNNING" ? <Estimate j={j} /> : null}
      {j.status === "RUNNING" && j.alive === false ? <p className="text-xs text-red-700">The process running this job is gone, so it did not finish.</p> : null}
      {j.status === "RUNNING" && j.alive !== false && j.stalled ? <p className="text-xs text-red-700">No update for {duration(j.quiet_s ?? 0)}. It may be stuck, or in a slow step.</p> : null}
    </li>
  );
}

function useJobs() {
  return useQuery({
    queryKey: ["intel", "progress"],
    queryFn: api.intelProgress,
    refetchInterval: (q) => (q.state.data?.jobs.some((j) => j.status === "RUNNING") ? 3000 : 15000),
  });
}

/** The pipeline: which step runs now, then how many things survive each stage and why the rest were dropped. */
function loopCounts(defs: IntelDefinitions["definitions"] | undefined): LoopCounts | undefined {
  if (!defs) return undefined;
  const judged = defs.filter((d) => d.study === "judged").length;
  const running = defs.filter((d) => d.study === "running").length;
  return { total: defs.length, judged, running, waiting: defs.length - judged - running };
}

function PipelinePanel() {
  const jobs = useJobs();
  const defs = useQuery({ queryKey: ["intel", "definitions"], queryFn: api.intelDefinitions, refetchInterval: 15000 });
  const funnel = useQuery({ queryKey: ["intel", "funnel"], queryFn: api.intelFunnel, refetchInterval: 15000 });
  return (
    <Card title="Research pipeline" note="Each card counts what entered that stage, what moved on and what was dropped, with the reasons. Dropped ideas are kept, not hidden: they raise the bar for the next one.">
      <div className="space-y-4">
        <PipelineStrip jobs={jobs.data?.jobs ?? []} />
        {funnel.isLoading ? <Loading what="the funnel" /> : funnel.error ? <ErrorBox error={funnel.error} what="the funnel" /> : funnel.data ? <Funnel stages={funnel.data.stages} jobs={jobs.data?.jobs ?? []} loop={loopCounts(defs.data?.definitions)} /> : null}
      </div>
    </Card>
  );
}

/** Every feature, what it measures and how its last validation went. It refreshes every 4 seconds while a validation is running, so each result appears as it is recorded. */
function FeaturesPanel() {
  const jobs = useJobs();
  const validating = jobs.data?.jobs.some((j) => j.job === "feature_validation" && j.status === "RUNNING") ?? false;
  const features = useQuery({ queryKey: ["intel", "features"], queryFn: api.intelFeatures, refetchInterval: validating ? 4000 : 20000 });
  return (
    <Panel title="Features" actions={<span className="text-xs text-ink-faint">{validating ? "validation running · updates every 4 seconds" : "refreshes every 20 seconds"}</span>}>
      {features.isLoading ? (
        <p className="px-5 py-4 text-sm text-ink-soft" role="status">
          Loading features…
        </p>
      ) : features.error ? (
        <div className="px-5 py-4">
          <ErrorBox error={features.error} what="the features" />
        </div>
      ) : features.data ? (
        <>
          <p className="border-b border-line px-5 py-3 text-xs text-ink-soft">
            Features are defined in code, each with a version and a fingerprint, so a changed definition cannot slip in unnoticed. A new feature is a code change, not a setting on this page. Four checks decide whether a feature may be used: enough values, the same values on a second independent read, stored months that agree, and no look-ahead.
          </p>
          <FeatureList features={features.data.features} jobs={jobs.data?.jobs ?? []} />
        </>
      ) : null}
    </Panel>
  );
}

function JobsPanel() {
  const jobs = useJobs();
  const running = jobs.data?.jobs.filter((j) => j.status === "RUNNING").length ?? 0;
  return (
    <Panel title="Running jobs" actions={<span className="text-xs text-ink-faint">{running > 0 ? `${running} running · updates every 3 seconds` : "refreshes every 15 seconds"}</span>}>
      {jobs.isLoading ? (
        <p className="px-5 py-4 text-sm text-ink-soft" role="status">
          Loading jobs…
        </p>
      ) : jobs.error ? (
        <div className="px-5 py-4">
          <ErrorBox error={jobs.error} what="the job progress" />
        </div>
      ) : jobs.data && jobs.data.jobs.length > 0 ? (
        <ul className="divide-y divide-line">
          {jobs.data.jobs.map((j) => (
            <JobRow key={j.id} j={j} />
          ))}
        </ul>
      ) : (
        <EmptyState title="No job has reported progress yet">Feature validation, feature computation and alpha discovery show here while they run.</EmptyState>
      )}
    </Panel>
  );
}

function Counts({ label, counts }: { label: string; counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  return <Stat label={label} value={entries.length === 0 ? "None yet" : entries.map(([k, v]) => `${v} ${k.toLowerCase()}`).join(", ")} />;
}

function Overview({ o }: { o: IntelOverview }) {
  return (
    <div className="space-y-6">
      <Card title="Where the research stands" note="Everything on this page is read from what the research jobs have recorded. Nothing here runs a job or places an order.">
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
          <Counts label="Features" counts={o.features.by_status} />
          <Stat label="Alpha tests ever run" value={o.alpha.tests_ever_run} hint="every test raises the bar for the next" />
          <Stat label="Strategy definitions" value={o.factory.definitions} hint={`${o.factory.experiments} experiments, ${o.factory.trials} trials`} />
          <Stat label="Research notes" value={o.notes.total} />
        </div>
      </Card>
      <Panel title="Strategy health">
        {o.health.length === 0 ? (
          <EmptyState title="No health check has run yet">A paper account is compared with its backtest by the health check; each result appears here.</EmptyState>
        ) : (
          <ul className="divide-y divide-line">
            {o.health.map((h) => (
              <li key={h.scope} className="flex flex-wrap items-center gap-3 px-5 py-3 text-sm">
                <StatusPill tone={h.status === "FAIL" ? "bad" : "good"}>{h.status === "FAIL" ? "Degraded" : "Not degraded"}</StatusPill>
                <span className="font-medium">{h.scope}</span>
                <span className="text-ink-soft">{h.detail}</span>
                <span className="ml-auto text-xs text-ink-faint">{day(h.at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel title="Latest capital allocation advice">
        {o.allocation === null ? (
          <EmptyState title="No allocation advice yet">It is a recommendation only; applying it is your decision.</EmptyState>
        ) : (
          <div className="space-y-3 px-5 py-4 text-sm">
            <p className="text-ink-soft">
              {o.allocation.method.replace("_", " ").toLowerCase()}, by {o.allocation.by}, {day(o.allocation.at)}. Advice only, nothing was changed.
            </p>
            <ul className="grid gap-x-8 gap-y-1 sm:grid-cols-2 lg:grid-cols-3">
              {Object.entries(o.allocation.weights).map(([k, v]) => (
                <li key={k} className="flex justify-between">
                  <span>{k}</span>
                  <span className="tabular-nums">{pct(v)}</span>
                </li>
              ))}
              <li className="flex justify-between font-medium">
                <span>Cash</span>
                <span className="tabular-nums">{pct(o.allocation.cash)}</span>
              </li>
            </ul>
            {o.allocation.notes.map((n) => (
              <p key={n} className="text-xs text-ink-soft">
                {n}
              </p>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

export default function IntelligencePage() {
  const [status, setStatus] = useState<"" | "CANDIDATE" | "REJECTED">("");
  const [q, setQ] = useState("");
  const overview = useQuery({ queryKey: ["intel", "overview"], queryFn: api.intelOverview });
  const alpha = useQuery({ queryKey: ["intel", "alpha", status], queryFn: () => api.intelAlpha(status || undefined) });
  const notes = useQuery({ queryKey: ["intel", "notes", q], queryFn: () => api.intelNotes(q) });
  return (
    <div className="space-y-6">
      <PageHeader title="Research intelligence" subtitle="Features, alpha tests, strategy health, research notes and capital allocation advice, as recorded so far. Read-only." />
      <PipelinePanel />
      <JobsPanel />
      <DefinitionsPanel />
      <FeaturesPanel />
      {overview.isLoading ? <Loading what="the research overview" /> : overview.error ? <ErrorBox error={overview.error} what="the research overview" /> : overview.data ? <Overview o={overview.data} /> : null}
      <Panel
        title="Alpha tests"
        actions={
          <select aria-label="Verdict filter" className={inputFull} value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
            <option value="">All verdicts</option>
            <option value="CANDIDATE">Worth validating</option>
            <option value="REJECTED">Rejected</option>
          </select>
        }
      >
        <DataTable
          caption="Alpha hypotheses"
          columns={hypothesisColumns}
          rows={alpha.data?.hypotheses}
          rowKey={(h) => String(h.id)}
          loading={alpha.isLoading}
          empty={<EmptyState title="No alpha test has been recorded">Discovery has not run on real data yet. Failed tests are kept too, because they raise the bar for the next one.</EmptyState>}
        />
      </Panel>
      <Panel title="Research notes" actions={<input aria-label="Search notes" className={inputFull} placeholder="Search notes" value={q} onChange={(e) => setQ(e.target.value)} maxLength={200} />}>
        <DataTable caption="Research notes" columns={noteColumns} rows={notes.data?.notes} rowKey={(n) => String(n.id)} loading={notes.isLoading} empty={<EmptyState title="No notes match">Findings, failures and decisions are saved here.</EmptyState>} />
      </Panel>
    </div>
  );
}
