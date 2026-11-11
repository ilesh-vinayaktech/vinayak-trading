"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/status/Badge";
import { Card, ErrorBox, Loading } from "@/components/status/LoadState";
import { CopyLink } from "@/components/users/CopyLink";
import { statusTone } from "@/components/users/format";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/formatting";
import { ROLES, STATUSES } from "@/lib/schemas";
import { buttonClass, inputClass } from "@/components/ui/styles";

const PAGE = 25;
const input = inputClass;

function InviteForm({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<string>("TRADER");
  const invite = useMutation({
    mutationFn: () => api.inviteUser(email, name, role),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["users"] }),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    invite.mutate();
  };
  if (invite.data) {
    return (
      <div className="space-y-2">
        <CopyLink label={`Invitation for ${email}`} url={invite.data.invite_url} />
        <button type="button" onClick={onDone} className={buttonClass("secondary")}>Done</button>
      </div>
    );
  }
  return (
    <form onSubmit={submit} className="grid max-w-2xl gap-3 sm:grid-cols-2">
      <div className="space-y-1">
        <label htmlFor="inv-email" className="text-sm font-medium">Email</label>
        <input id="inv-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={`${input} w-full`} />
      </div>
      <div className="space-y-1">
        <label htmlFor="inv-name" className="text-sm font-medium">Name</label>
        <input id="inv-name" required value={name} onChange={(e) => setName(e.target.value)} className={`${input} w-full`} />
      </div>
      <div className="space-y-1">
        <label htmlFor="inv-role" className="text-sm font-medium">Role</label>
        <select id="inv-role" value={role} onChange={(e) => setRole(e.target.value)} className={`${input} w-full`}>
          {ROLES.map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </select>
      </div>
      <div className="flex items-end gap-2">
        <button type="submit" disabled={invite.isPending} className={buttonClass("primary")}>Send invitation</button>
        <button type="button" onClick={onDone} className={buttonClass("secondary")}>Cancel</button>
      </div>
      {invite.isError ? <p role="alert" className="text-sm text-red-700 sm:col-span-2">{invite.error instanceof ApiError ? invite.error.message : "Could not send the invitation."}</p> : null}
    </form>
  );
}

export default function UsersPage() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [typed, setTyped] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [tag, setTag] = useState("");
  const [offset, setOffset] = useState(0);
  const [inviting, setInviting] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => {
      setQ(typed);
      setOffset(0);
    }, 250);
    return () => clearTimeout(t);
  }, [typed]);
  const list = useQuery({ queryKey: ["users", q, role, status, tag, offset], queryFn: () => api.users({ q, role, status, tag, limit: PAGE, offset }), placeholderData: (prev) => prev });
  const allTags = useQuery({ queryKey: ["tags"], queryFn: api.tags, enabled: can("crm:read") });
  const total = list.data?.total ?? 0;
  return (
    <div className="space-y-4">
      <PageHeader
        title="Users"
        subtitle="Everyone who can sign in. Invite people, change their role, suspend access, reset passwords and two-factor setup."
        actions={
          <button type="button" onClick={() => setInviting(true)} className={buttonClass("primary")}>
            Invite user
          </button>
        }
      />
      {inviting ? (
        <Card title="Invite a user">
          <InviteForm onDone={() => setInviting(false)} />
        </Card>
      ) : null}
      <Card title="Directory">
        <div className="mb-3 flex flex-wrap gap-2">
          <label className="sr-only" htmlFor="user-search">Search users</label>
          <input id="user-search" type="search" placeholder="Search name or email" value={typed} onChange={(e) => setTyped(e.target.value)} className={`${input} w-64`} />
          <label className="sr-only" htmlFor="role-filter">Role</label>
          <select id="role-filter" value={role} onChange={(e) => { setRole(e.target.value); setOffset(0); }} className={input}>
            <option value="">All roles</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
          <label className="sr-only" htmlFor="status-filter">Status</label>
          <select id="status-filter" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className={input}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
          {allTags.data && allTags.data.tags.length > 0 ? (
            <>
              <label className="sr-only" htmlFor="tag-filter">Tag</label>
              <select id="tag-filter" value={tag} onChange={(e) => { setTag(e.target.value); setOffset(0); }} className={input}>
                <option value="">All tags</option>
                {allTags.data.tags.map((t) => (
                  <option key={t.tag} value={t.tag}>{t.tag} ({t.users})</option>
                ))}
              </select>
            </>
          ) : null}
        </div>
        {list.isError ? <ErrorBox error={list.error} what="users" /> : null}
        {list.isLoading ? <Loading what="users" /> : null}
        {list.data ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-ink-soft">
                  <tr>
                    <th className="py-2 pr-4 font-medium">Name</th>
                    <th className="py-2 pr-4 font-medium">Role</th>
                    <th className="py-2 pr-4 font-medium">Status</th>
                    <th className="py-2 pr-4 font-medium">2FA</th>
                    <th className="py-2 pr-4 font-medium">Last sign-in</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {list.data.items.map((u) => (
                    <tr key={u.id}>
                      <td className="py-2 pr-4">
                        <Link href={`/users/${u.id}`} className="font-medium text-blue-700 hover:underline">{u.name}</Link>
                        <div className="text-xs text-ink-soft">{u.email}</div>
                        {u.tags.length > 0 ? <div className="mt-1 flex flex-wrap gap-1">{u.tags.map((t) => <Badge key={t}>{t}</Badge>)}</div> : null}
                      </td>
                      <td className="py-2 pr-4">{u.role}</td>
                      <td className="py-2 pr-4"><Badge tone={statusTone(u.status)}>{u.status}</Badge></td>
                      <td className="py-2 pr-4">{u.mfa_enabled ? "On" : "Off"}</td>
                      <td className="py-2 pr-4 text-ink-soft">{u.last_login_at ? fmtDateTime(u.last_login_at) : "Never"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {total === 0 ? <p className="py-4 text-sm text-ink-soft">No user matches.</p> : null}
            <div className="mt-3 flex items-center justify-between text-xs text-ink-soft">
              <span>{total === 0 ? "0 users" : `${offset + 1}–${Math.min(offset + PAGE, total)} of ${total}`}</span>
              <span className="flex gap-2">
                <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))} className="rounded border border-line px-2 py-1 disabled:opacity-40">Previous</button>
                <button type="button" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)} className="rounded border border-line px-2 py-1 disabled:opacity-40">Next</button>
              </span>
            </div>
          </>
        ) : null}
      </Card>
    </div>
  );
}
