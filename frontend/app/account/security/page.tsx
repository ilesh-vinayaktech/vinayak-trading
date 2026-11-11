"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useEffect, useState, type FormEvent } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/status/Badge";
import { Card } from "@/components/status/LoadState";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/formatting";

const field = "w-full max-w-sm rounded-md border border-line bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100";
const button = "rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50";
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");

function PasswordCard() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const qc = useQueryClient();
  const m = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: () => {
      setCurrent("");
      setNext("");
      setAgain("");
      void qc.invalidateQueries({ queryKey: ["me"] });
      void qc.invalidateQueries({ queryKey: ["my-sessions"] });
    },
  });
  const mismatch = again !== "" && again !== next;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!mismatch) m.mutate();
  };
  return (
    <Card title="Password" note="At least 12 characters. Changing it signs out your other sessions.">
      <form onSubmit={submit} className="space-y-3">
        <div className="space-y-1">
          <label htmlFor="cur" className="text-sm font-medium">Current password</label>
          <input id="cur" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} className={field} />
        </div>
        <div className="space-y-1">
          <label htmlFor="new" className="text-sm font-medium">New password</label>
          <input id="new" type="password" autoComplete="new-password" required minLength={12} value={next} onChange={(e) => setNext(e.target.value)} className={field} />
        </div>
        <div className="space-y-1">
          <label htmlFor="again" className="text-sm font-medium">Repeat new password</label>
          <input id="again" type="password" autoComplete="new-password" required value={again} onChange={(e) => setAgain(e.target.value)} className={field} />
          {mismatch ? <p className="text-xs text-red-700">The passwords differ.</p> : null}
        </div>
        {m.isError ? <p role="alert" className="text-sm text-red-700">{message(m.error)}</p> : null}
        {m.isSuccess ? <p role="status" className="text-sm text-emerald-700">Password changed.</p> : null}
        <button type="submit" disabled={m.isPending || mismatch} className={button}>Change password</button>
      </form>
    </Card>
  );
}

function TwoFactorCard() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [qr, setQr] = useState<string | null>(null);
  const enrol = useMutation({ mutationFn: api.mfaEnrol });
  const confirm = useMutation({
    mutationFn: () => api.mfaConfirm(code),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["me"] }),
  });
  useEffect(() => {
    if (enrol.data) void QRCode.toDataURL(enrol.data.uri, { margin: 1, width: 192 }).then(setQr);
  }, [enrol.data]);

  if (confirm.data) {
    return (
      <Card title="Two-factor authentication" note="On. Save these recovery codes now: each works once and they are not shown again.">
        <ul className="grid max-w-sm grid-cols-2 gap-2 font-mono text-sm" aria-label="Recovery codes">
          {confirm.data.recovery_codes.map((c) => (
            <li key={c} className="rounded border border-line bg-slate-50 px-2 py-1">{c}</li>
          ))}
        </ul>
      </Card>
    );
  }
  if (user?.mfa_enabled) {
    return (
      <Card title="Two-factor authentication">
        <Badge tone="good">On</Badge>
        <p className="mt-2 text-sm text-ink-soft">A code from your authenticator app is asked for at every sign-in.</p>
      </Card>
    );
  }
  return (
    <Card title="Two-factor authentication" note={user?.enrolment_required ? "Required for your role before you can use the console." : "Adds a second step at sign-in."}>
      {!enrol.data ? (
        <div className="space-y-2">
          {enrol.isError ? <p role="alert" className="text-sm text-red-700">{message(enrol.error)}</p> : null}
          <button type="button" onClick={() => enrol.mutate()} disabled={enrol.isPending} className={button}>Set up two-factor authentication</button>
        </div>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            confirm.mutate();
          }}
          className="space-y-3"
        >
          <p className="text-sm">Scan this with an authenticator app (Google Authenticator, Authy, 1Password), then enter the 6-digit code it shows.</p>
          {/* eslint-disable-next-line @next/next/no-img-element -- a generated data: URL, nothing for next/image to optimise */}
          {qr ? <img src={qr} alt="QR code for your authenticator app" width={192} height={192} className="rounded border border-line" /> : null}
          <p className="text-xs text-ink-soft">
            Can not scan? Enter this key by hand: <code className="font-mono text-slate-800">{enrol.data.secret}</code>
          </p>
          <div className="space-y-1">
            <label htmlFor="mfa-code" className="text-sm font-medium">Code from the app</label>
            <input id="mfa-code" inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} className={field} />
          </div>
          {confirm.isError ? <p role="alert" className="text-sm text-red-700">{message(confirm.error)}</p> : null}
          <button type="submit" disabled={confirm.isPending} className={button}>Turn on</button>
        </form>
      )}
    </Card>
  );
}

function SessionsCard() {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["my-sessions"], queryFn: api.mySessions });
  const end = useMutation({ mutationFn: (id: string) => api.endSession(id), onSuccess: () => void qc.invalidateQueries({ queryKey: ["my-sessions"] }) });
  return (
    <Card title="Active sessions" note="Where you are signed in. End any you do not recognise.">
      {list.isError ? <p role="alert" className="text-sm text-red-700">{message(list.error)}</p> : null}
      <ul className="divide-y divide-line">
        {list.data?.sessions.map((s) => (
          <li key={s.session_id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
            <div>
              <div className="font-medium">{s.user_agent ?? "Unknown device"} {s.current ? <Badge tone="good">this session</Badge> : null}</div>
              <div className="text-xs text-ink-soft">{s.ip ?? "unknown address"} · last active {fmtDateTime(s.last_seen_at)}</div>
            </div>
            {s.current ? null : (
              <button type="button" onClick={() => end.mutate(s.session_id)} disabled={end.isPending} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-slate-50">
                End session
              </button>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function SecurityPage() {
  const { user } = useAuth();
  const restricted = user?.enrolment_required || user?.must_change_password;
  return (
    <div className="space-y-4">
      <PageHeader title="Account security" subtitle={user ? `${user.name} · ${user.email} · ${user.role}` : ""} />
      {restricted ? (
        <p role="alert" className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">
          {user?.must_change_password ? "Choose a new password to continue." : "Set up two-factor authentication to continue."}
        </p>
      ) : null}
      <PasswordCard />
      <TwoFactorCard />
      {restricted ? null : <SessionsCard />}
    </div>
  );
}
