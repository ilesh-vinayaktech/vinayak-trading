"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

/** A modal dialog: dims the page, traps Tab inside, closes on Escape or a click outside, and hands focus back afterwards. */
export function Dialog({ open, title, description, onClose, children, footer }: { open: boolean; title: string; description?: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);
  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement;
    const first = panel.current?.querySelector<HTMLElement>("input, select, textarea, button:not([data-close])");
    (first ?? panel.current)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key !== "Tab" || !panel.current) return;
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      if (items.length === 0) return;
      const a = document.activeElement;
      if (e.shiftKey && a === items[0]) {
        e.preventDefault();
        items[items.length - 1]?.focus();
      } else if (!e.shiftKey && a === items[items.length - 1]) {
        e.preventDefault();
        items[0]?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      (opener.current as HTMLElement | null)?.focus?.();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center p-0 sm:items-center sm:p-4">
      <div aria-hidden="true" className="absolute inset-0 bg-slate-900/50" onClick={onClose} />
      <div ref={panel} tabIndex={-1} role="dialog" aria-modal="true" aria-label={title} className="relative flex max-h-[90vh] w-full max-w-lg flex-col rounded-t-2xl bg-white shadow-xl outline-none sm:rounded-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-4">
          <div>
            <h2 className="text-base font-semibold tracking-tight">{title}</h2>
            {description ? <p className="mt-0.5 text-sm text-ink-soft">{description}</p> : null}
          </div>
          <button type="button" data-close aria-label="Close dialog" onClick={onClose} className="-mr-2 rounded-lg p-1.5 text-ink-soft hover:bg-slate-100">
            <Icon name="close" />
          </button>
        </div>
        <div className="overflow-y-auto px-6 py-5">{children}</div>
        {footer ? <div className="flex flex-wrap justify-end gap-2 border-t border-line bg-slate-50 px-6 py-3 sm:rounded-b-2xl">{footer}</div> : null}
      </div>
    </div>
  );
}
