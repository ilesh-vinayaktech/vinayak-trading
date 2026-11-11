"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Panel, RelativeTime, Tabs, type Tab } from "@/components/ui/Layout";
import { ApiError, api } from "@/lib/api/client";
import type { AuditEvent } from "@/lib/schemas";

type Kind = "" | "auth." | "user." | "kite." | "ticket." | "crm.";
const TABS: Tab<Kind>[] = [{ key: "", label: "Everything" }, { key: "auth.", label: "Sign-in & security" }, { key: "user.", label: "User administration" }, { key: "kite.", label: "Kite" }, { key: "ticket.", label: "Support" }, { key: "crm.", label: "CRM" }];

const columns: Column<AuditEvent>[] = [
  { key: "when", header: "When", cell: (e) => <span className="whitespace-nowrap text-ink-soft"><RelativeTime iso={e.at} /></span> },
  { key: "who", header: "Who", cell: (e) => e.actor },
  { key: "action", header: "Action", cell: (e) => <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs">{e.action}</code> },
  { key: "ip", header: "Address", hideBelow: "md", cell: (e) => <span className="text-ink-soft">{e.ip ?? ""}</span> },
];

export default function AuditPage() {
  const [kind, setKind] = useState<Kind>("");
  const events = useQuery({ queryKey: ["audit", kind], queryFn: () => api.audit({ action: kind || undefined, limit: 100 }) });
  return (
    <div>
      <PageHeader title="Audit log" subtitle="Every sign-in, access change and security event, newest first. It is append-only: entries cannot be edited or erased." />
      <Panel>
        <div className="px-4 pt-1">
          <Tabs tabs={TABS} value={kind} onChange={setKind} label="Event type" />
        </div>
        {events.isError ? (
          <div className="p-5"><Alert tone="error">{events.error instanceof ApiError ? `${events.error.status}: ${events.error.message}` : "Could not load the audit log."}</Alert></div>
        ) : (
          <DataTable caption="Audit events" columns={columns} rows={events.data?.events} rowKey={(e) => String(e.id)} loading={events.isLoading} empty={<EmptyState icon="scroll" title="No events">Nothing recorded for this filter yet.</EmptyState>} />
        )}
      </Panel>
    </div>
  );
}
