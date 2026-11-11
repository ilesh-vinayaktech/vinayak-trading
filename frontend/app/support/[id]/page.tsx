"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/status/Badge";
import { Card, ErrorBox, Loading } from "@/components/status/LoadState";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { ticketTone } from "@/components/users/format";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/formatting";
import { TICKET_STATUSES } from "@/lib/schemas";

const input = "rounded-md border border-line bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100";
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");

export default function TicketPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const staff = can("tickets:manage");
  const qc = useQueryClient();
  const [body, setBody] = useState("");
  const [internal, setInternal] = useState(false);
  const ticket = useQuery({ queryKey: ["ticket", id], queryFn: () => api.ticket(id) });
  const people = useQuery({ queryKey: ["staff"], queryFn: api.staff, enabled: staff });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["ticket", id] });
    void qc.invalidateQueries({ queryKey: ["tickets"] });
  };
  const reply = useMutation({ mutationFn: () => api.replyTicket(id, body, internal), onSuccess: () => { setBody(""); setInternal(false); refresh(); } });
  const status = useMutation({ mutationFn: (s: string) => api.setTicketStatus(id, s), onSuccess: refresh });
  const assign = useMutation({ mutationFn: (who: string | null) => api.assignTicket(id, who), onSuccess: refresh });
  const t = ticket.data;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    reply.mutate();
  };
  if (ticket.isLoading) return <Loading what="ticket" />;
  if (ticket.isError || !t) return <ErrorBox error={ticket.error} what="this ticket" />;
  const err = reply.error ?? status.error ?? assign.error;
  return (
    <div className="space-y-4">
      <PageHeader
        title={`#${t.number} ${t.subject}`}
        subtitle={`${staff ? `${t.requester} · ` : ""}opened ${fmtDateTime(t.created_at)}`}
        actions={
          <div className="flex items-center gap-2">
            <Badge tone={ticketTone(t.status)}>{t.status}</Badge>
            {t.priority === "HIGH" ? <Badge tone="bad">High</Badge> : null}
            <Link href="/support" className="text-sm text-blue-700 hover:underline">All tickets</Link>
          </div>
        }
      />
      {err ? <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{message(err)}</p> : null}

      {staff ? (
        <Card title="Handle">
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1">
              <label htmlFor="assignee" className="text-sm font-medium">Assigned to</label>
              <select id="assignee" value={t.assignee_id ?? ""} onChange={(e) => assign.mutate(e.target.value || null)} className={`${input} block`}>
                <option value="">Unassigned</option>
                {people.data?.staff.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label htmlFor="tstatus" className="text-sm font-medium">Status</label>
              <select id="tstatus" value={t.status} onChange={(e) => status.mutate(e.target.value)} className={`${input} block`}>
                {TICKET_STATUSES.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
          </div>
        </Card>
      ) : null}

      <Card title="Conversation">
        <ol className="space-y-3">
          {t.messages.map((m) => (
            <li key={m.id} className={`rounded-md border p-3 text-sm ${m.internal ? "border-amber-200 bg-amber-50" : m.mine ? "border-blue-100 bg-blue-50" : "border-line bg-white"}`}>
              <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-ink-soft">
                <span className="font-medium text-ink">{m.author}</span>
                <span>{fmtDateTime(m.created_at)}</span>
                {m.internal ? <Badge tone="warn">Internal note</Badge> : null}
              </div>
              <p className="whitespace-pre-wrap">{m.body}</p>
            </li>
          ))}
        </ol>
      </Card>

      {t.status === "CLOSED" ? (
        <p className="text-sm text-ink-soft">This ticket is closed. Raise a new ticket if you still need help.</p>
      ) : (
        <Card title="Reply">
          <form onSubmit={submit} className="space-y-3">
            <label htmlFor="reply" className="sr-only">Your reply</label>
            <textarea id="reply" rows={4} required maxLength={8000} value={body} onChange={(e) => setBody(e.target.value)} className={`${input} w-full max-w-2xl`} />
            {staff ? (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> Internal note (the requester will not see it)
              </label>
            ) : null}
            <div className="flex flex-wrap gap-2">
              <button type="submit" disabled={reply.isPending} className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50">{internal ? "Add internal note" : "Send reply"}</button>
              {!staff ? (
                <ConfirmButton question="Close this ticket?" confirmLabel="Close" onConfirm={() => status.mutate("CLOSED")}>Close ticket</ConfirmButton>
              ) : null}
            </div>
          </form>
        </Card>
      )}
    </div>
  );
}
