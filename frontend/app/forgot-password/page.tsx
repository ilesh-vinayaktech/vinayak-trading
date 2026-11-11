"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { PublicCard, fieldClass, primaryClass } from "@/components/users/PublicCard";
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
    <PublicCard title="Reset your password" onSubmit={submit}>
      {sent ? (
        <p role="status" className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          If that address has an account, a reset link is on its way. It works for 2 hours.
        </p>
      ) : (
        <>
          {error ? <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p> : null}
          <div className="space-y-1">
            <label htmlFor="email" className="text-sm font-medium">Email</label>
            <input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} className={fieldClass} />
          </div>
          <button type="submit" disabled={busy} className={primaryClass}>Send reset link</button>
        </>
      )}
      <Link href="/login" className="block text-center text-xs text-blue-700 hover:underline">Back to sign in</Link>
    </PublicCard>
  );
}
