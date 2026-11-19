"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/status/Badge";
import { api } from "@/lib/api/client";
import type { Instrument } from "@/lib/schemas";
import { Icon } from "./icons";

/** Symbol search as a popover under the toolbar: type, pick (click, or the arrow keys and Enter), it closes. */
export function SymbolSearch({ current, onPick }: { current: string | null; onPick: (i: Instrument) => void }) {
  const [open, setOpen] = useState(current === null);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0); // the row the arrow keys are on; Enter picks it
  const root = useRef<HTMLDivElement>(null);
  const search = useQuery({ queryKey: ["search", q], queryFn: () => api.searchInstruments(q), enabled: open && q.trim().length >= 1 });

  const rows = search.data ?? [];
  useEffect(() => setActive(0), [search.data]); // a new list starts on its first row
  useEffect(() => {
    document.getElementById(`symbol-match-${active}`)?.scrollIntoView?.({ block: "nearest" }); // keep the row in view in a long list
  }, [active, search.data]);
  const pick = (i: Instrument) => {
    onPick(i);
    setQ("");
    setOpen(false);
  };
  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") setOpen(false);
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); // the caret should not jump to the ends of the text
      if (rows.length > 0) setActive((a) => Math.min(rows.length - 1, Math.max(0, a + (e.key === "ArrowDown" ? 1 : -1))));
    } else if (e.key === "Enter" && rows[active]) {
      e.preventDefault();
      pick(rows[active]);
    }
  };

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (root.current && !root.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  return (
    <div ref={root} className="relative">
      <button type="button" aria-haspopup="listbox" aria-expanded={open} onClick={() => setOpen((v) => !v)} className="flex h-8 items-center gap-2 rounded-md px-2 text-sm font-semibold text-slate-900 hover:bg-slate-100">
        <Icon name="search" size={16} className="text-slate-500" />
        {current ?? "Search symbol"}
      </button>
      {open ? (
        <div className="absolute left-0 top-full z-50 mt-1 w-[26rem] max-w-[90vw] rounded-lg border border-line bg-white p-2 shadow-xl">
          <label className="sr-only" htmlFor="q">
            Symbol, ISIN or name
          </label>
          <input id="q" autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} aria-activedescendant={rows[active] ? `symbol-match-${active}` : undefined} placeholder="Symbol, ISIN or name (RELIANCE, INE002A01018)" className="w-full rounded-md border border-line px-3 py-2 text-sm outline-none focus:border-blue-500" />
          {search.isLoading && q ? <p className="px-2 py-2 text-xs text-slate-500">Searching…</p> : null}
          {search.error ? <p className="px-2 py-2 text-xs text-red-700">The search failed. Is the API running?</p> : null}
          {search.data ? (
            <ul className="mt-2 max-h-72 overflow-y-auto" aria-label="Matches">
              {search.data.length === 0 ? <li className="px-2 py-2 text-sm text-slate-500">No instrument matches.</li> : null}
              {search.data.map((i, n) => (
                <li key={i.id}>
                  <button id={`symbol-match-${n}`} type="button" tabIndex={-1} aria-current={n === active ? "true" : undefined} onClick={() => pick(i)} onMouseMove={() => setActive(n)} className={`flex w-full items-center justify-between gap-3 rounded-md px-2 py-2 text-left text-sm ${n === active ? "bg-blue-50 ring-1 ring-blue-200" : "hover:bg-slate-100"}`}>
                    <span className="min-w-0">
                      <span className="font-semibold">{i.symbol}</span> <span className="truncate text-slate-500">{i.name}</span>
                    </span>
                    <span className="flex shrink-0 items-center gap-2 text-[11px] text-slate-500">
                      {i.isin}
                      <Badge tone={i.status === "active" ? "good" : "neutral"}>{i.status}</Badge>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
