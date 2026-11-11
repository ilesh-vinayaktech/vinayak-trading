"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { ApiError, api } from "@/lib/api/client";
import { safeNext, useAuth } from "@/lib/auth";

const field = "w-full rounded-md border border-line bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100";

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
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-line bg-white p-6 shadow-sm" aria-labelledby="signin-title">
        <div>
          <h1 id="signin-title" className="text-lg font-semibold">Sign in</h1>
          <p className="text-xs text-ink-soft">Vinayak Trading Research Console</p>
        </div>
        {error ? (
          <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">
            {error}
          </p>
        ) : null}
        <div className="space-y-1">
          <label htmlFor="email" className="text-sm font-medium">Email</label>
          <input id="email" type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} readOnly={needCode} className={field} />
        </div>
        <div className="space-y-1">
          <label htmlFor="password" className="text-sm font-medium">Password</label>
          <input id="password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} readOnly={needCode} className={field} />
        </div>
        {needCode ? (
          <div className="space-y-1">
            <label htmlFor="code" className="text-sm font-medium">Authentication code</label>
            <input id="code" inputMode="numeric" autoComplete="one-time-code" autoFocus required value={code} onChange={(e) => setCode(e.target.value)} className={field} />
            <p className="text-xs text-ink-soft">Enter the 6-digit code from your authenticator app, or one of your recovery codes.</p>
          </div>
        ) : null}
        <button type="submit" disabled={busy} className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50">
          {busy ? "Signing in..." : needCode ? "Verify" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <SignIn />
    </Suspense>
  );
}
