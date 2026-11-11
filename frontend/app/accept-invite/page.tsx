"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Field, PasswordInput } from "@/components/ui/Field";
import { PublicCard, primaryClass } from "@/components/users/PublicCard";
import { ApiError, api } from "@/lib/api/client";

function Form() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const mismatch = again !== "" && again !== password;
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (mismatch) return;
    setBusy(true);
    setError(null);
    try {
      await api.acceptInvite(token, password);
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server. Try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <PublicCard title="Choose your password" subtitle="Welcome. Set a password to activate your account." onSubmit={submit}>
      {!token ? (
        <Alert tone="error">This link is missing its token. Open the link from your email again.</Alert>
      ) : done ? (
        <Alert tone="success">Your account is active. You can sign in now.</Alert>
      ) : (
        <>
          {error ? <Alert tone="error">{error}</Alert> : null}
          <Field id="pw" label="New password" hint="At least 12 characters. A few unrelated words make a strong one.">
            <PasswordInput id="pw" value={password} onChange={setPassword} autoComplete="new-password" minLength={12} />
          </Field>
          <Field id="pw2" label="Repeat password" error={mismatch ? "The passwords differ." : null}>
            <PasswordInput id="pw2" value={again} onChange={setAgain} autoComplete="new-password" />
          </Field>
          <button type="submit" disabled={busy || mismatch} className={primaryClass}>Activate account</button>
        </>
      )}
      <Link href="/login" className="block text-center text-sm text-brand hover:underline">Go to sign in</Link>
    </PublicCard>
  );
}

export default function AcceptInvite() {
  return (
    <Suspense>
      <Form />
    </Suspense>
  );
}
