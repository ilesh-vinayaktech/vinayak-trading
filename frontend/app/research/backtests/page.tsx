"use client";

import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, Flag } from "@/components/status/Badge";
import { Card, ErrorBox, Loading } from "@/components/status/LoadState";
import { DataTable } from "@/components/tables/DataTable";
import { api } from "@/lib/api/client";
import { fmtDateTime, shortHash } from "@/lib/formatting";
import type { BacktestRow } from "@/lib/schemas";

const COLUMNS: ColumnDef<BacktestRow, unknown>[] = [
  { header: "Run", accessorKey: "run_id", cell: ({ getValue }) => `#${String(getValue())}` },
  { header: "Strategy", cell: ({ row }) => `${row.original.strategy_id} v${row.original.strategy_version}` },
  { header: "Reader mode", accessorKey: "reader_mode" },
  { header: "Created", accessorKey: "created_at", cell: ({ getValue }) => fmtDateTime(String(getValue())) },
  { header: "Accounting", cell: ({ row }) => <Flag value={row.original.accounting_complete} yes="complete" no="incomplete" /> },
  { header: "Ledger", cell: ({ row }) => <Flag value={row.original.ledger_reconciled} yes="reconciled" no="not reconciled" /> },
  { header: "Result hash", accessorKey: "result_hash", cell: ({ getValue }) => <code className="text-xs">{shortHash(String(getValue()), 12)}</code> },
];

const DISABLED_FIELDS = [
  ["Strategy", "No strategies are registered yet"],
  ["Instrument / universe", "Needs the strategy runner"],
  ["Date range", "Needs the strategy runner"],
  ["Dataset version", "Needs the strategy runner"],
  ["Adjustment mode", "none, split or total_return"],
  ["Cost schedule", "Needs verified cost schedules"],
  ["Initial capital", "Needs the strategy runner"],
];

const RESULTS = ["Equity curve", "Drawdown", "Monthly returns", "Sharpe and deflated Sharpe", "PBO", "Benchmark comparison", "Trade history", "Ledger reconciliation"];

export default function BacktestsPage() {
  const { data, error, isLoading } = useQuery({ queryKey: ["backtests"], queryFn: () => api.backtests() });
  return (
    <div className="space-y-6">
      <PageHeader title="Backtest Explorer" subtitle="Skeleton. Running a backtest needs the orchestrator, which does not exist yet, so the controls below are disabled rather than faked." />

      <Card title="New run (not available)" note="Every run will be reproducible from its saved configuration and evidence references.">
        <div className="grid gap-3 md:grid-cols-2">
          {DISABLED_FIELDS.map(([label, why]) => (
            <div key={label}>
              <label className="block text-xs text-ink-soft">{label}</label>
              <input disabled aria-label={label} placeholder={why} className="mt-1 w-full cursor-not-allowed rounded-md border border-line bg-slate-50 px-3 py-2 text-sm" />
            </div>
          ))}
        </div>
        <button type="button" disabled className="mt-4 cursor-not-allowed rounded-md bg-slate-300 px-4 py-2 text-sm text-white">
          Run backtest
        </button>
      </Card>

      <Card title="Stored runs">
        {isLoading ? <Loading what="runs" /> : error || !data ? <ErrorBox error={error} what="runs" /> : <DataTable data={data.items} columns={COLUMNS} empty="No backtests have been stored yet." />}
      </Card>

      <Card title="What a finished run will show">
        <div className="flex flex-wrap gap-2">
          {RESULTS.map((r) => (
            <Badge key={r}>{r}</Badge>
          ))}
        </div>
        <p className="mt-3 text-xs text-ink-faint">All figures will come from the backend; the browser will not compute P&L, Sharpe, fees or adjustments.</p>
      </Card>
    </div>
  );
}
