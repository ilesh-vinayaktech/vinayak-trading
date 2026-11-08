import type { ReactNode } from "react";
import { ApiError } from "@/lib/api/client";

export function Loading({ what }: { what: string }) {
  return (
    <p className="text-sm text-ink-soft" role="status">
      Loading {what}…
    </p>
  );
}

export function ErrorBox({ error, what }: { error: unknown; what: string }) {
  const msg = error instanceof ApiError ? `${error.status}: ${error.message}` : String(error);
  return (
    <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-800" role="alert">
      Could not load {what}. {msg}
      <div className="mt-1 text-xs text-red-700">Is the API running? Start it with: ALGO_DB_URL=... uv run uvicorn --factory algo.api.main:build --port 8000</div>
    </div>
  );
}

export function Card({ title, children, note }: { title: string; children: ReactNode; note?: string }) {
  return (
    <section className="rounded-lg border border-line bg-panel p-4 shadow-sm">
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {children}
      {note ? <p className="mt-3 text-xs text-ink-faint">{note}</p> : null}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div>
      <div className="text-xs text-ink-soft">{label}</div>
      <div className="text-lg font-semibold tabular-nums">{value}</div>
      {hint ? <div className="text-xs text-ink-faint">{hint}</div> : null}
    </div>
  );
}
