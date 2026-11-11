"use client";

import { useState, type ReactNode } from "react";
import { Icon } from "./Icon";
import { inputFull } from "./styles";

/** A form field with its label ABOVE the control, optional hint and error. The control gets `id`; the label points at it. */
export function Field({ id, label, hint, error, children }: { id: string; label: string; hint?: ReactNode; error?: string | null; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-red-700" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-ink-soft">{hint}</p>
      ) : null}
    </div>
  );
}

type PasswordProps = { id: string; value: string; onChange: (v: string) => void; autoComplete: "current-password" | "new-password"; required?: boolean; minLength?: number; readOnly?: boolean };

/** A password box with a show/hide button. The button is a real control with a state (aria-pressed), not just an icon. */
export function PasswordInput({ id, value, onChange, autoComplete, required = true, minLength, readOnly }: PasswordProps) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <input id={id} type={shown ? "text" : "password"} autoComplete={autoComplete} required={required} minLength={minLength} readOnly={readOnly} value={value} onChange={(e) => onChange(e.target.value)} className={`${inputFull} pr-10`} />
      <button type="button" aria-label={shown ? "Hide password" : "Show password"} aria-pressed={shown} onClick={() => setShown((s) => !s)} className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-ink-faint hover:text-ink-soft">
        <Icon name={shown ? "eyeOff" : "eye"} size={18} />
      </button>
    </div>
  );
}
