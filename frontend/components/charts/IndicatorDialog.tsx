"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { IndicatorDef } from "@/lib/schemas";
import { Icon } from "./icons";

const GROUP_ORDER = ["Trend", "Momentum", "Volatility", "Volume"];

/** TradingView-style indicator picker: search, grouped list, click to add with default settings. */
export function IndicatorDialog({ catalog, counts, atLimit, onAdd, onClose }: { catalog: IndicatorDef[]; counts: Record<string, number>; atLimit: boolean; onAdd: (def: IndicatorDef) => void; onClose: () => void }) {
  const [q, setQ] = useState("");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return catalog.filter((d) => !needle || `${d.name} ${d.label} ${d.group} ${d.description}`.toLowerCase().includes(needle));
  }, [catalog, q]);
  const groups = [...new Set([...GROUP_ORDER, ...shown.map((d) => d.group)])].filter((g) => shown.some((d) => d.group === g));

  return (
    <div className="fixed inset-0 z-[60] flex items-start justify-center bg-slate-900/40 p-4 pt-24" onMouseDown={(e) => e.target === e.currentTarget && onClose()} role="presentation">
      <div ref={box} role="dialog" aria-modal="true" aria-label="Indicators" className="flex max-h-[70vh] w-[34rem] max-w-full flex-col overflow-hidden rounded-xl bg-white shadow-2xl">
        <div className="flex items-center gap-2 border-b border-line px-4 py-3">
          <span className="text-sm font-semibold">Indicators</span>
          <span className="flex-1" />
          <button type="button" aria-label="Close" onClick={onClose} className="rounded p-1 text-slate-500 hover:bg-slate-100">
            ✕
          </button>
        </div>
        <div className="flex items-center gap-2 border-b border-line px-4 py-2">
          <Icon name="search" size={16} className="text-slate-400" />
          <input autoFocus aria-label="Search indicators" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search (RSI, moving average, volatility…)" className="w-full text-sm outline-none" />
        </div>
        {atLimit ? <p className="bg-amber-50 px-4 py-2 text-xs text-amber-900">The chart already has the maximum number of indicators; remove one to add another.</p> : null}
        <div className="overflow-y-auto py-1">
          {groups.length === 0 ? <p className="px-4 py-6 text-center text-sm text-slate-500">No indicator matches.</p> : null}
          {groups.map((g) => (
            <section key={g} aria-label={g}>
              <h3 className="px-4 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-slate-400">{g}</h3>
              <ul>
                {shown
                  .filter((d) => d.group === g)
                  .map((d) => (
                    <li key={d.name}>
                      <button type="button" disabled={atLimit} onClick={() => onAdd(d)} className="flex w-full items-start gap-3 px-4 py-2 text-left hover:bg-slate-50 disabled:opacity-40" data-indicator={d.name}>
                        <span className="min-w-0 flex-1">
                          <span className="block text-[13px] font-medium text-slate-900">{d.label}</span>
                          <span className="block truncate text-xs text-slate-500">{d.description}</span>
                        </span>
                        <span className="mt-0.5 shrink-0 rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-600">{d.pane === "overlay" ? "on chart" : "own pane"}</span>
                        {counts[d.name] ? <span className="mt-0.5 shrink-0 rounded-full bg-blue-50 px-2 py-0.5 text-[10px] text-blue-700">{counts[d.name]} added</span> : null}
                      </button>
                    </li>
                  ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
