"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/status/Badge";
import { Card, ErrorBox, Loading, Stat } from "@/components/status/LoadState";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { UserCrm } from "@/components/users/UserCrm";
import { CopyLink } from "@/components/users/CopyLink";
import { actionLabel, statusTone } from "@/components/users/format";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/formatting";
import { ROLES } from "@/lib/schemas";

const input = "rounded-md border border-line bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100";
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");

export default function UserProfile() {
  const { id } = useParams<{ id: string }>();
  const { user: me, can } = useAuth();
  const qc = useQueryClient();
  const detail = useQuery({ queryKey: ["user", id], queryFn: () => api.user(id) });
  const activity = useQuery({ queryKey: ["user-activity", id], queryFn: () => api.audit({ target_type: "user", target_id: id, limit: 30 }) });
  const [name, setName] = useState<string | null>(null);
  const [link, setLink] = useState<{ label: string; url: string } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["user", id] });
    void qc.invalidateQueries({ queryKey: ["user-activity", id] });
    void qc.invalidateQueries({ queryKey: ["users"] });
  };
  const act = useMutation({
    mutationFn: async (fn: () => Promise<string | null>) => fn(),
    onSuccess: (msg) => {
      setNotice(msg);
      refresh();
    },
  });
  const u = detail.data;
  const self = me?.id === id;
  const canWrite = can("users:write");
  const run = (fn: () => Promise<string | null>) => {
    setLink(null);
    setNotice(null);
    act.mutate(fn);
  };

  if (detail.isLoading) return <Loading what="user" />;
  if (detail.isError || !u) return <ErrorBox error={detail.error} what="this user" />;
  return (
    <div className="space-y-4">
      <PageHeader
        title={u.name}
        subtitle={u.email}
        actions={
          <div className="flex items-center gap-2">
            <Badge tone={statusTone(u.status)}>{u.status}</Badge>
            <Badge>{u.role}</Badge>
            <Link href="/users" className="text-sm text-blue-700 hover:underline">All users</Link>
          </div>
        }
      />
      {self ? <p className="rounded-md bg-slate-100 px-3 py-2 text-sm text-ink-soft">This is your own account: role, status and two-factor changes need another administrator. Use Account security for your password.</p> : null}
      {act.isError ? <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{message(act.error)}</p> : null}
      {notice ? <p role="status" className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{notice}</p> : null}
      {link ? <CopyLink label={link.label} url={link.url} /> : null}

      <Card title="Profile">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Stat label="Two-factor" value={u.mfa_enabled ? "On" : "Off"} hint={u.mfa_enabled ? `${u.recovery_codes_left} recovery codes left` : undefined} />
          <Stat label="Active sessions" value={u.active_sessions} />
          <Stat label="Last sign-in" value={u.last_login_at ? fmtDateTime(u.last_login_at) : "Never"} />
          <Stat label="Password changed" value={u.password_changed_at ? fmtDateTime(u.password_changed_at) : "Not set"} />
          <Stat label="Created" value={fmtDateTime(u.created_at)} hint={u.created_by ? `by ${u.created_by}` : "by the system"} />
        </div>
      </Card>

      {canWrite ? (
        <Card title="Manage access">
          <div className="space-y-4">
            <form
              className="flex flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                run(async () => {
                  await api.renameUser(id, name ?? u.name);
                  return "Name saved.";
                });
              }}
            >
              <div className="space-y-1">
                <label htmlFor="rename" className="text-sm font-medium">Name</label>
                <input id="rename" value={name ?? u.name} onChange={(e) => setName(e.target.value)} className={`${input} w-64`} />
              </div>
              <button type="submit" className="rounded-md border border-line px-3 py-2 text-sm hover:bg-slate-50">Save name</button>
            </form>
            {can("roles:write") ? (
              <div className="space-y-1">
                <label htmlFor="role" className="text-sm font-medium">Role</label>
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
                  className={`${input} block`}
                >
                  {ROLES.map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </select>
              </div>
            ) : null}
            <div className="flex flex-wrap gap-2">
              {u.status === "ACTIVE" ? (
                <ConfirmButton tone="danger" disabled={self} question={`Suspend ${u.name}?`} confirmLabel="Suspend" onConfirm={() => run(async () => { await api.setUserStatus(id, "SUSPENDED"); return "Suspended and signed out."; })}>Suspend</ConfirmButton>
              ) : null}
              {u.status === "SUSPENDED" || u.status === "DISABLED" ? (
                <ConfirmButton disabled={self} question={`Reactivate ${u.name}?`} confirmLabel="Reactivate" onConfirm={() => run(async () => { await api.setUserStatus(id, "ACTIVE"); return "Reactivated."; })}>Reactivate</ConfirmButton>
              ) : null}
              {u.status !== "DISABLED" ? (
                <ConfirmButton tone="danger" disabled={self} question={`Disable ${u.name} for good?`} confirmLabel="Disable" onConfirm={() => run(async () => { await api.setUserStatus(id, "DISABLED"); return "Disabled and signed out."; })}>Disable</ConfirmButton>
              ) : null}
              {u.status === "INVITED" ? (
                <ConfirmButton question="Send a new invitation link?" confirmLabel="Send" onConfirm={() => run(async () => { const r = await api.resendInvite(id); setLink({ label: "New invitation link", url: r.invite_url }); return "A new invitation was sent."; })}>Resend invitation</ConfirmButton>
              ) : null}
              {u.status === "ACTIVE" ? (
                <ConfirmButton question="Send a password reset link?" confirmLabel="Send" onConfirm={() => run(async () => { const r = await api.sendReset(id); setLink({ label: "Password reset link", url: r.reset_url }); return "A reset link was sent."; })}>Send password reset</ConfirmButton>
              ) : null}
              <ConfirmButton tone="danger" disabled={self || !u.mfa_enabled} question="Remove their two-factor setup?" confirmLabel="Reset 2FA" onConfirm={() => run(async () => { await api.resetUserMfa(id); return "Two-factor removed and sessions ended."; })}>Reset two-factor</ConfirmButton>
              <ConfirmButton tone="danger" disabled={u.active_sessions === 0} question="Sign them out everywhere?" confirmLabel="End sessions" onConfirm={() => run(async () => { const r = await api.endUserSessions(id); return `${r.ended} session(s) ended.`; })}>End all sessions</ConfirmButton>
            </div>
          </div>
        </Card>
      ) : null}

      {can("crm:read") ? <UserCrm userId={id} tags={u.tags} /> : null}

      <Card title="Activity" note="Changes made to this account and its sign-ins, newest first.">
        {activity.isError ? <p role="alert" className="text-sm text-red-700">{message(activity.error)}</p> : null}
        <ul className="divide-y divide-line text-sm">
          {activity.data?.events.map((e) => (
            <li key={e.id} className="flex flex-wrap justify-between gap-2 py-2">
              <span>
                <span className="font-medium">{actionLabel(e.action)}</span> <span className="text-ink-soft">by {e.actor}</span>
              </span>
              <span className="text-xs text-ink-soft">{fmtDateTime(e.at)}</span>
            </li>
          ))}
        </ul>
        {activity.data && activity.data.events.length === 0 ? <p className="text-sm text-ink-soft">Nothing recorded yet.</p> : null}
      </Card>
    </div>
  );
}
