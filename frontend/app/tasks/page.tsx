"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/status/Badge";
import { Card, ErrorBox, Loading } from "@/components/status/LoadState";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";

const input = "rounded-md border border-line bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100";

export default function TasksPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [status, setStatus] = useState("OPEN");
  const tasks = useQuery({ queryKey: ["tasks", scope, status], queryFn: () => api.tasks({ mine: scope === "mine", status: status || undefined }) });
  const toggle = useMutation({ mutationFn: ({ id, to }: { id: string; to: string }) => api.setTaskStatus(id, to), onSuccess: () => void qc.invalidateQueries({ queryKey: ["tasks"] }) });
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div className="space-y-4">
      <PageHeader title="Tasks" subtitle="Follow-ups for staff. Add them from a user's profile so they stay attached to the person." />
      <Card title="Work list">
        <div className="mb-3 flex flex-wrap gap-2">
          <label className="sr-only" htmlFor="scope">Whose tasks</label>
          <select id="scope" value={scope} onChange={(e) => setScope(e.target.value as "mine" | "all")} className={input}>
            <option value="mine">Assigned to me</option>
            <option value="all">Everyone&apos;s</option>
          </select>
          <label className="sr-only" htmlFor="tstatus">Status</label>
          <select id="tstatus" value={status} onChange={(e) => setStatus(e.target.value)} className={input}>
            <option value="OPEN">Open</option>
            <option value="DONE">Done</option>
            <option value="">All</option>
          </select>
        </div>
        {tasks.isError ? <ErrorBox error={tasks.error} what="tasks" /> : null}
        {tasks.isLoading ? <Loading what="tasks" /> : null}
        <ul className="divide-y divide-line text-sm">
          {tasks.data?.tasks.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>
                <span className={t.status === "DONE" ? "text-ink-soft line-through" : "font-medium"}>{t.title}</span>
                {t.due_date && t.status === "OPEN" && t.due_date < today ? <> <Badge tone="bad">overdue</Badge></> : null}
                <span className="block text-xs text-ink-soft">
                  {t.owner}
                  {t.due_date ? ` · due ${t.due_date}` : ""}
                  {t.about && t.about_id ? <> · about <Link href={`/users/${t.about_id}`} className="text-blue-700 hover:underline">{t.about}</Link></> : null}
                </span>
              </span>
              {can("crm:write") ? (
                <button type="button" onClick={() => toggle.mutate({ id: t.id, to: t.status === "DONE" ? "OPEN" : "DONE" })} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-slate-50">
                  {t.status === "DONE" ? "Reopen" : "Mark done"}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
        {tasks.data && tasks.data.tasks.length === 0 ? <p className="py-3 text-sm text-ink-soft">Nothing here.</p> : null}
      </Card>
    </div>
  );
}
