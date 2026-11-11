"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert, Avatar } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Field } from "@/components/ui/Field";
import { DefinitionList, Panel, RelativeTime, StatusPill } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { ticketPill } from "@/components/users/format";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { TICKET_STATUSES } from "@/lib/schemas";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");
const cap = (s: string) => s.charAt(0) + s.slice(1).toLowerCase();

export default function TicketPage() {
  const { id } = useParams<{ id: string }>();
  const { can } = useAuth();
  const toast = useToast();
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
  const reply = useMutation({ mutationFn: () => api.replyTicket(id, body, internal), onSuccess: () => { toast.success(internal ? "Internal note added." : "Reply sent."); setBody(""); setInternal(false); refresh(); } });
  const status = useMutation({ mutationFn: (s: string) => api.setTicketStatus(id, s), onSuccess: (_d, s) => { toast.success(`Ticket ${s.toLowerCase()}.`); refresh(); } });
  const assign = useMutation({ mutationFn: (who: string | null) => api.assignTicket(id, who), onSuccess: () => { toast.success("Assignment updated."); refresh(); } });
  const t = ticket.data;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    reply.mutate();
  };
  if (ticket.isLoading) {
    return (
      <div role="status" aria-label="Loading ticket" className="space-y-4">
        <Skeleton className="h-8 w-80" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }
  if (ticket.isError || !t) {
    return <Alert tone="error" title="Could not load this ticket">{ticket.error instanceof ApiError ? `${ticket.error.status}: ${ticket.error.message}` : String(ticket.error)}</Alert>;
  }
  const err = reply.error ?? status.error ?? assign.error;
  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Support", href: "/support" }, { label: `#${t.number}` }]}
        title={`#${t.number} ${t.subject}`}
        subtitle={`${staff ? `${t.requester} · ` : ""}opened ${new Date(t.created_at).toISOString().slice(0, 10)}`}
        actions={
          <>
            <StatusPill tone={ticketPill(t.status)}>{cap(t.status)}</StatusPill>
            {t.priority === "HIGH" ? <StatusPill tone="bad">High priority</StatusPill> : null}
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-5 lg:col-span-2">
          {err ? <Alert tone="error">{message(err)}</Alert> : null}
          <Panel title="Conversation">
            <ol className="space-y-4 p-5">
              {t.messages.map((m) => (
                <li key={m.id} className="flex gap-3">
                  <Avatar name={m.author} />
                  <div className={`min-w-0 flex-1 rounded-xl border px-4 py-3 text-sm ${m.internal ? "border-amber-200 bg-amber-50" : m.mine ? "border-blue-100 bg-blue-50/60" : "border-line bg-white"}`}>
                    <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-ink-soft">
                      <span className="font-medium text-ink">{m.author}</span>
                      <RelativeTime iso={m.created_at} />
                      {m.internal ? <StatusPill tone="warn">Internal note</StatusPill> : null}
                    </div>
                    <p className="whitespace-pre-wrap leading-relaxed">{m.body}</p>
                  </div>
                </li>
              ))}
            </ol>
          </Panel>

          {t.status === "CLOSED" ? (
            <Alert tone="info">This ticket is closed. Raise a new ticket if you still need help.</Alert>
          ) : (
            <Panel title="Reply">
              <form onSubmit={submit} className="space-y-3 p-5">
                <label htmlFor="reply" className="sr-only">Your reply</label>
                <textarea id="reply" rows={4} required maxLength={8000} value={body} onChange={(e) => setBody(e.target.value)} placeholder={internal ? "Visible to staff only" : "Write your reply"} className={`${inputFull} ${internal ? "border-amber-300 bg-amber-50/40" : ""}`} />
                {staff ? (
                  <label className="flex items-center gap-2 text-sm text-ink-soft">
                    <input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> Internal note (the requester will not see it)
                  </label>
                ) : null}
                <div className="flex flex-wrap gap-2">
                  <button type="submit" disabled={reply.isPending} className={buttonClass("primary")}>{internal ? "Add internal note" : "Send reply"}</button>
                  {!staff ? <ConfirmButton question="Close this ticket?" confirmLabel="Close" onConfirm={() => status.mutate("CLOSED")}>Close ticket</ConfirmButton> : null}
                </div>
              </form>
            </Panel>
          )}
        </div>

        <aside className="space-y-5">
          <Panel title="Details">
            <div className="px-5 py-2">
              <DefinitionList
                items={[
                  { label: "Requester", value: t.requester },
                  { label: "Assignee", value: t.assignee ?? "Unassigned" },
                  { label: "Priority", value: cap(t.priority) },
                  { label: "Opened", value: <RelativeTime iso={t.created_at} /> },
                  { label: "Last activity", value: <RelativeTime iso={t.updated_at} /> },
                ]}
              />
            </div>
          </Panel>
          {staff ? (
            <Panel title="Handle">
              <div className="space-y-4 p-5">
                <Field id="assignee" label="Assigned to">
                  <select id="assignee" value={t.assignee_id ?? ""} onChange={(e) => assign.mutate(e.target.value || null)} className={inputFull}>
                    <option value="">Unassigned</option>
                    {people.data?.staff.map((s) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </select>
                </Field>
                <Field id="tstatus" label="Status">
                  <select id="tstatus" value={t.status} onChange={(e) => status.mutate(e.target.value)} className={inputFull}>
                    {TICKET_STATUSES.map((s) => (
                      <option key={s} value={s}>{cap(s)}</option>
                    ))}
                  </select>
                </Field>
              </div>
            </Panel>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
