"use client";

import { useState, type ReactNode } from "react";
import { buttonClass } from "@/components/ui/styles";

/** A button that asks "are you sure?" in place before doing something that signs people out or removes access. */
export function ConfirmButton({ children, question, confirmLabel, onConfirm, disabled, tone = "neutral" }: { children: ReactNode; question: string; confirmLabel: string; onConfirm: () => void; disabled?: boolean; tone?: "neutral" | "danger" }) {
  const [asking, setAsking] = useState(false);
  if (asking) {
    return (
      <span className="inline-flex flex-wrap items-center gap-2 rounded-lg border border-line bg-white px-2.5 py-1.5 text-xs shadow-sm" role="group" aria-label={question}>
        {question}
        <button
          type="button"
          onClick={() => {
            setAsking(false);
            onConfirm();
          }}
          className={buttonClass(tone === "danger" ? "danger" : "primary", true)}
        >
          {confirmLabel}
        </button>
        <button type="button" onClick={() => setAsking(false)} className={buttonClass("secondary", true)}>
          Cancel
        </button>
      </span>
    );
  }
  return (
    <button type="button" disabled={disabled} onClick={() => setAsking(true)} className={buttonClass("secondary")}>
      {children}
    </button>
  );
}
