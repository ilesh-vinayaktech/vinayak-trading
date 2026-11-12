"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Panel, RelativeTime } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import type { BacktestRow } from "@/lib/schemas";

const pct = (v: unknown) => (typeof v === "number" ? `${(v * 100).toFixed(1)}%` : "-");
const colour = (v: unknown) => (typeof v === "number" && v < 0 ? "text-red-600" : "text-emerald-700");

const COLUMNS: Column<BacktestRow>[] = [
  { key: "run", header: "Run", cell: (r) => <Link href={`/research/backtests/${r.run_id}`} className="font-medium text-brand hover:underline">#{r.run_id} · view report</Link> },
  { key: "s", header: "Strategy", cell: (r) => <span>{r.strategy_id} v{r.strategy_version}{r.label ? <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-ink-soft">{r.label}</span> : null}</span> },
  { key: "study", header: "Study", hideBelow: "md", cell: (r) => (r.study ? <Link href={`/research/studies/${r.study.experiment_id}`} className="text-brand hover:underline">{r.study.name}</Link> : <span className="text-ink-faint">-</span>) },
  { key: "ret", header: "Total return", className: "text-right", cell: (r) => <span className={colour(r.metrics.total_return)}>{pct(r.metrics.total_return)}</span> },
  { key: "cagr", header: "Yearly return", className: "text-right", hideBelow: "md", cell: (r) => pct(r.metrics.cagr) },
  { key: "dd", header: "Worst drop", className: "text-right", hideBelow: "md", cell: (r) => pct(r.metrics.max_drawdown) },
  { key: "tr", header: "Fills", className: "text-right", hideBelow: "lg", cell: (r) => (typeof r.metrics.trades === "number" ? r.metrics.trades : "-") },
  { key: "at", header: "Run", hideBelow: "sm", cell: (r) => <RelativeTime iso={r.created_at} /> },
];

/** Every stored run. Runs come from the backtest studies; open one to see what it bought, sold and made. */
export default function BacktestsPage() {
  const q = useQuery({ queryKey: ["backtests"], queryFn: () => api.backtests() });
  return (
    <div className="space-y-6">
      <PageHeader title="Backtests" subtitle="Every run the studies have produced. Open one to see the stocks it traded, each trade's profit or loss, and the final amount." />
      {q.isError ? <Alert tone="error">Could not load the runs.</Alert> : null}
      <Panel>
        <DataTable caption="Stored backtest runs" columns={COLUMNS} rows={q.data?.items} rowKey={(r) => String(r.run_id)} loading={q.isLoading}
          empty={<EmptyState icon="flask" title="No runs yet">Register a backtest study and run its trials; each combination appears here.</EmptyState>} />
      </Panel>
    </div>
  );
}
