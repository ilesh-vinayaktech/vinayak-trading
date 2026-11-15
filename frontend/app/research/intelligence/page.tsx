"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Card, ErrorBox, Loading, Stat } from "@/components/status/LoadState";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { inputFull } from "@/components/ui/styles";
import { api } from "@/lib/api/client";
import type { IntelAlpha, IntelNotes, IntelOverview } from "@/lib/schemas";

type Hypothesis = IntelAlpha["hypotheses"][number];
type Note = IntelNotes["notes"][number];

const day = (iso: string) => iso.replace("T", " ").slice(0, 16);
const num = (v: number | null, digits = 4) => (v === null ? "–" : v.toFixed(digits));
const pct = (v: number) => `${(v * 100).toFixed(1)}%`;
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
