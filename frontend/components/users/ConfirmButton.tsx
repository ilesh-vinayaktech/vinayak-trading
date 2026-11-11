"use client";

import { useState, type ReactNode } from "react";

/** A button that asks "are you sure?" in place before doing something that signs people out or removes access. */
export function ConfirmButton({ children, question, confirmLabel, onConfirm, disabled, tone = "neutral" }: { children: ReactNode; question: string; confirmLabel: string; onConfirm: () => void; disabled?: boolean; tone?: "neutral" | "danger" }) {
  const [asking, setAsking] = useState(false);
  if (asking) {
    return (
      <span className="inline-flex flex-wrap items-center gap-2 rounded-md border border-line bg-white px-2 py-1 text-xs" role="group" aria-label={question}>
        {question}
        <button
          type="button"
          onClick={() => {
            setAsking(false);
            onConfirm();
          }}
          className={tone === "danger" ? "rounded bg-red-700 px-2 py-1 font-medium text-white" : "rounded bg-slate-900 px-2 py-1 font-medium text-white"}
        >
          {confirmLabel}
        </button>
        <button type="button" onClick={() => setAsking(false)} className="rounded border border-line px-2 py-1">
          Cancel
        </button>
      </span>
    );
  }
  return (
    <button type="button" disabled={disabled} onClick={() => setAsking(true)} className="rounded-md border border-line bg-white px-3 py-1.5 text-sm hover:bg-slate-50 disabled:opacity-40">
      {children}
    </button>
  );
}
