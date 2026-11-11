"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { ApiError, api } from "@/lib/api/client";
import { buttonClass } from "@/components/ui/styles";

/** Where Zerodha sends the browser back to. It hands the one-time request token and our `state` to the server, which checks
 * the state belongs to this signed-in user before it exchanges the token. Nothing here is kept in the page or the URL after. */
function Callback() {
  const q = useSearchParams();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const done = useRef(false); // React may run effects twice in development; a request token can only be used once
  useEffect(() => {
    if (done.current) return;
    done.current = true;
    const token = q.get("request_token");
    const state = q.get("state");
    if (q.get("status") !== "success" || !token || !state) {
      setError("Zerodha did not complete the login. Start again from the Kite page.");
      return;
    }
    api
      .kiteComplete(token, state)
      .then(() => router.replace("/kite?connected=1"))
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Could not reach the server. Try again."));
  }, [q, router]);
  return (
    <div className="mx-auto max-w-md space-y-3 py-10">
      {error ? (
        <>
          <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p>
          <button type="button" onClick={() => router.replace("/kite")} className={buttonClass("secondary")}>Back to the Kite page</button>
        </>
      ) : (
        <p role="status" className="text-sm text-ink-soft">Finishing your Kite connection…</p>
      )}
    </div>
  );
}

export default function KiteCallback() {
  return (
    <Suspense>
      <Callback />
    </Suspense>
  );
}
