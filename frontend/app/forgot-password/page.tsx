"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Field } from "@/components/ui/Field";
import { inputFull } from "@/components/ui/styles";
import { PublicCard, primaryClass } from "@/components/users/PublicCard";
import { ApiError, api } from "@/lib/api/client";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.forgotPassword(email);
      setSent(true); // the same message whether or not the address has an account
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server. Try again.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <PublicCard title="Reset your password" subtitle="We will email you a link to choose a new one." onSubmit={submit}>
      {sent ? (
        <Alert tone="success">If that address has an account, a reset link is on its way. It works for 2 hours.</Alert>
      ) : (
        <>
          {error ? <Alert tone="error">{error}</Alert> : null}
          <Field id="email" label="Email">
            <input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className={inputFull} />
          </Field>
          <button type="submit" disabled={busy} className={primaryClass}>Send reset link</button>
        </>
      )}
      <Link href="/login" className="block text-center text-sm text-brand hover:underline">Back to sign in</Link>
    </PublicCard>
  );
}
