"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Field, PasswordInput } from "@/components/ui/Field";
import { inputFull } from "@/components/ui/styles";
import { PublicCard, primaryClass } from "@/components/users/PublicCard";
import { ApiError, api } from "@/lib/api/client";
import { safeNext, useAuth } from "@/lib/auth";

function SignIn() {
  const router = useRouter();
  const params = useSearchParams();
  const { signedIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.login(email, password, needCode ? code : undefined);
      if ("mfa_required" in r) {
        setNeedCode(true);
        return;
      }
      signedIn(r.user);
      router.replace(r.user.enrolment_required || r.user.must_change_password ? "/account/security" : safeNext(params.get("next")));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server. Try again.");
      if (err instanceof ApiError && err.status === 401 && needCode) setCode("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicCard title={needCode ? "Two-step verification" : "Sign in"} subtitle={needCode ? "Enter the code from your authenticator app." : "Welcome back. Sign in to continue."} onSubmit={submit}>
      {error ? <Alert tone="error">{error}</Alert> : null}
      <Field id="email" label="Email">
        <input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} readOnly={needCode} className={inputFull} />
      </Field>
      <Field id="password" label="Password">
        <PasswordInput id="password" value={password} onChange={setPassword} autoComplete="current-password" readOnly={needCode} />
      </Field>
      {needCode ? (
        <Field id="code" label="Authentication code" hint="The 6-digit code, or one of your recovery codes.">
          <input id="code" inputMode="numeric" autoComplete="one-time-code" autoFocus required value={code} onChange={(e) => setCode(e.target.value)} className={inputFull} />
        </Field>
      ) : null}
      <button type="submit" disabled={busy} className={primaryClass}>
        {busy ? "Signing in..." : needCode ? "Verify" : "Sign in"}
      </button>
      <Link href="/forgot-password" className="block text-center text-sm text-brand hover:underline">Forgot your password?</Link>
    </PublicCard>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <SignIn />
    </Suspense>
  );
}
