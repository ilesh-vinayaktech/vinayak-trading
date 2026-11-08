"use client";

import { useState } from "react";
import { specOf, trimNumber } from "@/lib/indicators";
import type { IndicatorDef, IndicatorResult } from "@/lib/schemas";
import { Icon } from "./icons";

/** One indicator's line in a chart legend: name, the values at the crosshair, and its controls. */
export function IndicatorRow({ result, def, index, colors, onToggle, onRemove, onEdit, visible }: { result: IndicatorResult; def: IndicatorDef | undefined; index: number | null; colors: Record<string, string>; visible: boolean; onToggle: () => void; onRemove: () => void; onEdit: (spec: string) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);
  const at = index === null ? result.outputs.map((o) => o.values[o.values.length - 1]) : result.outputs.map((o) => o.values[index]);
  const apply = () => {
    if (!def) return;
    onEdit(specOf(def.name, def.params.map((p, i) => draft[i] ?? p.default)));
    setOpen(false);
  };
  return (
    <div className="pointer-events-auto relative flex items-center gap-2 rounded px-1 text-xs hover:bg-white/80" data-testid="indicator-row" data-spec={result.spec}>
      <span className={`font-medium ${visible ? "text-slate-800" : "text-slate-400 line-through"}`}>{result.label}</span>
      {visible
        ? result.outputs.map((o, i) => (
              <span key={o.key} className="font-mono" style={{ color: colors[o.key] ?? o.color }} title={o.label}>
                {trimNumber(at[i])}
              </span>
            ))
        : null}
      <span className="ml-1 flex items-center gap-1 text-slate-500">
        <button type="button" aria-label={`${visible ? "Hide" : "Show"} ${result.label}`} onClick={onToggle} className="hover:text-slate-900">
          <Icon name={visible ? "eye" : "eyeoff"} size={14} />
        </button>
        {def && def.params.length > 0 ? (
          <button type="button" aria-label={`Settings for ${result.label}`} aria-expanded={open} onClick={() => { setDraft(def.params.map((p) => result.params[p.key] ?? p.default)); setOpen((v) => !v); }} className="hover:text-slate-900">
            <Icon name="info" size={14} />
          </button>
        ) : null}
        <button type="button" aria-label={`Remove ${result.label}`} onClick={onRemove} className="hover:text-red-600">
          <Icon name="trash" size={14} />
        </button>
      </span>
      {open && def ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            apply();
          }}
          className="absolute left-0 top-full z-40 mt-1 w-60 rounded-lg border border-line bg-white p-3 shadow-xl"
          aria-label={`${def.label} settings`}
        >
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{def.label}</div>
          {def.params.map((p, i) => (
            <label key={p.key} className="mb-2 flex items-center justify-between gap-3 text-xs text-slate-700">
              {p.label}
              <input aria-label={p.label} type="number" min={p.min} max={p.max} step={p.integer ? 1 : "any"} value={draft[i] ?? ""} onChange={(e) => setDraft((d) => d.map((v, k) => (k === i ? e.target.value : v)))} className="w-24 rounded border border-line px-2 py-1 text-right" />
            </label>
          ))}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setOpen(false)} className="rounded px-2 py-1 text-xs text-slate-600 hover:bg-slate-100">
              Cancel
            </button>
            <button type="submit" className="rounded bg-slate-900 px-3 py-1 text-xs text-white">
              Apply
            </button>
          </div>
        </form>
      ) : null}
    </div>
  );
}
