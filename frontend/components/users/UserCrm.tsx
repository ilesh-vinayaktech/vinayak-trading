"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Badge } from "@/components/status/Badge";
import { Card } from "@/components/status/LoadState";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/formatting";
import { buttonClass, inputClass } from "@/components/ui/styles";

const input = inputClass;
const button = buttonClass("primary");
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");

/** Staff-only panels on a user's profile: tags, internal notes and follow-up tasks. The person they are about never sees them. */
export function UserCrm({ userId, tags }: { userId: string; tags: string[] }) {
  const { can } = useAuth();
  const qc = useQueryClient();
  const write = can("crm:write");
  const [tag, setTag] = useState("");
  const [note, setNote] = useState("");
  const [title, setTitle] = useState("");
  const [owner, setOwner] = useState("");
  const [due, setDue] = useState("");
  const refreshUser = () => {
    void qc.invalidateQueries({ queryKey: ["user", userId] });
    void qc.invalidateQueries({ queryKey: ["users"] });
    void qc.invalidateQueries({ queryKey: ["tags"] });
  };
  const notes = useQuery({ queryKey: ["notes", userId], queryFn: () => api.notes(userId) });
  const tasks = useQuery({ queryKey: ["tasks", "user", userId], queryFn: () => api.tasks({ user_id: userId }) });
  const staff = useQuery({ queryKey: ["staff"], queryFn: api.staff, enabled: write });
  const addTag = useMutation({ mutationFn: () => api.addTag(userId, tag), onSuccess: () => { setTag(""); refreshUser(); } });
  const dropTag = useMutation({ mutationFn: (t: string) => api.removeTag(userId, t), onSuccess: refreshUser });
  const addNote = useMutation({ mutationFn: () => api.addNote(userId, note), onSuccess: () => { setNote(""); void qc.invalidateQueries({ queryKey: ["notes", userId] }); } });
  const addTask = useMutation({
    mutationFn: () => api.createTask({ title, detail: "", owner_id: owner || (staff.data?.staff[0]?.id ?? ""), user_id: userId, due_date: due || undefined }),
    onSuccess: () => { setTitle(""); setDue(""); void qc.invalidateQueries({ queryKey: ["tasks"] }); },
  });
  const done = useMutation({ mutationFn: ({ id, status }: { id: string; status: string }) => api.setTaskStatus(id, status), onSuccess: () => void qc.invalidateQueries({ queryKey: ["tasks"] }) });
  const submit = (fn: () => void) => (e: FormEvent) => {
    e.preventDefault();
    fn();
  };
  const err = addTag.error ?? dropTag.error ?? addNote.error ?? addTask.error ?? done.error;

  return (
    <>
      <Card title="Tags" note="Labels for staff to filter the directory by. Not visible to the user.">
        <div className="mb-3 flex flex-wrap gap-2" aria-label="Tags of this user">
          {tags.length === 0 ? <span className="text-sm text-ink-soft">No tags.</span> : null}
          {tags.map((t) => (
            <span key={t} className="inline-flex items-center gap-1">
              <Badge>{t}</Badge>
              {write ? (
                <button type="button" aria-label={`Remove tag ${t}`} onClick={() => dropTag.mutate(t)} className="text-xs text-ink-soft hover:text-red-700">×</button>
              ) : null}
            </span>
          ))}
        </div>
        {write ? (
          <form onSubmit={submit(() => addTag.mutate())} className="flex gap-2">
            <label htmlFor="new-tag" className="sr-only">New tag</label>
            <input id="new-tag" placeholder="e.g. kyc pending" value={tag} onChange={(e) => setTag(e.target.value)} className={`${input} w-56`} required />
            <button type="submit" disabled={addTag.isPending} className={button}>Add tag</button>
          </form>
        ) : null}
      </Card>

      <Card title="Internal notes" note="Only staff can read these.">
        {write ? (
          <form onSubmit={submit(() => addNote.mutate())} className="mb-3 space-y-2">
            <label htmlFor="new-note" className="sr-only">New note</label>
            <textarea id="new-note" rows={3} required maxLength={4000} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What happened, what was agreed" className={`${input} w-full max-w-2xl`} />
            <button type="submit" disabled={addNote.isPending} className={button}>Add note</button>
          </form>
        ) : null}
        <ul className="divide-y divide-line text-sm">
          {notes.data?.notes.map((n) => (
            <li key={n.id} className="py-2">
              <p className="whitespace-pre-wrap">{n.body}</p>
              <p className="text-xs text-ink-soft">{n.author} · {fmtDateTime(n.created_at)}</p>
            </li>
          ))}
        </ul>
        {notes.data && notes.data.notes.length === 0 ? <p className="text-sm text-ink-soft">No notes yet.</p> : null}
      </Card>

      <Card title="Follow-up tasks">
        {write ? (
          <form onSubmit={submit(() => addTask.mutate())} className="mb-3 flex flex-wrap items-end gap-2">
            <div className="space-y-1">
              <label htmlFor="task-title" className="text-sm font-medium">Task</label>
              <input id="task-title" required maxLength={200} value={title} onChange={(e) => setTitle(e.target.value)} className={`${input} w-64`} />
            </div>
            <div className="space-y-1">
              <label htmlFor="task-owner" className="text-sm font-medium">Owner</label>
              <select id="task-owner" value={owner} onChange={(e) => setOwner(e.target.value)} className={input}>
                {staff.data?.staff.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1">
              <label htmlFor="task-due" className="text-sm font-medium">Due</label>
              <input id="task-due" type="date" value={due} onChange={(e) => setDue(e.target.value)} className={input} />
            </div>
            <button type="submit" disabled={addTask.isPending} className={button}>Add task</button>
          </form>
        ) : null}
        <ul className="divide-y divide-line text-sm">
          {tasks.data?.tasks.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>
                <span className={t.status === "DONE" ? "text-ink-soft line-through" : "font-medium"}>{t.title}</span>
                <span className="text-xs text-ink-soft"> · {t.owner}{t.due_date ? ` · due ${t.due_date}` : ""}</span>
              </span>
              {write ? (
                <button type="button" onClick={() => done.mutate({ id: t.id, status: t.status === "DONE" ? "OPEN" : "DONE" })} className={buttonClass("secondary", true)}>
                  {t.status === "DONE" ? "Reopen" : "Mark done"}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
        {tasks.data && tasks.data.tasks.length === 0 ? <p className="text-sm text-ink-soft">No tasks about this user.</p> : null}
      </Card>
      {err ? <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{message(err)}</p> : null}
    </>
  );
}
