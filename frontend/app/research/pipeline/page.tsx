"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { RunPipelineDialog } from "@/components/research/RunPipelineDialog";
import { ErrorBox, Loading } from "@/components/status/LoadState";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import type { Pipeline } from "@/lib/schemas";

type Row = Pipeline["rows"][number];
type Figures = NonNullable<Row["inner"]>;

const pct = (x: number | null | undefined) => (x == null ? "-" : `${(x * 100).toFixed(0)}%`);
const OUTCOME = { ready: ["good", "Ready for paper"], stopped: ["bad", "Stopped"], waiting: ["warn", "Waiting"], running: ["info", "Running"] } as const;
const STAGE = { development: "development", inner: "the inner holdout", outer: "the outer holdout", paper: "paper trading" } as const;
const DEPTH = { development: 0, inner: 1, outer: 2, paper: 3 } as const;
const rank = (r: Row) => (r.outcome === "ready" ? 100 : DEPTH[r.stage] * 10 + (r.outcome === "stopped" ? 0 : 5));

function Stage({ s }: { s: Figures | null }) {
  if (s === null) return <span className="text-ink-soft">not run</span>;
  return (
    <div className="space-y-1">
      <StatusPill tone={s.passed ? "good" : "bad"}>{s.passed ? "Passed" : "Failed"}</StatusPill>
      <div className="whitespace-nowrap text-xs text-ink-soft">
        {pct(s.cagr)} a year, worst fall {pct(s.max_drawdown)}
        {s.sharpe != null ? `, Sharpe ${s.sharpe.toFixed(2)}` : ""}
      </div>
    </div>
  );
}

function Outer({ r }: { r: Row }) {
  if (r.outer === null) return <span className="text-ink-soft">not submitted</span>;
  const tone = r.outer.overall === "PASS" ? "good" : r.outer.overall === "FAIL" ? "bad" : "warn";
  return <StatusPill tone={tone}>{r.outer.overall === "INCOMPLETE" ? "Not complete" : r.outer.overall === "PASS" ? "Passed" : "Failed"}</StatusPill>;
}

/** Every strategy at a glance: how far it got through development, the inner holdout, the outer holdout and paper, where it stopped and why, and what it returned. */
export default function PipelinePage() {
  const { can } = useAuth();
  const [running, setRunning] = useState(false);
  const q = useQuery({ queryKey: ["pipeline"], queryFn: api.pipeline, refetchInterval: 15000 });
  if (q.isLoading) return <Loading what="the strategy pipeline" />;
  if (q.isError || !q.data) return <ErrorBox error={q.error} what="the strategy pipeline" />;
  const { rows, outer_visible } = q.data;
  const sorted = [...rows].sort((a, b) => rank(b) - rank(a) || a.name.localeCompare(b.name));
  const funnel: [string, number][] = [
    ["Tested", rows.length],
    ["Passed development", rows.filter((r) => r.development?.passed).length],
    ["Passed inner holdout", rows.filter((r) => r.inner?.passed).length],
    ...(outer_visible ? ([["Passed outer holdout", rows.filter((r) => r.outer?.overall === "PASS").length]] as [string, number][]) : []),
    ["Ready for paper", rows.filter((r) => r.outcome === "ready").length],
  ];
  const columns: Column<Row>[] = [
    { key: "name", header: "Strategy", cell: (r) => <Link href={`/research/studies/${r.experiment_id}`} className="font-medium text-brand hover:underline">{r.name}</Link> },
    {
      key: "now",
      header: "Where it stands",
      cell: (r) => (
        <div className="max-w-md space-y-1">
          <StatusPill tone={OUTCOME[r.outcome][0]}>{r.outcome === "stopped" ? `Stopped at ${STAGE[r.stage]}` : OUTCOME[r.outcome][1]}</StatusPill>
          <div className="text-xs text-ink-soft">{r.why}</div>
        </div>
      ),
    },
    { key: "dev", header: "Development 2016-2022", hideBelow: "md", cell: (r) => <Stage s={r.development} /> },
    { key: "inner", header: "Inner holdout 2023-2024", hideBelow: "md", cell: (r) => <Stage s={r.inner} /> },
    ...(outer_visible ? [{ key: "outer", header: "Outer holdout 2025-2026", hideBelow: "lg" as const, cell: (r: Row) => <Outer r={r} /> }] : []),
  ];
  return (
    <div className="space-y-6">
      <PageHeader
        title="Strategy pipeline"
        subtitle="Every strategy, how far it got, where it stopped and why, and what it returned. Development, then the inner holdout, then the outer holdout, then paper trading."
        actions={can("strategy:own") ? <button type="button" className={buttonClass("primary")} onClick={() => setRunning(true)}>Run strategies</button> : undefined}
      />
      <RunPipelineDialog open={running} onClose={() => setRunning(false)} codeDirty={q.data.code_dirty} />
      <Panel title="How many made it">
        <ul className="grid grid-cols-2 gap-4 p-4 sm:grid-cols-3 lg:grid-cols-5" data-testid="funnel">
          {funnel.map(([label, n]) => (
            <li key={label}>
              <div className="text-2xl font-semibold tabular-nums">{n}</div>
              <div className="text-xs text-ink-soft">{label}</div>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="All strategies">
        <DataTable caption="Strategy pipeline" columns={columns} rows={sorted} rowKey={(r) => String(r.experiment_id)} empty={<EmptyState icon="flask" title="No strategies yet">Register a study to start one down the pipeline.</EmptyState>} />
      </Panel>
      <p className="text-xs text-ink-soft">
        Returns are yearly, after costs, for the stages research may see. The outer holdout shows pass or fail only{outer_visible ? "" : " and is visible to the owner"}: its figures are never shown, so they cannot guide the next idea.
      </p>
    </div>
  );
}
