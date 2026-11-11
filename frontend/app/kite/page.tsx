"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Suspense, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, type Tone } from "@/components/status/Badge";
import { Card, ErrorBox, Loading } from "@/components/status/LoadState";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtIst } from "@/lib/formatting";
import type { KiteConnection } from "@/lib/schemas";
import { buttonClass, inputClass } from "@/components/ui/styles";

const field = `${inputClass} w-full max-w-md font-mono`;
const button = buttonClass("primary");
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");
const LABEL: Record<KiteConnection["state"], { text: string; tone: Tone }> = {
  not_configured: { text: "Not set up", tone: "neutral" },
  saved: { text: "Credentials saved, not connected", tone: "warn" },
  connected: { text: "Connected", tone: "good" },
  expired: { text: "Expired: connect again", tone: "bad" },
};

function Credentials({ c }: { c: KiteConnection }) {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const save = useMutation({
    mutationFn: () => api.kiteSave(key, secret),
    onSuccess: () => {
      setKey("");
      setSecret(""); // the secret does not stay in the page once it has been sent
      void qc.invalidateQueries({ queryKey: ["kite"] });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <Card title="1. Your Kite Connect app" note="In your Kite Connect developer account, create an app and set its Redirect URL to the address below. The key and secret are stored encrypted and are never shown again.">
      <div className="mb-3 space-y-1 text-sm">
        <div className="font-medium">Redirect URL to register</div>
        <code className="block break-all rounded border border-line bg-slate-50 px-2 py-1 font-mono text-xs" data-testid="redirect-url">{c.redirect_url}</code>
      </div>
      {c.api_key_hint ? <p className="mb-3 text-sm text-ink-soft">Saved key ending <code className="font-mono">{c.api_key_hint}</code>. Enter new values to replace it.</p> : null}
      <form onSubmit={submit} className="space-y-3">
        <div className="space-y-1">
          <label htmlFor="api-key" className="text-sm font-medium">API key</label>
          <input id="api-key" autoComplete="off" spellCheck={false} required value={key} onChange={(e) => setKey(e.target.value)} className={field} />
        </div>
        <div className="space-y-1">
          <label htmlFor="api-secret" className="text-sm font-medium">API secret</label>
          <input id="api-secret" type="password" autoComplete="new-password" spellCheck={false} required value={secret} onChange={(e) => setSecret(e.target.value)} className={field} />
        </div>
        {save.isError ? <p role="alert" className="text-sm text-red-700">{message(save.error)}</p> : null}
        {save.isSuccess ? <p role="status" className="text-sm text-emerald-700">Saved.</p> : null}
        <button type="submit" disabled={save.isPending} className={button}>{c.api_key_hint ? "Replace credentials" : "Save credentials"}</button>
      </form>
    </Card>
  );
}

function Connect({ c }: { c: KiteConnection }) {
  const qc = useQueryClient();
  const start = useMutation({
    mutationFn: api.kiteStart,
    onSuccess: (r) => window.location.assign(r.login_url), // off to Zerodha; it sends the browser back to the redirect URL
  });
  const disconnect = useMutation({ mutationFn: api.kiteDisconnect, onSuccess: () => void qc.invalidateQueries({ queryKey: ["kite"] }) });
  const remove = useMutation({ mutationFn: api.kiteRemove, onSuccess: () => void qc.invalidateQueries({ queryKey: ["kite"] }) });
  const configured = c.state !== "not_configured";
  return (
    <Card title="2. Connect" note="Zerodha asks you to sign in again every day. The connection ends at 06:00 IST.">
      <div className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={LABEL[c.state].tone}>{LABEL[c.state].text}</Badge>
          {c.kite_user_id ? <span className="text-sm text-ink-soft">Zerodha user {c.kite_user_id}</span> : null}
          {c.token_expires_at && c.state === "connected" ? <span className="text-sm text-ink-soft">until {fmtIst(c.token_expires_at)}</span> : null}
        </div>
        {start.isError ? <p role="alert" className="text-sm text-red-700">{message(start.error)}</p> : null}
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={!configured || start.isPending} onClick={() => start.mutate()} className={button}>
            {c.state === "connected" ? "Reconnect to Zerodha" : "Connect to Zerodha"}
          </button>
          {c.state === "connected" ? (
            <ConfirmButton question="Disconnect from Kite?" confirmLabel="Disconnect" onConfirm={() => disconnect.mutate()}>Disconnect</ConfirmButton>
          ) : null}
          {configured ? (
            <ConfirmButton tone="danger" question="Remove your saved Kite credentials?" confirmLabel="Remove" onConfirm={() => remove.mutate()}>Remove credentials</ConfirmButton>
          ) : null}
        </div>
      </div>
    </Card>
  );
}

function SystemFeed({ c }: { c: KiteConnection }) {
  const qc = useQueryClient();
  const feed = useQuery({ queryKey: ["kite", "system"], queryFn: api.kiteSystem });
  const set = useMutation({ mutationFn: (enabled: boolean) => api.kiteSetSystem(enabled), onSuccess: () => void qc.invalidateQueries({ queryKey: ["kite"] }) });
  const f = feed.data?.feed ?? null;
  return (
    <Card title="System data feed" note="The data loaders use this connection instead of a credentials file. Only one connection can be the feed.">
      <p className="mb-2 text-sm">
        {f ? (
          <>
            Used now: <span className="font-medium">{f.owner}</span> (key ending {f.api_key_hint}) <Badge tone={LABEL[f.state].tone}>{LABEL[f.state].text}</Badge>
          </>
        ) : (
          "No connection is the data feed yet."
        )}
      </p>
      {set.isError ? <p role="alert" className="mb-2 text-sm text-red-700">{message(set.error)}</p> : null}
      {c.is_system ? (
        <button type="button" onClick={() => set.mutate(false)} className={buttonClass("secondary")}>Stop using my connection as the feed</button>
      ) : (
        <button type="button" onClick={() => set.mutate(true)} className={buttonClass("secondary")}>Use my connection as the data feed</button>
      )}
    </Card>
  );
}

function Notice() {
  const q = useSearchParams();
  if (q.get("connected")) return <p role="status" className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">Connected to Zerodha for today.</p>;
  const error = q.get("error");
  return error ? <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-800">{error}</p> : null;
}

export default function KitePage() {
  const { can } = useAuth();
  const conn = useQuery({ queryKey: ["kite", "connection"], queryFn: api.kiteConnection });
  return (
    <div className="space-y-4">
      <PageHeader title="Kite connection" subtitle="Link your own Zerodha Kite Connect app. Your credentials belong to you: they are encrypted and no one else, including administrators, can see or use them." />
      <Suspense>
        <Notice />
      </Suspense>
      {conn.isError ? <ErrorBox error={conn.error} what="your Kite connection" /> : null}
      {conn.isLoading ? <Loading what="your Kite connection" /> : null}
      {conn.data ? (
        <>
          <Credentials c={conn.data} />
          <Connect c={conn.data} />
          {can("system:settings") ? <SystemFeed c={conn.data} /> : null}
        </>
      ) : null}
    </div>
  );
}
