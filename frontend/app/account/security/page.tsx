"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import QRCode from "qrcode";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/status/Badge";
import { Card } from "@/components/status/LoadState";
import { Alert } from "@/components/ui/Alert";
import { Field, PasswordInput } from "@/components/ui/Field";
import { Icon } from "@/components/ui/Icon";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtDateTime } from "@/lib/formatting";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");

function Requirement({ ok, children }: { ok: boolean; children: string }) {
  return (
    <li className={`flex items-center gap-2 text-xs ${ok ? "text-emerald-700" : "text-ink-soft"}`}>
      <Icon name={ok ? "check" : "circle"} size={14} />
      {children}
      <span className="sr-only">{ok ? " (met)" : " (not met yet)"}</span>
    </li>
  );
}

function PasswordForm() {
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
      <form onSubmit={submit} className="max-w-md space-y-4">
        <Field id="cur" label="Current password">
          <PasswordInput id="cur" value={current} onChange={setCurrent} autoComplete="current-password" />
        </Field>
        <Field id="new" label="New password">
          <PasswordInput id="new" value={next} onChange={setNext} autoComplete="new-password" minLength={12} />
        </Field>
        <ul className="space-y-1" aria-label="Password requirements">
          <Requirement ok={next.length >= 12}>At least 12 characters</Requirement>
          <Requirement ok={again !== "" && again === next}>Both new passwords match</Requirement>
        </ul>
        <Field id="again" label="Repeat new password" error={mismatch ? "The passwords differ." : null}>
          <PasswordInput id="again" value={again} onChange={setAgain} autoComplete="new-password" />
        </Field>
        {m.isError ? <Alert tone="error">{message(m.error)}</Alert> : null}
        {m.isSuccess ? <Alert tone="success">Password changed.</Alert> : null}
        <button type="submit" disabled={m.isPending || mismatch} className={buttonClass("primary")}>Change password</button>
      </form>
  );
}

function PasswordCard() {
  return (
    <Card title="Password" note="Changing it signs out your other sessions.">
      <PasswordForm />
    </Card>
  );
}

/** While two-factor setup is still required the password form is optional, so it stays out of the way until asked for. */
function OptionalPassword() {
  return (
    <details className="group rounded-xl border border-line bg-panel shadow-card">
      <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-4 text-sm font-medium">
        Change your password instead (optional)
        <Icon name="chevron" size={16} className="text-ink-faint transition-transform group-open:rotate-180" />
      </summary>
      <div className="border-t border-line px-5 py-5">
        <PasswordForm />
      </div>
    </details>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span aria-hidden="true" className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand-dark">{n}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium">{title}</p>
        <div className="mt-1 text-sm text-ink-soft">{children}</div>
      </div>
    </li>
  );
}

function TwoFactorCard() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [qr, setQr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const enrol = useMutation({ mutationFn: api.mfaEnrol });
  const confirm = useMutation({
    mutationFn: () => api.mfaConfirm(code),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["me"] }),
  });
  useEffect(() => {
    if (enrol.data) void QRCode.toDataURL(enrol.data.uri, { margin: 1, width: 192 }).then(setQr);
  }, [enrol.data]);

  if (confirm.data) {
    const codes = confirm.data.recovery_codes;
    return (
      <Card title="Two-factor authentication" note="Each code works once. If you lose your phone, a recovery code is the only way back in without an administrator.">
        <div className="space-y-4">
          <Alert tone="success" title="Two-factor authentication is on">Save your recovery codes now: they are not shown again.</Alert>
          <ul className="grid max-w-md grid-cols-2 gap-2 font-mono text-sm" aria-label="Recovery codes">
            {codes.map((c) => (
              <li key={c} className="rounded-lg border border-line bg-slate-50 px-3 py-1.5">{c}</li>
            ))}
          </ul>
          <button
            type="button"
            className={buttonClass("secondary")}
            onClick={() => {
              void navigator.clipboard?.writeText(codes.join("\n"));
              setCopied(true);
            }}
          >
            {copied ? "Copied" : "Copy all codes"}
          </button>
        </div>
      </Card>
    );
  }
  if (user?.mfa_enabled) {
    return (
      <Card title="Two-factor authentication">
        <div className="flex items-start gap-3">
          <Badge tone="good">On</Badge>
          <p className="text-sm text-ink-soft">A code from your authenticator app is asked for at every sign-in.</p>
        </div>
      </Card>
    );
  }
  return (
    <Card title="Two-factor authentication" note={user?.enrolment_required ? "Required for your role before you can use the console." : "Adds a second step at sign-in."}>
      {!enrol.data ? (
        <div className="space-y-3">
          <p className="text-sm text-ink-soft">Protect your account with a code from an authenticator app (Google Authenticator, Authy or 1Password). It takes about a minute.</p>
          {enrol.isError ? <Alert tone="error">{message(enrol.error)}</Alert> : null}
          <button type="button" onClick={() => enrol.mutate()} disabled={enrol.isPending} className={buttonClass("primary")}>Set up two-factor authentication</button>
        </div>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            confirm.mutate();
          }}
        >
          <ol className="space-y-5">
            <Step n={1} title="Open your authenticator app">Install one if you do not have it yet, then choose to add an account.</Step>
            <Step n={2} title="Scan this code">
              <div className="mt-2 flex flex-wrap items-start gap-4">
                {/* eslint-disable-next-line @next/next/no-img-element -- a generated data: URL, nothing for next/image to optimise */}
                {qr ? <img src={qr} alt="QR code for your authenticator app" width={192} height={192} className="rounded-lg border border-line" /> : <div className="h-48 w-48 animate-pulse rounded-lg bg-slate-100" />}
                <p className="max-w-xs text-xs">
                  Can not scan? Enter this key by hand: <code className="break-all font-mono text-slate-800">{enrol.data.secret}</code>
                </p>
              </div>
            </Step>
            <Step n={3} title="Enter the 6-digit code it shows">
              <div className="mt-2 max-w-xs space-y-3">
                <Field id="mfa-code" label="Code from the app">
                  <input id="mfa-code" inputMode="numeric" autoComplete="one-time-code" required value={code} onChange={(e) => setCode(e.target.value)} className={inputFull} />
                </Field>
                {confirm.isError ? <Alert tone="error">{message(confirm.error)}</Alert> : null}
                <button type="submit" disabled={confirm.isPending} className={buttonClass("primary")}>Turn on</button>
              </div>
            </Step>
          </ol>
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
      {list.isError ? <Alert tone="error">{message(list.error)}</Alert> : null}
      <ul className="divide-y divide-line">
        {list.data?.sessions.map((s) => (
          <li key={s.session_id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
            <div className="min-w-0">
              <div className="flex items-center gap-2 font-medium">
                <span className="truncate">{s.user_agent ?? "Unknown device"}</span>
                {s.current ? <Badge tone="good">this session</Badge> : null}
              </div>
              <div className="text-xs text-ink-soft">{s.ip ?? "unknown address"} · last active {fmtDateTime(s.last_seen_at)}</div>
            </div>
            {s.current ? null : (
              <button type="button" onClick={() => end.mutate(s.session_id)} disabled={end.isPending} className={buttonClass("secondary", true)}>
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
  const mustChange = Boolean(user?.must_change_password);
  const restricted = Boolean(user?.enrolment_required) || mustChange;
  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader title="Account security" subtitle={user ? `${user.name} · ${user.email} · ${user.role}` : ""} />
      {restricted ? (
        <Alert tone="warn" title="Finish setting up your account">
          {mustChange ? "Choose a new password to continue." : "Set up two-factor authentication to continue."}
        </Alert>
      ) : null}
      {mustChange ? <PasswordCard /> : null}
      <TwoFactorCard />
      {mustChange ? null : restricted ? <OptionalPassword /> : <PasswordCard />}
      {restricted ? null : <SessionsCard />}
    </div>
  );
}
