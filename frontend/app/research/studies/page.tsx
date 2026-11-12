"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Panel, RelativeTime } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import type { Study } from "@/lib/schemas";

const columns: Column<Study>[] = [
  { key: "name", header: "Study", cell: (s) => <Link href={`/research/studies/${s.experiment_id}`} className="font-medium text-brand hover:underline">{s.name}</Link> },
  { key: "stocks", header: "Stocks", hideBelow: "sm", cell: (s) => s.spec.universe.segments.join(", ") },
  { key: "period", header: "Period", hideBelow: "md", cell: (s) => <span className="whitespace-nowrap">{s.spec.start} to {s.spec.end}</span> },
  { key: "holdout", header: "Holdout from", hideBelow: "md", cell: (s) => s.spec.holdout_start },
  { key: "trials", header: "Trials run", className: "text-right", cell: (s) => `${s.trials_run} of ${s.trials_planned}` },
  { key: "when", header: "Registered", hideBelow: "lg", cell: (s) => <span className="text-ink-soft"><RelativeTime iso={s.registered_at} /></span> },
];

export default function StudiesPage() {
  const { can } = useAuth();
  const q = useQuery({ queryKey: ["studies"], queryFn: api.studies });
  return (
    <div className="space-y-6">
      <PageHeader
        title="Backtest studies"
        subtitle="An official backtest starts as a study: the idea, the settings to try, the stocks, the period and the pass/fail bar, all fixed before anything runs."
        actions={can("strategy:own") ? <Link href="/research/studies/new" className={buttonClass("primary")}>New study</Link> : undefined}
      />
      {q.isError ? <Alert tone="error" title="Could not load the studies">Try again in a moment.</Alert> : null}
      <Panel title="Registered studies">
        <DataTable caption="Registered studies" columns={columns} rows={q.data?.studies} rowKey={(s) => String(s.experiment_id)} loading={q.isLoading}
          empty={<EmptyState icon="flask" title="No studies yet">Register one to set up an official backtest.</EmptyState>} />
      </Panel>
    </div>
  );
}
