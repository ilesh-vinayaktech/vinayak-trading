"use client";

import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Badge } from "@/components/status/Badge";
import { Card, ErrorBox, Loading } from "@/components/status/LoadState";
import { DataTable } from "@/components/tables/DataTable";
import { api } from "@/lib/api/client";
import { fmtDateTime, humanize } from "@/lib/formatting";

type Ingestion = { id: number; source: string; dataset: string; partition: string; status: string; at: string };

const COLUMNS: ColumnDef<Ingestion, unknown>[] = [
  { header: "When", accessorKey: "at", cell: ({ getValue }) => fmtDateTime(String(getValue())) },
  { header: "Source", cell: ({ row }) => `${row.original.source}/${row.original.dataset}` },
  { header: "Partition", accessorKey: "partition" },
  {
    header: "Status",
    accessorKey: "status",
    cell: ({ getValue }) => {
      const s = String(getValue());
      return <Badge tone={s === "loaded" || s === "noop" ? "good" : s === "quarantined" ? "bad" : "neutral"}>{humanize(s)}</Badge>;
    },
  },
];

export default function SystemPage() {
  const { data, error, isLoading } = useQuery({ queryKey: ["activity"], queryFn: api.activity });
  if (isLoading) return <Loading what="activity" />;
  if (error || !data) return <ErrorBox error={error} what="system activity" />;
  const failed = data.ingestion.filter((r) => r.status === "quarantined");
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">System Activity</h1>
        <p className="text-sm text-ink-soft">What the stores record today. Job runtime and resource use are not recorded, and this page says so instead of guessing.</p>
      </div>
      <Card title="Ingestion (most recent first)" note={failed.length ? `${failed.length} quarantined partition(s) in this window.` : undefined}>
        <DataTable data={data.ingestion} columns={COLUMNS} empty="No ingestion events." />
      </Card>
      <Card title="Latest validation per benchmark">
        <ul className="divide-y divide-line text-sm">
          {data.validations.map((v) => (
            <li key={v.benchmark_id} className="flex flex-wrap items-center gap-2 py-2">
              <span className="font-mono text-xs">benchmark {v.benchmark_id}</span>
              {v.latest ? (
                <>
                  <Badge tone={v.latest.technical_validation_passed ? "good" : "bad"}>technical {v.latest.technical_validation_passed ? "passed" : "not passed"}</Badge>
                  <Badge tone={v.latest.covers_current_dataset ? "good" : "warn"}>{v.latest.covers_current_dataset ? "current" : "stale"}</Badge>
                  <span className="text-xs text-ink-soft">validation #{v.latest.validation_id}, {fmtDateTime(v.latest.created_at)}</span>
                </>
              ) : (
                <Badge>never validated</Badge>
              )}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Backtest and validation jobs" note={data.jobs.note}>
        <p className="text-sm text-ink-soft">{data.backtests.length} stored backtest run(s).</p>
      </Card>
    </div>
  );
}
