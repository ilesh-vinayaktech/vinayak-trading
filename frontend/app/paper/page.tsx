"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { OrdersPanel } from "@/components/paper/OrdersPanel";
import { Overview } from "@/components/paper/Overview";
import { LiveStatusPanel } from "@/components/paper/LiveStatusPanel";
import { SettingsForm } from "@/components/paper/SettingsForm";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, Skeleton, type Column } from "@/components/ui/DataTable";
import { Panel, RelativeTime, StatusPill, Tabs, type Tab } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import type { PaperRun } from "@/lib/schemas";
import { VenueContext, useVenue, type Venue } from "@/lib/venue";

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
  const mode = useVenue();
  const q = useQuery({ queryKey: ["paper", mode, "runs"], queryFn: () => api.paperRuns(mode) });
  return (
    <Panel title="Daily decisions">
      {q.isError ? <div className="p-5"><Alert tone="error">Could not load the decision log.</Alert></div> : <DataTable caption="Daily decisions" columns={columns} rows={q.data?.runs} rowKey={(r) => r.decision_day} loading={q.isLoading} empty={<EmptyState icon="scroll" title="No decisions yet">The strategy decides once a day, after the market closes.</EmptyState>} />}
    </Panel>
  );
}

export default function PaperPage() {
  const [mode, setMode] = useState<Venue>("paper");
  const q = useQuery({ queryKey: ["paper", mode, "account"], queryFn: () => api.paperAccount(mode) });
  const summary = useQuery({ queryKey: ["paper", mode, "summary"], queryFn: () => api.paperSummary(mode), enabled: q.data?.account != null });
  const [tab, setTab] = useState<Key>("overview");
  const d = q.data;
  const tabs: Tab<Key>[] = [
    { key: "overview", label: "Overview" },
    { key: "orders", label: "Orders", count: summary.data?.pending_orders || undefined },
    { key: "decisions", label: "Decisions" },
    { key: "settings", label: "Settings" },
  ];
  return (
    <VenueContext.Provider value={mode}>
    <div className="space-y-6">
      <PageHeader
        title={d?.account ? `Trading (${d.account.mode === "LIVE" ? "live" : "paper"})` : "Trading"}
        subtitle={d?.account?.mode === "LIVE" ? "Real money. You approve every order, and it is sent to Zerodha only while the live gate is open." : "Practise the strategy with pretend money. You approve every order, and nothing here places a real one."}
      />
      <Tabs tabs={[{ key: "paper", label: "Paper" }, { key: "live", label: "Live" }]} value={mode} onChange={(m) => { setMode(m); setTab("overview"); }} label="Account type" />
      {mode === "live" ? <LiveStatusPanel /> : null}
      {mode === "live" ? (
        <Alert tone="warn" title="Real money">
          Orders you approve are sent to your broker by the live process, only while live trading is allowed. The platform sells only shares it bought itself, never the ones you hold by hand.
        </Alert>
      ) : d?.account?.definition ? (
        <Alert tone="info" title="Passed the holdout">
          {d.account.definition} passed development and the 2025-2026 holdout. That is a screen, not proof: results from here on are the real test, and they show whether the plumbing works, not yet that it makes money.
        </Alert>
      ) : (
        <Alert tone="warn" title="Unvalidated research">
          This strategy has not passed validation. Results show whether the plumbing works, not that the strategy makes money.
        </Alert>
      )}
      {q.isError ? <Alert tone="error" title="Could not load your trading account">Try again in a moment.</Alert> : null}
      {q.isLoading ? <div role="status" aria-label="Loading your trading account"><Skeleton className="h-40 w-full" /></div> : null}
      {d && d.account === null ? (
        <>
          <p className="text-sm text-ink-soft">{mode === "live" ? "You have no live account yet. Set the capital the platform may use and pick a strategy that has been promoted to the LIVE stage." : "You have no paper account yet. Choose what the strategy should trade and start with some pretend cash."}</p>
          <SettingsForm key={mode} data={d} />
        </>
      ) : null}
      {d?.account ? (
        <>
          {d.account.attention ? <Alert tone="warn" title="Paused">{d.account.attention}. New orders are not proposed until an administrator clears this.</Alert> : null}
          {!d.account.enabled ? <Alert tone="info" title="Trading is off">No new orders are proposed. Turn it on in Settings.</Alert> : null}
          <Tabs tabs={tabs} value={tab} onChange={setTab} label="Trading sections" />
          {tab === "overview" ? <Overview /> : null}
          {tab === "orders" ? <OrdersPanel /> : null}
          {tab === "decisions" ? <Decisions /> : null}
          {tab === "settings" ? <SettingsForm key={mode} data={d} /> : null}
        </>
      ) : null}
    </div>
    </VenueContext.Provider>
  );
}
