"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { DefinitionList, Panel, RelativeTime, StatusPill } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import { fmtMoney } from "@/lib/formatting";
import { THRESHOLD_LABELS } from "@/lib/studies";

export default function StudyPage() {
  const id = Number(useParams<{ id: string }>().id);
  const q = useQuery({ queryKey: ["study", id], queryFn: () => api.study(id), enabled: Number.isFinite(id) });
  const s = q.data;
  return (
    <div className="space-y-6">
      <PageHeader title={s?.name ?? "Study"} breadcrumbs={[{ label: "Backtest studies", href: "/research/studies" }, { label: s?.name ?? "Study" }]}
        subtitle="Registered and locked: these settings can no longer change." />
      {q.isError ? <Alert tone="error" title="Could not load the study">It may not exist.</Alert> : null}
      {q.isLoading ? <div role="status" aria-label="Loading the study"><Skeleton className="h-64 w-full" /></div> : null}
      {s ? (
        <>
          <div className="flex flex-wrap gap-2">
            <StatusPill tone="info">Locked</StatusPill>
            <StatusPill tone="neutral">{s.trials_run} of {s.trials_planned} trials run</StatusPill>
            <StatusPill tone={s.holdout_opened_at ? "warn" : "good"}>{s.holdout_opened_at ? "Holdout opened" : "Holdout untouched"}</StatusPill>
          </div>
          <Alert tone="info" title="Running a study">The runner that executes the trials, the walk-forward and the one-time holdout is the next build.</Alert>
          <Panel title="The idea"><div className="px-5 py-4 text-sm">{s.hypothesis}</div></Panel>
          <Panel title="Settings">
            <div className="px-5 py-4">
              <DefinitionList items={[
                { label: "Strategy", value: s.strategy_id },
                { label: "Settings tried", value: Object.entries(s.spec.grid).map(([k, v]) => `${k}: ${v.join(", ")}`).join(" · ") },
                { label: "Stocks", value: `${s.spec.universe.segments.join(", ")}; at least ${s.spec.universe.min_history_sessions} sessions of history` },
                { label: "Period", value: `${s.spec.start} to ${s.spec.end}, ${s.spec.timeframe}` },
                { label: "Holdout", value: `from ${s.spec.holdout_start}` },
                { label: "Capital", value: `₹${fmtMoney(s.spec.capital, 0)}, capacity tested at ${s.spec.capacity_multiple}x` },
                { label: "Charges", value: `${s.spec.broker}, ${s.spec.product.toLowerCase()}: ${s.cost_schedules.map((c) => `${c.valid_from} (${c.status.replace(/_/g, " ")})`).join("; ")}` },
                { label: "Price history", value: `frozen through ${s.data_freeze.through}` },
                ...(s.spec.accept_survivorship_bias ? [{ label: "Survivorship", value: "bias accepted by the owner (starts before October 2019)" }] : []),
                { label: "Registered", value: <RelativeTime iso={s.registered_at} /> },
                { label: "Checksum", value: <span className="font-mono text-xs">{s.sha256.slice(0, 16)}</span> },
              ]} />
            </div>
          </Panel>
          <Panel title="Pass or fail">
            <div className="px-5 py-4">
              <DefinitionList items={Object.entries(s.spec.thresholds).map(([k, v]) => ({ label: THRESHOLD_LABELS[k] ?? k, value: v }))} />
            </div>
          </Panel>
        </>
      ) : null}
    </div>
  );
}
