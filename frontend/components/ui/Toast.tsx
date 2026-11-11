"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Icon } from "./Icon";

type Tone = "success" | "error" | "info";
type Toast = { id: number; tone: Tone; text: string };
type Notify = (tone: Tone, text: string) => void;
const ToastContext = createContext<Notify | null>(null);
const LIFETIME_MS = 6000;

/** Brief confirmations ("Saved.") that do not shift the page and clear themselves; errors stay until dismissed. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const next = useRef(1);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const notify = useCallback<Notify>((tone, text) => setToasts((t) => [...t.slice(-3), { id: next.current++, tone, text }]), []);
  return (
    <ToastContext.Provider value={notify}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2" aria-live="polite">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

const STYLE: Record<Tone, string> = { success: "border-emerald-200", error: "border-red-200", info: "border-blue-200" };
const ICON = { success: "check", error: "alert", info: "info" } as const;

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: (id: number) => void }) {
  useEffect(() => {
    if (toast.tone === "error") return;
    const t = setTimeout(() => onDismiss(toast.id), LIFETIME_MS);
    return () => clearTimeout(t);
  }, [toast, onDismiss]);
  return (
    <div role={toast.tone === "error" ? "alert" : "status"} className={`pointer-events-auto flex items-start gap-3 rounded-xl border bg-white px-4 py-3 text-sm shadow-lg ${STYLE[toast.tone]}`}>
      <Icon name={ICON[toast.tone]} size={18} className={toast.tone === "success" ? "mt-0.5 text-emerald-600" : toast.tone === "error" ? "mt-0.5 text-red-600" : "mt-0.5 text-blue-600"} />
      <p className="flex-1">{toast.text}</p>
      <button type="button" aria-label="Dismiss" onClick={() => onDismiss(toast.id)} className="-mr-1 text-ink-faint hover:text-ink-soft">
        <Icon name="close" size={16} />
      </button>
    </div>
  );
}

export function useToast(): { success: (text: string) => void; error: (text: string) => void; info: (text: string) => void } {
  const notify = useContext(ToastContext);
  if (!notify) throw new Error("useToast outside ToastProvider");
  return useMemo(() => ({ success: (text: string) => notify("success", text), error: (text: string) => notify("error", text), info: (text: string) => notify("info", text) }), [notify]);
}
