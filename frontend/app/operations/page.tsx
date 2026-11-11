"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { DataTable, Skeleton, type Column } from "@/components/ui/DataTable";
import { Panel, RelativeTime, StatCard, StatusPill } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { roleLabel } from "@/components/users/format";
import { api } from "@/lib/api/client";
import { fmtIst } from "@/lib/formatting";
import type { OpsDashboard } from "@/lib/schemas";

const ROLE_ORDER = ["ADMIN", "OPERATOR", "TRADER", "VIEWER"];
const sum = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0);
const feedState = (f: OpsDashboard["kite"]["feed"]): { text: string; tone: "good" | "warn" | "bad"; hint: string } =>
  f === null
    ? { text: "No feed", tone: "bad", hint: "No connection is the data feed. Set one on the Kite page." }
    : f.state === "connected"
      ? { text: "Live", tone: "good", hint: `${f.owner}${f.token_expires_at ? `, until ${fmtIst(f.token_expires_at)}` : ""}` }
      : { text: f.state === "expired" ? "Expired" : "Not connected", tone: "bad", hint: `${f.owner} needs to connect to Zerodha` };

const columns: Column<OpsDashboard["recent"][number]>[] = [
  { key: "when", header: "When", cell: (e) => <span className="whitespace-nowrap text-ink-soft"><RelativeTime iso={e.at} /></span> },
  { key: "who", header: "Who", cell: (e) => e.actor },
  { key: "action", header: "Action", cell: (e) => <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs">{e.action}</code> },
];

export default function OperationsPage() {
  const q = useQuery({ queryKey: ["dashboard", "operations"], queryFn: api.opsDashboard, refetchInterval: 30_000 });
  const d = q.data;
  const feed = d ? feedState(d.kite.feed) : null;
  return (
    <div className="space-y-6">
      <PageHeader title="Operations" subtitle="What needs attention across the platform. It refreshes every 30 seconds." actions={<Link href="/dashboard" className={buttonClass("secondary")}>Data health</Link>} />
      {q.isError ? <Alert tone="error" title="Could not load operations">Try again in a moment.</Alert> : null}
      {q.isLoading ? <div role="status" aria-label="Loading operations" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Skeleton className="h-28 w-full" /><Skeleton className="h-28 w-full" /><Skeleton className="h-28 w-full" /><Skeleton className="h-28 w-full" /></div> : null}
      {d && feed ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Data feed" value={feed.text} tone={feed.tone} href="/kite" hint={feed.hint} />
            <StatCard label="Kite connections today" value={d.kite.connected} hint="Users connected to Zerodha now" />
            <StatCard label="Sign-ins, last 24 hours" value={d.signins.successes_24h} tone={d.signins.failures_24h > 0 ? "warn" : undefined} href="/audit" hint={`${d.signins.failures_24h} failed`} />
            <StatCard label="Users" value={sum(d.users.by_status)} href="/users" hint={Object.entries(d.users.by_status).map(([k, n]) => `${n} ${k.toLowerCase()}`).join(", ")} />
            <StatCard label="Open tickets" value={d.tickets.open} href="/support" tone={d.tickets.unassigned > 0 ? "warn" : undefined} hint={`${d.tickets.unassigned} unassigned`} />
            <StatCard label="Open follow-ups" value={d.tasks.open} href="/tasks" tone={d.tasks.overdue > 0 ? "bad" : undefined} hint={`${d.tasks.overdue} overdue`} />
          </div>
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <Panel title="Recent activity" actions={<Link href="/audit" className="text-sm font-medium text-brand hover:underline">Audit log</Link>}>
                <DataTable caption="Recent activity" columns={columns} rows={d.recent} rowKey={(e) => String(e.id)} empty="No activity yet." />
              </Panel>
            </div>
            <Panel title="Users by role">
              <ul className="divide-y divide-line text-sm" aria-label="Users by role">
                {ROLE_ORDER.filter((r) => r in d.users.by_role).map((role) => [role, d.users.by_role[role]] as const).map(([role, n]) => (
                  <li key={role} className="flex items-center justify-between px-5 py-3"><span>{roleLabel(role)}</span><StatusPill tone="neutral">{n}</StatusPill></li>
                ))}
              </ul>
            </Panel>
          </div>
        </>
      ) : null}
    </div>
  );
}
