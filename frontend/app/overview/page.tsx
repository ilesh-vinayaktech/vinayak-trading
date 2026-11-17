"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { ForecastPanel } from "@/components/market/ForecastPanel";
import { IndustriesPanel } from "@/components/market/IndustriesPanel";
import { NewsPanel } from "@/components/market/NewsPanel";
import { PositionsPanel } from "@/components/market/PositionsPanel";
import { SetupsPanel } from "@/components/market/SetupsPanel";
import { SectorPanel } from "@/components/market/SectorPanel";
import { ZonePanel } from "@/components/market/ZonePanel";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, Skeleton, type Column } from "@/components/ui/DataTable";
import { Icon } from "@/components/ui/Icon";
import { Panel, RelativeTime, StatCard, StatusPill } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { roleLabel, ticketPill } from "@/components/users/format";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtIst, fmtMoney } from "@/lib/formatting";
import type { MyDashboard, TicketStatus } from "@/lib/schemas";

const KITE: Record<MyDashboard["kite"]["state"], { text: string; tone: "good" | "warn" | "bad" | undefined; hint: string }> = {
  not_configured: { text: "Not set up", tone: undefined, hint: "Add your Kite Connect app to get started" },
  saved: { text: "Not connected", tone: "warn", hint: "Credentials saved. Connect to Zerodha for today" },
  connected: { text: "Connected", tone: "good", hint: "" },
  expired: { text: "Expired", tone: "bad", hint: "Zerodha sessions end at 06:00 IST. Connect again" },
};

function Step({ done, children, href }: { done: boolean; children: string; href: string }) {
  return (
    <li className="flex items-center gap-3 px-5 py-3 text-sm">
      <span className={`flex h-5 w-5 items-center justify-center rounded-full border ${done ? "border-emerald-600 bg-emerald-600 text-white" : "border-slate-300 text-transparent"}`}>
        <Icon name="check" size={12} />
      </span>
      <span className={done ? "text-ink-soft line-through" : "font-medium"}>{children}</span>
      {done ? <span className="sr-only">(done)</span> : <Link href={href} className="ml-auto text-sm font-medium text-brand hover:underline">Do this</Link>}
    </li>
  );
}

const columns: Column<MyDashboard["tickets"]["latest"][number]>[] = [
  { key: "no", header: "#", cell: (t) => <Link href={`/support/${t.ticket_id}`} className="font-medium text-brand hover:underline">#{t.number}</Link> },
  { key: "subject", header: "Subject", cell: (t) => t.subject },
  { key: "status", header: "Status", cell: (t) => <StatusPill tone={ticketPill(t.status as TicketStatus)}>{roleLabel(t.status)}</StatusPill> },
  { key: "updated", header: "Updated", hideBelow: "sm", cell: (t) => <span className="text-ink-soft"><RelativeTime iso={t.updated_at} /></span> },
];

export default function OverviewPage() {
  const { user, can } = useAuth();
  const q = useQuery({ queryKey: ["dashboard", "me"], queryFn: api.myDashboard });
  const d = q.data;
  const account = useQuery({ queryKey: ["broker", "account"], queryFn: api.brokerAccount, enabled: can("kite:own") && d?.kite.state === "connected" }); // only when Kite is connected: each read asks Kite
  const first = user?.name.split(" ")[0] ?? "";
  return (
    <div className="space-y-6">
      <PageHeader title={first ? `Welcome back, ${first}` : "Overview"} subtitle="Your connection, requests and account at a glance." actions={can("research:read") ? <Link href="/data/instruments" className={buttonClass("secondary")}>Open data explorer</Link> : null} />
      {can("research:read") ? (
        <>
          <ZonePanel />
          <ForecastPanel />
          <SetupsPanel />
          <PositionsPanel />
          <SectorPanel />
          <IndustriesPanel />
          <NewsPanel />
        </>
      ) : null}
      {q.isError ? <Alert tone="error" title="Could not load your overview">Try again in a moment.</Alert> : null}
      {q.isLoading ? <div role="status" aria-label="Loading your overview" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Skeleton className="h-28 w-full" /><Skeleton className="h-28 w-full" /><Skeleton className="h-28 w-full" /><Skeleton className="h-28 w-full" /></div> : null}
      {d ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {can("kite:own") ? (
              <StatCard label="Kite connection" value={KITE[d.kite.state].text} tone={KITE[d.kite.state].tone} href="/kite" hint={d.kite.state === "connected" && d.kite.token_expires_at ? `Until ${fmtIst(d.kite.token_expires_at)}` : KITE[d.kite.state].hint} />
            ) : null}
            {can("kite:own") && d.kite.state === "connected" ? (
              <StatCard
                label="Broker account"
                value={account.data?.state === "ok" && account.data.cash !== null ? `₹${fmtMoney(account.data.cash)}` : account.isLoading ? "Reading..." : "Not available"}
                tone={account.data && account.data.state !== "ok" ? "warn" : undefined}
                href="/broker"
                hint={account.data?.state === "ok" ? `Cash. ${account.data.holdings.length} holding${account.data.holdings.length === 1 ? "" : "s"} worth ₹${fmtMoney(account.data.totals.holdings_value, 0)}` : "Cash and holdings in Kite"}
              />
            ) : null}
            <StatCard label="Open requests" value={d.tickets.open} href="/support" hint={d.tickets.open === 0 ? "Nothing waiting" : "Support tickets you opened"} />
            {can("crm:read") ? <StatCard label="My follow-ups" value={d.tasks.open} href="/tasks" tone={d.tasks.overdue > 0 ? "bad" : undefined} hint={d.tasks.overdue > 0 ? `${d.tasks.overdue} overdue` : "None overdue"} /> : null}
            <StatCard label="Two-factor sign-in" value={d.security.mfa_enabled ? "On" : "Off"} tone={d.security.mfa_enabled ? "good" : "warn"} href="/account/security" hint={`${d.security.active_sessions} active session${d.security.active_sessions === 1 ? "" : "s"}`} />
          </div>
          <div className="grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <Panel title="Your open requests" actions={<Link href="/support" className="text-sm font-medium text-brand hover:underline">All requests</Link>}>
                <DataTable caption="Your open requests" columns={columns} rows={d.tickets.latest} rowKey={(t) => t.ticket_id} empty={<EmptyState icon="support" title="No open requests" action={<Link href="/support" className={buttonClass("secondary")}>Ask for help</Link>}>Anything you ask support for shows up here.</EmptyState>} />
              </Panel>
            </div>
            <Panel title="Get set up">
              <ul className="divide-y divide-line" aria-label="Setup checklist">
                <Step done={d.security.mfa_enabled} href="/account/security">Turn on two-factor sign-in</Step>
                {can("kite:own") ? <Step done={d.kite.state !== "not_configured"} href="/kite">Save your Kite Connect app</Step> : null}
                {can("kite:own") ? <Step done={d.kite.state === "connected"} href="/kite">Connect to Zerodha for today</Step> : null}
              </ul>
            </Panel>
          </div>
        </>
      ) : null}
    </div>
  );
}
