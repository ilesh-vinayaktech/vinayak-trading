import type { ReactNode } from "react";

/** The centred card the signed-out pages (sign in, forgot password, accept invitation, reset) share. */
export function PublicCard({ title, subtitle, children, onSubmit }: { title: string; subtitle?: string; children: ReactNode; onSubmit: (e: React.FormEvent) => void }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4 rounded-lg border border-line bg-white p-6 shadow-sm" aria-labelledby="card-title">
        <div>
          <h1 id="card-title" className="text-lg font-semibold">{title}</h1>
          <p className="text-xs text-ink-soft">{subtitle ?? "Vinayak Trading Research Console"}</p>
        </div>
        {children}
      </form>
    </main>
  );
}

export const fieldClass = "w-full rounded-md border border-line bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100";
export const primaryClass = "w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50";
