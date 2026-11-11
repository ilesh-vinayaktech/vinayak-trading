"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Panel, StatusPill, Tabs, type Tab } from "@/components/ui/Layout";
import { buttonClass, inputClass } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import type { Task } from "@/lib/schemas";

type Status = "OPEN" | "DONE" | "ALL";
const TABS: Tab<Status>[] = [{ key: "OPEN", label: "Open" }, { key: "DONE", label: "Done" }, { key: "ALL", label: "All" }];

export default function TasksPage() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [status, setStatus] = useState<Status>("OPEN");
  const tasks = useQuery({ queryKey: ["tasks", scope, status], queryFn: () => api.tasks({ mine: scope === "mine", status: status === "ALL" ? undefined : status }) });
  const toggle = useMutation({
    mutationFn: ({ id, to }: { id: string; to: string }) => api.setTaskStatus(id, to),
    onSuccess: (_d, v) => {
      toast.success(v.to === "DONE" ? "Task marked done." : "Task reopened.");
      void qc.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
  const today = new Date().toISOString().slice(0, 10);
  const columns: Column<Task>[] = [
    {
      key: "task",
      header: "Task",
      cell: (t) => (
        <span className="block min-w-0">
          <span className={`block ${t.status === "DONE" ? "text-ink-soft line-through" : "font-medium"}`}>{t.title}</span>
          {t.about && t.about_id ? <span className="block text-xs text-ink-soft">About <Link href={`/users/${t.about_id}`} className="text-blue-700 hover:underline">{t.about}</Link></span> : null}
        </span>
      ),
    },
    { key: "owner", header: "Owner", hideBelow: "sm", cell: (t) => t.owner },
    {
      key: "due",
      header: "Due",
      cell: (t) => (t.due_date ? <span className="flex items-center gap-2">{t.due_date}{t.status === "OPEN" && t.due_date < today ? <StatusPill tone="bad">overdue</StatusPill> : null}</span> : <span className="text-ink-faint">No date</span>),
    },
    {
      key: "action",
      header: "",
      className: "text-right",
      cell: (t) =>
        can("crm:write") ? (
          <button type="button" onClick={() => toggle.mutate({ id: t.id, to: t.status === "DONE" ? "OPEN" : "DONE" })} className={buttonClass("secondary", true)}>
            {t.status === "DONE" ? "Reopen" : "Mark done"}
          </button>
        ) : null,
    },
  ];
  return (
    <div>
      <PageHeader title="Tasks" subtitle="Follow-ups for staff. Add them from a user's profile so they stay attached to the person." />
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3 px-4 pt-1">
          <Tabs tabs={TABS} value={status} onChange={setStatus} label="Task status" />
          <div className="pb-1">
            <label className="sr-only" htmlFor="scope">Whose tasks</label>
            <select id="scope" value={scope} onChange={(e) => setScope(e.target.value as "mine" | "all")} className={inputClass}>
              <option value="mine">Assigned to me</option>
              <option value="all">Everyone&apos;s</option>
            </select>
          </div>
        </div>
        {tasks.isError ? (
          <div className="p-5"><Alert tone="error">{tasks.error instanceof ApiError ? `${tasks.error.status}: ${tasks.error.message}` : "Could not load tasks."}</Alert></div>
        ) : (
          <DataTable caption="Tasks" columns={columns} rows={tasks.data?.tasks} rowKey={(t) => t.id} loading={tasks.isLoading} empty={<EmptyState icon="tasks" title="Nothing here">{status === "OPEN" ? "No open tasks. Add follow-ups from a user's profile." : "No tasks match."}</EmptyState>} />
        )}
      </Panel>
    </div>
  );
}
