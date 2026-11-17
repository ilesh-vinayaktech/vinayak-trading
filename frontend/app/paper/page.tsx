"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { OrdersPanel } from "@/components/paper/OrdersPanel";
import { Overview } from "@/components/paper/Overview";
import { SettingsForm } from "@/components/paper/SettingsForm";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, Skeleton, type Column } from "@/components/ui/DataTable";
import { Panel, RelativeTime, StatusPill, Tabs, type Tab } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import type { PaperRun } from "@/lib/schemas";

type Key = "overview" | "orders" | "decisions" | "settings";
const TONE: Record<PaperRun["status"], "good" | "warn" | "bad" | "neutral"> = { PROPOSED: "good", NO_CHANGE: "neutral", SKIPPED: "warn", ERROR: "bad" };
const LABEL: Record<PaperRun["status"], string> = { PROPOSED: "Orders proposed", NO_CHANGE: "No change", SKIPPED: "Skipped", ERROR: "Could not decide" };

const columns: Column<PaperRun>[] = [
  { key: "day", header: "Decision day", cell: (r) => <span className="whitespace-nowrap font-medium">{r.decision_day}</span> },
  { key: "status", header: "Result", cell: (r) => <StatusPill tone={TONE[r.status]}>{LABEL[r.status]}</StatusPill> },
  { key: "orders", header: "Orders", className: "text-right", cell: (r) => r.orders },
  { key: "reason", header: "Detail", hideBelow: "sm", cell: (r) => <span className="text-ink-soft">{r.reason ?? ""}</span> },
  { key: "when", header: "Ran", hideBelow: "md", cell: (r) => <span className="text-ink-soft"><RelativeTime iso={r.created_at} /></span> },
];

function Decisions() {
  const q = useQuery({ queryKey: ["paper", "runs"], queryFn: api.paperRuns });
  return (
    <Panel title="Daily decisions">
      {q.isError ? <div className="p-5"><Alert tone="error">Could not load the decision log.</Alert></div> : <DataTable caption="Daily decisions" columns={columns} rows={q.data?.runs} rowKey={(r) => r.decision_day} loading={q.isLoading} empty={<EmptyState icon="scroll" title="No decisions yet">The strategy decides once a day, after the market closes.</EmptyState>} />}
    </Panel>
  );
}

export default function PaperPage() {
  const q = useQuery({ queryKey: ["paper", "account"], queryFn: api.paperAccount });
  const summary = useQuery({ queryKey: ["paper", "summary"], queryFn: api.paperSummary, enabled: q.data?.account != null });
  const [tab, setTab] = useState<Key>("overview");
  const d = q.data;
  const tabs: Tab<Key>[] = [
    { key: "overview", label: "Overview" },
    { key: "orders", label: "Orders", count: summary.data?.pending_orders || undefined },
    { key: "decisions", label: "Decisions" },
    { key: "settings", label: "Settings" },
  ];
  return (
    <div className="space-y-6">
      <PageHeader title="Paper trading" subtitle="Practise the strategy with pretend money. You approve every order, and nothing here places a real one." />
      {d?.account?.definition ? (
        <Alert tone="info" title="Passed the holdout">
          {d.account.definition} passed development and the 2025-2026 holdout. That is a screen, not proof: paper results from here on are the real test, and they show whether the plumbing works, not yet that it makes money.
        </Alert>
      ) : (
        <Alert tone="warn" title="Unvalidated research">
          This strategy has not passed validation. Paper results show whether the plumbing works, not that the strategy makes money.
        </Alert>
      )}
      {q.isError ? <Alert tone="error" title="Could not load your paper account">Try again in a moment.</Alert> : null}
      {q.isLoading ? <div role="status" aria-label="Loading your paper account"><Skeleton className="h-40 w-full" /></div> : null}
      {d && d.account === null ? (
        <>
          <p className="text-sm text-ink-soft">You have no paper account yet. Choose what the strategy should trade and start with some pretend cash.</p>
          <SettingsForm data={d} />
        </>
      ) : null}
      {d?.account ? (
        <>
          {d.account.attention ? <Alert tone="warn" title="Paused">{d.account.attention}. New orders are not proposed until an administrator clears this.</Alert> : null}
          {!d.account.enabled ? <Alert tone="info" title="Paper trading is off">No new orders are proposed. Turn it on in Settings.</Alert> : null}
          <Tabs tabs={tabs} value={tab} onChange={setTab} label="Paper trading sections" />
          {tab === "overview" ? <Overview /> : null}
          {tab === "orders" ? <OrdersPanel /> : null}
          {tab === "decisions" ? <Decisions /> : null}
          {tab === "settings" ? <SettingsForm data={d} /> : null}
        </>
      ) : null}
    </div>
  );
}
