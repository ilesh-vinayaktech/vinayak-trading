"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, Pagination, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Icon } from "@/components/ui/Icon";
import { Panel, RelativeTime, StatusPill, Tabs, type Tab } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ticketPill } from "@/components/users/format";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { PRIORITIES, type TicketRow } from "@/lib/schemas";

const PAGE = 25;
const cap = (s: string) => s.charAt(0) + s.slice(1).toLowerCase();
type Filter = "ALL" | "OPEN" | "PENDING" | "RESOLVED" | "CLOSED";
const TABS: Tab<Filter>[] = [{ key: "ALL", label: "All" }, { key: "OPEN", label: "Open" }, { key: "PENDING", label: "Pending" }, { key: "RESOLVED", label: "Resolved" }, { key: "CLOSED", label: "Closed" }];

function NewTicketDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [priority, setPriority] = useState("NORMAL");
  const create = useMutation({
    mutationFn: () => api.createTicket(subject, body, priority),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: ["tickets"] });
      toast.success(`Ticket #${r.number} created.`);
      setSubject("");
      setBody("");
      setPriority("NORMAL");
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New ticket"
      description="Tell us what you need. We reply here and your ticket stays open until it is resolved."
      footer={
        <>
          <button type="button" onClick={onClose} className={buttonClass("secondary")}>Cancel</button>
          <button type="submit" form="ticket-form" disabled={create.isPending} className={buttonClass("primary")}>Send ticket</button>
        </>
      }
    >
      <form id="ticket-form" onSubmit={submit} className="space-y-4">
        {create.isError ? <Alert tone="error">{create.error instanceof ApiError ? create.error.message : "Could not send the ticket."}</Alert> : null}
        <Field id="t-subject" label="Subject">
          <input id="t-subject" required maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} className={inputFull} />
        </Field>
        <Field id="t-body" label="What do you need help with?">
          <textarea id="t-body" required rows={5} maxLength={8000} value={body} onChange={(e) => setBody(e.target.value)} className={inputFull} />
        </Field>
        <Field id="t-priority" label="Priority">
          <select id="t-priority" value={priority} onChange={(e) => setPriority(e.target.value)} className={inputFull}>
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>{cap(p)}</option>
            ))}
          </select>
        </Field>
      </form>
    </Dialog>
  );
}

export default function SupportPage() {
  const { can } = useAuth();
  const staff = can("tickets:manage");
  const [filter, setFilter] = useState<Filter>("ALL");
  const [mine, setMine] = useState(false);
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const list = useQuery({ queryKey: ["tickets", filter, mine, offset], queryFn: () => api.tickets({ status: filter === "ALL" ? undefined : filter, mine, limit: PAGE, offset }), placeholderData: (prev) => prev });
  const total = list.data?.total ?? 0;
  const columns: Column<TicketRow>[] = [
    {
      key: "ticket",
      header: "Ticket",
      cell: (t) => (
        <Link href={`/support/${t.id}`} className="block min-w-0">
          <span className="block truncate font-medium text-blue-700 hover:underline">#{t.number} {t.subject}</span>
          <span className="block truncate text-xs text-ink-soft">{staff ? `${t.requester} · ` : ""}opened <RelativeTime iso={t.created_at} /></span>
        </Link>
      ),
    },
    { key: "status", header: "Status", cell: (t) => <StatusPill tone={ticketPill(t.status)}>{cap(t.status)}</StatusPill> },
    { key: "priority", header: "Priority", hideBelow: "sm", cell: (t) => (t.priority === "HIGH" ? <StatusPill tone="bad">High</StatusPill> : <span className="text-ink-soft">{cap(t.priority)}</span>) },
    ...(staff ? [{ key: "assignee", header: "Assignee", hideBelow: "md" as const, cell: (t: TicketRow) => (t.assignee ? t.assignee : <span className="text-ink-faint">Unassigned</span>) }] : []),
    { key: "updated", header: "Updated", hideBelow: "md", cell: (t) => <span className="text-ink-soft"><RelativeTime iso={t.updated_at} /></span> },
  ];
  return (
    <div>
      <PageHeader
        title="Support"
        subtitle={staff ? "The support queue: every ticket, most recent activity first." : "Ask for help and follow your requests."}
        actions={
          <button type="button" onClick={() => setCreating(true)} className={buttonClass("primary")}>
            <Icon name="support" size={16} /> New ticket
          </button>
        }
      />
      <NewTicketDialog open={creating} onClose={() => setCreating(false)} />
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 pt-1">
          <Tabs tabs={TABS} value={filter} onChange={(k) => { setFilter(k); setOffset(0); }} label="Ticket status" />
          {staff ? (
            <label className="flex items-center gap-2 text-sm text-ink-soft">
              <input type="checkbox" checked={mine} onChange={(e) => { setMine(e.target.checked); setOffset(0); }} /> Only tickets I raised
            </label>
          ) : null}
        </div>
        {list.isError ? (
          <div className="p-5"><Alert tone="error">{list.error instanceof ApiError ? `${list.error.status}: ${list.error.message}` : "Could not load tickets."}</Alert></div>
        ) : (
          <DataTable
            caption="Tickets"
            columns={columns}
            rows={list.data?.items}
            rowKey={(t) => t.id}
            loading={list.isLoading}
            empty={<EmptyState icon="support" title="No tickets" action={<button type="button" onClick={() => setCreating(true)} className={buttonClass("secondary")}>New ticket</button>}>{filter === "ALL" ? "Nothing here yet." : `No ${filter.toLowerCase()} tickets.`}</EmptyState>}
          />
        )}
        <Pagination offset={offset} pageSize={PAGE} total={total} onChange={setOffset} />
      </Panel>
    </div>
  );
}
