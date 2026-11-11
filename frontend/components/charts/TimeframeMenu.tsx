"use client";

import { useEffect, useRef, useState } from "react";
import type { Timeframe } from "@/lib/schemas";
import { TIMEFRAME_GROUPS, TIMEFRAME_LABELS } from "@/lib/timeframes";

/** A dropdown of timeframes in sections (minutes, hours, days), like a charting terminal's interval menu. */
export function TimeframeMenu({ value, onChange, className }: { value: Timeframe; onChange: (t: Timeframe) => void; className: string }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return (
    <div ref={root} className="relative">
      <button type="button" aria-haspopup="menu" aria-expanded={open} aria-label={`Timeframe: ${TIMEFRAME_LABELS[value]}`} title="Timeframe" onClick={() => setOpen((o) => !o)} className={`${className} min-w-[3rem] gap-1 font-medium`}>
        {TIMEFRAME_LABELS[value]}
        <span aria-hidden="true" className="text-[10px] text-slate-500">▾</span>
      </button>
      {open ? (
        <div role="menu" aria-label="Timeframes" className="absolute left-0 top-9 z-40 max-h-96 w-48 overflow-y-auto rounded-md border border-line bg-white py-1 shadow-lg">
          {TIMEFRAME_GROUPS.map((g) => (
            <div key={g.title} role="group" aria-label={g.title}>
              <div className="px-3 pb-1 pt-2 text-[11px] font-semibold tracking-wide text-slate-500">{g.title}</div>
              {g.items.map((i) => (
                <button key={i.value} type="button" role="menuitemradio" aria-checked={i.value === value} onClick={() => { onChange(i.value); setOpen(false); }} className={`flex w-full items-center justify-between px-3 py-1.5 text-left text-[13px] hover:bg-slate-100 ${i.value === value ? "font-medium text-blue-700" : "text-slate-800"}`}>
                  {i.name}
                  {i.value === value ? <span aria-hidden="true">✓</span> : null}
                </button>
              ))}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
