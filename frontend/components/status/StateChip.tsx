import clsx from "clsx";

// The six states that must never look interchangeable. Each has its own colour AND glyph AND word,
// so they stay distinguishable without colour.
export type PlatformState = "ELIGIBLE" | "BLOCKED" | "UNKNOWN" | "UNRESOLVED" | "NOT_CONFIGURED" | "NOT_IMPLEMENTED";

const STYLE: Record<PlatformState, { glyph: string; classes: string; label: string }> = {
  ELIGIBLE: { glyph: "✓", classes: "bg-emerald-50 text-emerald-800 ring-emerald-300", label: "eligible" },
  BLOCKED: { glyph: "⛔", classes: "bg-red-50 text-red-800 ring-red-300", label: "blocked" },
  UNKNOWN: { glyph: "?", classes: "bg-slate-100 text-slate-700 ring-slate-300 border-dashed", label: "unknown" },
  UNRESOLVED: { glyph: "!", classes: "bg-amber-50 text-amber-900 ring-amber-400", label: "unresolved" },
  NOT_CONFIGURED: { glyph: "○", classes: "bg-white text-slate-600 ring-slate-300", label: "not configured" },
  NOT_IMPLEMENTED: { glyph: "◌", classes: "bg-violet-50 text-violet-800 ring-violet-300", label: "not implemented" },
};

export function StateChip({ state, text }: { state: PlatformState; text?: string }) {
  const s = STYLE[state];
  return (
    <span data-state={state} className={clsx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", s.classes)}>
      <span aria-hidden="true">{s.glyph}</span>
      {text ?? s.label}
    </span>
  );
}
