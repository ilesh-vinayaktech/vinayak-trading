"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useState, type FormEvent } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert, Avatar } from "@/components/ui/Alert";
import { DataTable, EmptyState, Pagination, type Column } from "@/components/ui/DataTable";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Icon } from "@/components/ui/Icon";
import { Panel, RelativeTime, StatusPill } from "@/components/ui/Layout";
import { buttonClass, inputClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { CopyLink } from "@/components/users/CopyLink";
import { roleLabel, statusPill } from "@/components/users/format";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { ROLES, STATUSES, type UserRow } from "@/lib/schemas";

const PAGE = 25;

function InviteDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<string>("TRADER");
  const invite = useMutation({
    mutationFn: () => api.inviteUser(email, name, role),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(`Invitation created for ${email}.`);
    },
  });
  const close = () => {
    onClose();
    setTimeout(() => {
      invite.reset();
      setEmail("");
      setName("");
      setRole("TRADER");
    }, 150);
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    invite.mutate();
  };
  return (
    <Dialog
      open={open}
      onClose={close}
      title="Invite a user"
      description="They get a one-time link to choose their password."
      footer={
        invite.data ? (
          <button type="button" onClick={close} className={buttonClass("primary")}>Done</button>
        ) : (
          <>
            <button type="button" onClick={close} className={buttonClass("secondary")}>Cancel</button>
            <button type="submit" form="invite-form" disabled={invite.isPending} className={buttonClass("primary")}>Send invitation</button>
          </>
        )
      }
    >
      {invite.data ? (
        <CopyLink label={`Invitation for ${email}`} url={invite.data.invite_url} />
      ) : (
        <form id="invite-form" onSubmit={submit} className="space-y-4">
          {invite.isError ? <Alert tone="error">{invite.error instanceof ApiError ? invite.error.message : "Could not send the invitation."}</Alert> : null}
          <Field id="inv-email" label="Email">
            <input id="inv-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={inputFull} />
          </Field>
          <Field id="inv-name" label="Name">
            <input id="inv-name" required value={name} onChange={(e) => setName(e.target.value)} className={inputFull} />
          </Field>
          <Field id="inv-role" label="Role" hint="Administrators and operators must set up two-factor authentication at first sign-in.">
            <select id="inv-role" value={role} onChange={(e) => setRole(e.target.value)} className={inputFull}>
              {ROLES.map((r) => (
                <option key={r} value={r}>{roleLabel(r)}</option>
              ))}
            </select>
          </Field>
        </form>
      )}
    </Dialog>
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
  const filtered = Boolean(q || role || status || tag);
  const clear = () => {
    setTyped("");
    setQ("");
    setRole("");
    setStatus("");
    setTag("");
    setOffset(0);
  };
  const columns: Column<UserRow>[] = [
    {
      key: "user",
      header: "User",
      cell: (u) => (
        <Link href={`/users/${u.id}`} className="flex items-center gap-3">
          <Avatar name={u.name} />
          <span className="min-w-0">
            <span className="block truncate font-medium text-blue-700 hover:underline">{u.name}</span>
            <span className="block truncate text-xs text-ink-soft">{u.email}</span>
          </span>
        </Link>
      ),
    },
    { key: "role", header: "Role", cell: (u) => roleLabel(u.role) },
    { key: "status", header: "Status", cell: (u) => <StatusPill tone={statusPill(u.status)}>{u.status.charAt(0) + u.status.slice(1).toLowerCase()}</StatusPill> },
    { key: "mfa", header: "2FA", hideBelow: "sm", cell: (u) => (u.mfa_enabled ? <span className="inline-flex items-center gap-1 text-emerald-700"><Icon name="check" size={14} /> On</span> : <span className="text-ink-faint">Off</span>) },
    { key: "tags", header: "Tags", hideBelow: "lg", cell: (u) => (u.tags.length ? <span className="flex flex-wrap gap-1">{u.tags.map((t) => <span key={t} className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-ink-soft">{t}</span>)}</span> : <span className="text-ink-faint">-</span>) },
    { key: "login", header: "Last sign-in", hideBelow: "md", cell: (u) => (u.last_login_at ? <span className="text-ink-soft"><RelativeTime iso={u.last_login_at} /></span> : <span className="text-ink-faint">Never</span>) },
  ];
  return (
    <div>
      <PageHeader
        title="Users"
        subtitle="Everyone who can sign in. Invite people, change their role, suspend access, reset passwords and two-factor setup."
        actions={
          <button type="button" onClick={() => setInviting(true)} className={buttonClass("primary")}>
            <Icon name="users" size={16} /> Invite user
          </button>
        }
      />
      <InviteDialog open={inviting} onClose={() => setInviting(false)} />
      <Panel>
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
          <div className="relative">
            <label htmlFor="user-search" className="sr-only">Search users</label>
            <input id="user-search" type="search" placeholder="Search name or email" value={typed} onChange={(e) => setTyped(e.target.value)} className={`${inputClass} w-64 pl-3`} />
          </div>
          <label className="sr-only" htmlFor="role-filter">Role</label>
          <select id="role-filter" value={role} onChange={(e) => { setRole(e.target.value); setOffset(0); }} className={inputClass}>
            <option value="">All roles</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>{roleLabel(r)}</option>
            ))}
          </select>
          <label className="sr-only" htmlFor="status-filter">Status</label>
          <select id="status-filter" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }} className={inputClass}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s.charAt(0) + s.slice(1).toLowerCase()}</option>
            ))}
          </select>
          {allTags.data && allTags.data.tags.length > 0 ? (
            <>
              <label className="sr-only" htmlFor="tag-filter">Tag</label>
              <select id="tag-filter" value={tag} onChange={(e) => { setTag(e.target.value); setOffset(0); }} className={inputClass}>
                <option value="">All tags</option>
                {allTags.data.tags.map((t) => (
                  <option key={t.tag} value={t.tag}>{t.tag} ({t.users})</option>
                ))}
              </select>
            </>
          ) : null}
          {filtered ? <button type="button" onClick={clear} className={buttonClass("ghost", true)}>Clear filters</button> : null}
        </div>
        {list.isError ? (
          <div className="p-5"><Alert tone="error">{list.error instanceof ApiError ? `${list.error.status}: ${list.error.message}` : "Could not load users."}</Alert></div>
        ) : (
          <DataTable
            caption="Users"
            columns={columns}
            rows={list.data?.items}
            rowKey={(u) => u.id}
            loading={list.isLoading}
            empty={<EmptyState icon="users" title={filtered ? "No user matches" : "No users yet"} action={filtered ? <button type="button" onClick={clear} className={buttonClass("secondary")}>Clear filters</button> : undefined}>{filtered ? "Try a different search or clear the filters." : "Invite the first person to get started."}</EmptyState>}
          />
        )}
        <Pagination offset={offset} pageSize={PAGE} total={total} onChange={setOffset} />
      </Panel>
    </div>
  );
}
