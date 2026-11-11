"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { PublicCard, fieldClass, primaryClass } from "@/components/users/PublicCard";
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
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">This link is missing its token. Open the link from your email again.</p>
      ) : done ? (
        <p role="status" className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">Your account is active. You can sign in now.</p>
      ) : (
        <>
          {error ? <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p> : null}
          <div className="space-y-1">
            <label htmlFor="pw" className="text-sm font-medium">New password</label>
            <input id="pw" type="password" autoComplete="new-password" required minLength={12} value={password} onChange={(e) => setPassword(e.target.value)} className={fieldClass} />
            <p className="text-xs text-ink-soft">At least 12 characters. A few unrelated words make a strong one.</p>
          </div>
          <div className="space-y-1">
            <label htmlFor="pw2" className="text-sm font-medium">Repeat password</label>
            <input id="pw2" type="password" autoComplete="new-password" required value={again} onChange={(e) => setAgain(e.target.value)} className={fieldClass} />
            {mismatch ? <p className="text-xs text-red-700">The passwords differ.</p> : null}
          </div>
          <button type="submit" disabled={busy || mismatch} className={primaryClass}>Activate account</button>
        </>
      )}
      <Link href="/login" className="block text-center text-xs text-blue-700 hover:underline">Go to sign in</Link>
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
