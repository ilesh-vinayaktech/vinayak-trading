"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState, type ReactNode } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert, Avatar } from "@/components/ui/Alert";
import { EmptyState, Skeleton } from "@/components/ui/DataTable";
import { Field } from "@/components/ui/Field";
import { DefinitionList, Panel, RelativeTime, StatusPill, Tabs } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { CopyLink } from "@/components/users/CopyLink";
import { actionLabel, roleLabel, statusPill } from "@/components/users/format";
import { UserCrm } from "@/components/users/UserCrm";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { ROLES } from "@/lib/schemas";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");
type TabKey = "access" | "crm" | "activity";

function ActionRow({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 py-4 first:pt-0 last:pb-0">
      <div className="min-w-0 max-w-md">
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-0.5 text-sm text-ink-soft">{description}</p>
      </div>
      {children}
    </div>
  );
}

export default function UserProfile() {
  const { id } = useParams<{ id: string }>();
  const { user: me, can } = useAuth();
  const qc = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<TabKey>("access");
  const detail = useQuery({ queryKey: ["user", id], queryFn: () => api.user(id) });
  const activity = useQuery({ queryKey: ["user-activity", id], queryFn: () => api.audit({ target_type: "user", target_id: id, limit: 30 }) });
  const [name, setName] = useState<string | null>(null);
  const [link, setLink] = useState<{ label: string; url: string } | null>(null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["user", id] });
    void qc.invalidateQueries({ queryKey: ["user-activity", id] });
    void qc.invalidateQueries({ queryKey: ["users"] });
  };
  const act = useMutation({
    mutationFn: async (fn: () => Promise<string | null>) => fn(),
    onSuccess: (msg) => {
      if (msg) toast.success(msg);
      refresh();
    },
  });
  const u = detail.data;
  const self = me?.id === id;
  const canWrite = can("users:write");
  const run = (fn: () => Promise<string | null>) => {
    setLink(null);
    act.mutate(fn);
  };

  if (detail.isLoading) {
    return (
      <div role="status" aria-label="Loading user" className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-96" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (detail.isError || !u) {
    return (
      <Alert tone="error" title="Could not load this user">
        {detail.error instanceof ApiError ? `${detail.error.status}: ${detail.error.message}` : String(detail.error)}
      </Alert>
    );
  }
  const tabs: { key: TabKey; label: string }[] = [{ key: "access", label: "Access" }, ...(can("crm:read") ? [{ key: "crm" as const, label: "Notes & tasks" }] : []), { key: "activity", label: "Activity" }];
  return (
    <div>
      <PageHeader
        breadcrumbs={[{ label: "Users", href: "/users" }, { label: u.name }]}
        title={u.name}
        subtitle={u.email}
        actions={
          <>
            <StatusPill tone={statusPill(u.status)}>{u.status.charAt(0) + u.status.slice(1).toLowerCase()}</StatusPill>
            <span className="rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-ink-soft">{roleLabel(u.role)}</span>
          </>
        }
      />
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="min-w-0 space-y-5 lg:col-span-2">
          {self ? <Alert tone="info">This is your own account: role, status and two-factor changes need another administrator. Use Account security for your password.</Alert> : null}
          {act.isError ? <Alert tone="error">{message(act.error)}</Alert> : null}
          {link ? <CopyLink label={link.label} url={link.url} /> : null}
          <Tabs tabs={tabs} value={tab} onChange={setTab} label="Sections" />

          {tab === "access" && canWrite ? (
            <>
              <Panel title="Profile">
                <form
                  className="flex flex-wrap items-end gap-3 p-5"
                  onSubmit={(e) => {
                    e.preventDefault();
                    run(async () => {
                      await api.renameUser(id, name ?? u.name);
                      return "Name saved.";
                    });
                  }}
                >
                  <div className="min-w-0 flex-1 basis-64">
                    <Field id="rename" label="Name">
                      <input id="rename" value={name ?? u.name} onChange={(e) => setName(e.target.value)} className={inputFull} />
                    </Field>
                  </div>
                  {can("roles:write") ? (
                    <div className="basis-44">
                      <Field id="role" label="Role">
                        <select
                          id="role"
                          value={u.role}
                          disabled={self}
                          onChange={(e) => {
                            const next = e.target.value; // read now: a controlled select is put back before the request runs
                            run(async () => {
                              await api.setUserRole(id, next);
                              return "Role changed. Their sessions were ended so the new access applies at next sign-in.";
                            });
                          }}
                          className={inputFull}
                        >
                          {ROLES.map((r) => (
                            <option key={r} value={r}>{roleLabel(r)}</option>
                          ))}
                        </select>
                      </Field>
                    </div>
                  ) : null}
                  <button type="submit" className={buttonClass("secondary")}>Save name</button>
                </form>
              </Panel>
              <Panel title="Account actions">
                <div className="divide-y divide-line p-5">
                  {u.status === "ACTIVE" ? (
                    <ActionRow title="Suspend account" description="Blocks sign-in and ends their sessions. You can reactivate them later.">
                      <ConfirmButton tone="danger" disabled={self} question={`Suspend ${u.name}?`} confirmLabel="Suspend" onConfirm={() => run(async () => { await api.setUserStatus(id, "SUSPENDED"); return "Suspended and signed out."; })}>Suspend</ConfirmButton>
                    </ActionRow>
                  ) : null}
                  {u.status === "SUSPENDED" || u.status === "DISABLED" ? (
                    <ActionRow title="Restore access" description="Lets them sign in again with their current password.">
                      <ConfirmButton disabled={self} question={`Reactivate ${u.name}?`} confirmLabel="Reactivate" onConfirm={() => run(async () => { await api.setUserStatus(id, "ACTIVE"); return "Reactivated."; })}>Reactivate</ConfirmButton>
                    </ActionRow>
                  ) : null}
                  {u.status === "INVITED" ? (
                    <ActionRow title="Invitation pending" description="They have not chosen a password yet. Send a fresh one-time link.">
                      <ConfirmButton question="Send a new invitation link?" confirmLabel="Send" onConfirm={() => run(async () => { const r = await api.resendInvite(id); setLink({ label: "New invitation link", url: r.invite_url }); return "A new invitation was sent."; })}>Resend invitation</ConfirmButton>
                    </ActionRow>
                  ) : null}
                  {u.status === "ACTIVE" ? (
                    <ActionRow title="Password reset" description="Emails them a one-time link to choose a new password.">
                      <ConfirmButton question="Send a password reset link?" confirmLabel="Send" onConfirm={() => run(async () => { const r = await api.sendReset(id); setLink({ label: "Password reset link", url: r.reset_url }); return "A reset link was sent."; })}>Send password reset</ConfirmButton>
                    </ActionRow>
                  ) : null}
                  <ActionRow title="Two-factor authentication" description="Removes their authenticator and recovery codes (for a lost phone). They set it up again at next sign-in.">
                    <ConfirmButton tone="danger" disabled={self || !u.mfa_enabled} question="Remove their two-factor setup?" confirmLabel="Reset 2FA" onConfirm={() => run(async () => { await api.resetUserMfa(id); return "Two-factor removed and sessions ended."; })}>Reset two-factor</ConfirmButton>
                  </ActionRow>
                  <ActionRow title="Sessions" description={`${u.active_sessions} active ${u.active_sessions === 1 ? "session" : "sessions"}. Signing them out ends access on every device immediately.`}>
                    <ConfirmButton tone="danger" disabled={u.active_sessions === 0} question="Sign them out everywhere?" confirmLabel="End sessions" onConfirm={() => run(async () => { const r = await api.endUserSessions(id); return `${r.ended} session(s) ended.`; })}>End all sessions</ConfirmButton>
                  </ActionRow>
                  {u.status !== "DISABLED" ? (
                    <ActionRow title="Disable account" description="Permanent removal of access, for someone who has left. Their history is kept.">
                      <ConfirmButton tone="danger" disabled={self} question={`Disable ${u.name} for good?`} confirmLabel="Disable" onConfirm={() => run(async () => { await api.setUserStatus(id, "DISABLED"); return "Disabled and signed out."; })}>Disable</ConfirmButton>
                    </ActionRow>
                  ) : null}
                </div>
              </Panel>
            </>
          ) : null}

          {tab === "crm" && can("crm:read") ? <UserCrm userId={id} tags={u.tags} /> : null}

          {tab === "activity" || (tab === "access" && !canWrite) ? (
            <Panel title="Activity">
              <div className="px-5 py-2">
                {activity.isError ? <div className="py-3"><Alert tone="error">{message(activity.error)}</Alert></div> : null}
                <ul className="divide-y divide-line text-sm">
                  {activity.data?.events.map((e) => (
                    <li key={e.id} className="flex flex-wrap justify-between gap-2 py-3">
                      <span>
                        <span className="font-medium">{actionLabel(e.action)}</span> <span className="text-ink-soft">by {e.actor}</span>
                      </span>
                      <span className="text-xs text-ink-soft"><RelativeTime iso={e.at} /></span>
                    </li>
                  ))}
                </ul>
                {activity.data && activity.data.events.length === 0 ? <EmptyState icon="scroll" title="Nothing recorded yet" /> : null}
              </div>
            </Panel>
          ) : null}
        </div>

        <aside className="space-y-5">
          <Panel title="Summary">
            <div className="px-5 py-2">
              <div className="flex items-center gap-3 py-3">
                <Avatar name={u.name} />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{u.name}</p>
                  <p className="truncate text-xs text-ink-soft">{u.email}</p>
                </div>
              </div>
              <DefinitionList
                items={[
                  { label: "Two-factor", value: <>{u.mfa_enabled ? "On" : "Off"}{u.mfa_enabled ? <span className="block text-xs font-normal text-ink-soft">{u.recovery_codes_left} recovery codes left</span> : null}</> },
                  { label: "Active sessions", value: u.active_sessions },
                  { label: "Last sign-in", value: u.last_login_at ? <RelativeTime iso={u.last_login_at} /> : "Never" },
                  { label: "Password changed", value: u.password_changed_at ? <RelativeTime iso={u.password_changed_at} /> : "Not set" },
                  { label: "Created", value: <><RelativeTime iso={u.created_at} /><span className="block text-xs font-normal text-ink-soft">{u.created_by ? `by ${u.created_by}` : "by the system"}</span></> },
                ]}
              />
            </div>
          </Panel>
        </aside>
      </div>
    </div>
  );
}
