"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "next/navigation";
import { PageHeader } from "@/components/layout/PageHeader";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Field } from "@/components/ui/Field";
import { Panel, SettingsSection, StatusPill } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ConfirmButton } from "@/components/users/ConfirmButton";
import { ApiError, api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { fmtIst } from "@/lib/formatting";
import type { KiteConnection } from "@/lib/schemas";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Something went wrong. Try again.");
type Pill = "good" | "warn" | "bad" | "neutral";
const LABEL: Record<KiteConnection["state"], { text: string; tone: Pill }> = {
  not_configured: { text: "Not set up", tone: "neutral" },
  saved: { text: "Credentials saved, not connected", tone: "warn" },
  connected: { text: "Connected", tone: "good" },
  expired: { text: "Expired: connect again", tone: "bad" },
};

function Credentials({ c }: { c: KiteConnection }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [key, setKey] = useState("");
  const [secret, setSecret] = useState("");
  const save = useMutation({
    mutationFn: () => api.kiteSave(key, secret),
    onSuccess: () => {
      setKey("");
      setSecret(""); // the secret does not stay in the page once it has been sent
      toast.success("Saved.");
      void qc.invalidateQueries({ queryKey: ["kite"] });
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };
  return (
    <SettingsSection title="Your Kite Connect app" description="Create an app in your Kite Connect developer account and set its Redirect URL to the address shown here. The key and secret are stored encrypted and are never shown again.">
      <div className="space-y-5">
        <Field id="redirect" label="Redirect URL to register">
          <code id="redirect" className="block break-all rounded-lg border border-line bg-slate-50 px-3 py-2 font-mono text-xs" data-testid="redirect-url">{c.redirect_url}</code>
        </Field>
        {c.api_key_hint ? <p className="text-sm text-ink-soft">Saved key ending <code className="font-mono">{c.api_key_hint}</code>. Enter new values to replace it.</p> : null}
        <form onSubmit={submit} className="space-y-4">
          <Field id="api-key" label="API key">
            <input id="api-key" autoComplete="off" spellCheck={false} required value={key} onChange={(e) => setKey(e.target.value)} className={`${inputFull} font-mono`} />
          </Field>
          <Field id="api-secret" label="API secret">
            <input id="api-secret" type="password" autoComplete="new-password" spellCheck={false} required value={secret} onChange={(e) => setSecret(e.target.value)} className={`${inputFull} font-mono`} />
          </Field>
          {save.isError ? <Alert tone="error">{message(save.error)}</Alert> : null}
          <button type="submit" disabled={save.isPending} className={buttonClass("primary")}>{c.api_key_hint ? "Replace credentials" : "Save credentials"}</button>
        </form>
      </div>
    </SettingsSection>
  );
}

function Connect({ c }: { c: KiteConnection }) {
  const qc = useQueryClient();
  const toast = useToast();
  const start = useMutation({
    mutationFn: api.kiteStart,
    onSuccess: (r) => window.location.assign(r.login_url), // off to Zerodha; it sends the browser back to the redirect URL
  });
  const disconnect = useMutation({ mutationFn: api.kiteDisconnect, onSuccess: () => { toast.success("Disconnected."); void qc.invalidateQueries({ queryKey: ["kite"] }); } });
  const remove = useMutation({ mutationFn: api.kiteRemove, onSuccess: () => { toast.success("Credentials removed."); void qc.invalidateQueries({ queryKey: ["kite"] }); } });
  const configured = c.state !== "not_configured";
  return (
    <SettingsSection title="Connection" description="Zerodha asks you to sign in again every day. The connection ends at 06:00 IST.">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <StatusPill tone={LABEL[c.state].tone}>{LABEL[c.state].text}</StatusPill>
          {c.kite_user_id ? <span className="text-sm text-ink-soft">Zerodha user {c.kite_user_id}</span> : null}
          {c.token_expires_at && c.state === "connected" ? <span className="text-sm text-ink-soft">until {fmtIst(c.token_expires_at)}</span> : null}
        </div>
        {start.isError ? <Alert tone="error">{message(start.error)}</Alert> : null}
        <div className="flex flex-wrap gap-2">
          <button type="button" disabled={!configured || start.isPending} onClick={() => start.mutate()} className={buttonClass("primary")}>
            {c.state === "connected" ? "Reconnect to Zerodha" : "Connect to Zerodha"}
          </button>
          {c.state === "connected" ? <ConfirmButton question="Disconnect from Kite?" confirmLabel="Disconnect" onConfirm={() => disconnect.mutate()}>Disconnect</ConfirmButton> : null}
          {configured ? <ConfirmButton tone="danger" question="Remove your saved Kite credentials?" confirmLabel="Remove" onConfirm={() => remove.mutate()}>Remove credentials</ConfirmButton> : null}
        </div>
      </div>
    </SettingsSection>
  );
}

function SystemFeed({ c }: { c: KiteConnection }) {
  const qc = useQueryClient();
  const toast = useToast();
  const feed = useQuery({ queryKey: ["kite", "system"], queryFn: api.kiteSystem });
  const set = useMutation({ mutationFn: (enabled: boolean) => api.kiteSetSystem(enabled), onSuccess: (_d, enabled) => { toast.success(enabled ? "Your connection is now the data feed." : "Your connection no longer feeds the loaders."); void qc.invalidateQueries({ queryKey: ["kite"] }); } });
  const f = feed.data?.feed ?? null;
  return (
    <SettingsSection title="System data feed" description="The data loaders use this connection instead of a credentials file. Only one connection can be the feed.">
      <div className="space-y-4">
        <p className="text-sm">
          {f ? (
            <>
              Used now: <span className="font-medium">{f.owner}</span> (key ending {f.api_key_hint}) <StatusPill tone={LABEL[f.state].tone}>{LABEL[f.state].text}</StatusPill>
            </>
          ) : (
            "No connection is the data feed yet."
          )}
        </p>
        {set.isError ? <Alert tone="error">{message(set.error)}</Alert> : null}
        {c.is_system ? (
          <button type="button" onClick={() => set.mutate(false)} className={buttonClass("secondary")}>Stop using my connection as the feed</button>
        ) : (
          <button type="button" onClick={() => set.mutate(true)} className={buttonClass("secondary")}>Use my connection as the data feed</button>
        )}
      </div>
    </SettingsSection>
  );
}

function Notice() {
  const toast = useToast();
  const q = useSearchParams();
  const connected = q.get("connected");
  useEffect(() => {
    if (connected) toast.success("Connected to Zerodha for today.");
  }, [connected, toast]);
  const error = q.get("error");
  return error ? <Alert tone="error">{error}</Alert> : null;
}

export default function KitePage() {
  const { can } = useAuth();
  const conn = useQuery({ queryKey: ["kite", "connection"], queryFn: api.kiteConnection });
  return (
    <div className="max-w-5xl">
      <PageHeader title="Kite connection" subtitle="Link your own Zerodha Kite Connect app. Your credentials belong to you: they are encrypted and no one else, including administrators, can see or use them." />
      <Suspense>
        <Notice />
      </Suspense>
      {conn.isError ? <Alert tone="error" title="Could not load your Kite connection">{message(conn.error)}</Alert> : null}
      {conn.isLoading ? (
        <div role="status" aria-label="Loading your Kite connection" className="space-y-3"><Skeleton className="h-6 w-48" /><Skeleton className="h-40 w-full" /></div>
      ) : null}
      {conn.data ? (
        <Panel>
          <div className="px-6 py-6">
            <Credentials c={conn.data} />
            <Connect c={conn.data} />
            {can("system:settings") ? <SystemFeed c={conn.data} /> : null}
          </div>
        </Panel>
      ) : null}
    </div>
  );
}
