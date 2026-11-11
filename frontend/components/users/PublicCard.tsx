import type { ReactNode } from "react";
import { buttonClass, inputFull } from "@/components/ui/styles";

/** The centred card the signed-out pages (sign in, forgot password, accept invitation, reset) share. */
export function PublicCard({ title, subtitle, children, onSubmit }: { title: string; subtitle?: string; children: ReactNode; onSubmit: (e: React.FormEvent) => void }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-gradient-to-b from-slate-50 to-slate-100 px-4 py-10">
      <div className="mb-6 flex items-center gap-3">
        <span aria-hidden="true" className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand text-lg font-bold text-white shadow-card">V</span>
        <span>
          <span className="block text-base font-semibold leading-tight">Vinayak</span>
          <span className="block text-xs text-ink-soft">Trading Research Console</span>
        </span>
      </div>
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-5 rounded-2xl border border-line bg-white p-7 shadow-card" aria-labelledby="card-title">
        <div>
          <h1 id="card-title" className="text-xl font-semibold tracking-tight">{title}</h1>
          {subtitle ? <p className="mt-1 text-sm text-ink-soft">{subtitle}</p> : null}
        </div>
        {children}
      </form>
      <p className="mt-6 text-xs text-ink-faint">Access is by invitation. Your activity is recorded.</p>
    </main>
  );
}

export const fieldClass = inputFull;
export const primaryClass = `${buttonClass("primary")} w-full`;
