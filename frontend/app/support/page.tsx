"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/status/Badge";
import { Card, ErrorBox, Loading } from "@/components/status/LoadState";
import { ticketTone } from "@/components/users/format";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/formatting";
import { PRIORITIES, TICKET_STATUSES } from "@/lib/schemas";

const PAGE = 25;
const input = "rounded-md border border-line bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100";

function NewTicket({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [priority, setPriority] = useState("NORMAL");
  const create = useMutation({
    mutationFn: () => api.createTicket(subject, body, priority),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["tickets"] });
      onDone();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <form onSubmit={submit} className="max-w-2xl space-y-3">
      <div className="space-y-1">
        <label htmlFor="t-subject" className="text-sm font-medium">Subject</label>
        <input id="t-subject" required maxLength={200} value={subject} onChange={(e) => setSubject(e.target.value)} className={`${input} w-full`} />
      </div>
      <div className="space-y-1">
        <label htmlFor="t-body" className="text-sm font-medium">What do you need help with?</label>
        <textarea id="t-body" required rows={5} maxLength={8000} value={body} onChange={(e) => setBody(e.target.value)} className={`${input} w-full`} />
      </div>
      <div className="space-y-1">
        <label htmlFor="t-priority" className="text-sm font-medium">Priority</label>
        <select id="t-priority" value={priority} onChange={(e) => setPriority(e.target.value)} className={input}>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>{p.charAt(0) + p.slice(1).toLowerCase()}</option>
          ))}
        </select>
      </div>
      {create.isError ? <p role="alert" className="text-sm text-red-700">{create.error instanceof ApiError ? create.error.message : "Could not send the ticket."}</p> : null}
      <div className="flex gap-2">
        <button type="submit" disabled={create.isPending} className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50">Send ticket</button>
        <button type="button" onClick={onDone} className="rounded-md border border-line px-3 py-2 text-sm hover:bg-slate-50">Cancel</button>
      </div>
    </form>
  );
}

export default function SupportPage() {
  const { can } = useAuth();
  const staff = can("tickets:manage");
  const [status, setStatus] = useState("");
  const [mine, setMine] = useState(false);
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const list = useQuery({ queryKey: ["tickets", status, mine, offset], queryFn: () => api.tickets({ status: status || undefined, mine, limit: PAGE, offset }), placeholderData: (prev) => prev });
  const total = list.data?.total ?? 0;
  return (
    <div className="space-y-4">
      <PageHeader
        title="Support"
        subtitle={staff ? "The support queue: every ticket, newest activity first." : "Ask for help and follow your requests."}
        actions={
          <button type="button" onClick={() => setCreating(true)} className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800">New ticket</button>
        }
      />
      {creating ? (
        <Card title="New ticket">
          <NewTicket onDone={() => setCreating(false)} />
        </Card>
      ) : null}
      <Card title={staff ? "Queue" : "Your tickets"}>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <label className="sr-only" htmlFor="ts">Status</label>
          <select id="ts" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className={input}>
            <option value="">All statuses</option>
            {TICKET_STATUSES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          {staff ? (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={mine} onChange={(e) => { setMine(e.target.checked); setOffset(0); }} /> Only tickets I raised
            </label>
          ) : null}
        </div>
        {list.isError ? <ErrorBox error={list.error} what="tickets" /> : null}
        {list.isLoading ? <Loading what="tickets" /> : null}
        <ul className="divide-y divide-line text-sm">
          {list.data?.items.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>
                <Link href={`/support/${t.id}`} className="font-medium text-blue-700 hover:underline">#{t.number} {t.subject}</Link>
                <span className="block text-xs text-ink-soft">
                  {staff ? `${t.requester} · ` : ""}
                  {t.assignee ? `assigned to ${t.assignee} · ` : staff ? "unassigned · " : ""}
                  updated {fmtDateTime(t.updated_at)}
                </span>
              </span>
              <span className="flex gap-2">
                {t.priority === "HIGH" ? <Badge tone="bad">High</Badge> : null}
                <Badge tone={ticketTone(t.status)}>{t.status}</Badge>
              </span>
            </li>
          ))}
        </ul>
        {list.data && total === 0 ? <p className="py-3 text-sm text-ink-soft">No tickets.</p> : null}
        {total > PAGE ? (
          <div className="mt-3 flex items-center justify-between text-xs text-ink-soft">
            <span>{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
            <span className="flex gap-2">
              <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="rounded border border-line px-2 py-1 disabled:opacity-40">Previous</button>
              <button type="button" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)} className="rounded border border-line px-2 py-1 disabled:opacity-40">Next</button>
            </span>
          </div>
        ) : null}
      </Card>
    </div>
  );
}
