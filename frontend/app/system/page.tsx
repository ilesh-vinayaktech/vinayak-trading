"use client";

import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { Badge } from "@/components/status/Badge";
import { Card, ErrorBox, Loading } from "@/components/status/LoadState";
import { DataTable } from "@/components/tables/DataTable";
import { PageHeader } from "@/components/layout/PageHeader";
import { api } from "@/lib/api/client";
import { fmtDateTime, fmtInt, partitionStatus } from "@/lib/formatting";
import type { IngestionRow } from "@/lib/schemas";

const PAGE = 25;

/** noop = the same file was loaded again and nothing changed. */
const statusLabel = partitionStatus;

function statusTone(s: string) {
  return s === "loaded" || s === "noop" ? "good" : s === "quarantined" ? "bad" : "neutral";
}

const COLUMNS: ColumnDef<IngestionRow, unknown>[] = [
  { header: "When", accessorKey: "at", cell: ({ getValue }) => fmtDateTime(String(getValue())) },
  { header: "Source", cell: ({ row }) => `${row.original.source}/${row.original.dataset}` },
  { header: "Partition", accessorKey: "partition" },
  {
    header: "Result",
    cell: ({ row }) => <Badge tone={statusTone(row.original.status)}>{statusLabel(row.original.status)}</Badge>,
  },
];

export default function SystemPage() {
  const [offset, setOffset] = useState(0);
  const { data, error, isLoading } = useQuery({ queryKey: ["activity", offset], queryFn: () => api.activity(PAGE, offset), placeholderData: (prev) => prev });
  if (isLoading) return <Loading what="activity" />;
  if (error || !data) return <ErrorBox error={error} what="system activity" />;
  const ing = data.ingestion;
  const live = ing.items.filter((r) => r.status === "quarantined");
  const last = Math.min(ing.offset + ing.items.length, ing.total);
  return (
    <div className="space-y-6">
      <PageHeader title="System Activity" subtitle="What the stores record today. Job runtime and resource use are not recorded, and this page says so instead of guessing." />
      <Card
        title="Ingestion events (newest first)"
        note="One row per date, showing its latest load. Earlier attempts for the same date (a file that was not out yet, a failure a later load fixed) are not listed. Current quarantines are also on the dashboard."
      >
        {live.length > 0 ? (
          <p className="mb-3 text-sm text-red-700" role="alert">
            {live.length} partition(s) on this page are currently quarantined: {live.map((r) => r.partition).join(", ")}.
          </p>
        ) : null}
        <DataTable data={ing.items} columns={COLUMNS} empty="No ingestion events." />
        <div className="mt-3 flex items-center justify-between text-xs text-ink-soft">
          <span>
            {ing.total === 0 ? "0 events" : `${fmtInt(ing.offset + 1)}-${fmtInt(last)} of ${fmtInt(ing.total)} events`}
          </span>
          <span className="flex gap-2">
            <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="rounded border border-line px-3 py-1 disabled:opacity-40">
              Newer
            </button>
            <button type="button" disabled={ing.offset + ing.items.length >= ing.total} onClick={() => setOffset(offset + PAGE)} className="rounded border border-line px-3 py-1 disabled:opacity-40">
              Older
            </button>
          </span>
        </div>
      </Card>
      <Card title="Latest validation per benchmark">
        <ul className="divide-y divide-line text-sm">
          {data.validations.map((v) => (
            <li key={v.benchmark_id} className="flex flex-wrap items-center gap-2 py-2">
              <span className="min-w-56 font-medium">{v.name}</span>
              {v.latest ? (
                <>
                  <Badge tone={v.latest.technical_validation_passed ? "good" : "bad"}>technical {v.latest.technical_validation_passed ? "passed" : "not passed"}</Badge>
                  <Badge tone={v.latest.covers_current_dataset ? "good" : "warn"}>{v.latest.covers_current_dataset ? "current" : "stale"}</Badge>
                  <span className="text-xs text-ink-soft">
                    validation #{v.latest.validation_id}, {fmtDateTime(v.latest.created_at)}
                  </span>
                </>
              ) : (
                <Badge>never validated</Badge>
              )}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Backtest and validation jobs" note={data.jobs.note}>
        <p className="text-sm text-ink-soft">{data.backtests.length} stored backtest run(s) in the latest page.</p>
      </Card>
    </div>
  );
}
