import clsx from "clsx";
import type { ReactNode } from "react";
import { StateChip } from "./StateChip";

export type Tone = "good" | "warn" | "bad" | "neutral";

const TONES: Record<Tone, string> = {
  good: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  warn: "bg-amber-50 text-amber-800 ring-amber-200",
  bad: "bg-red-50 text-red-800 ring-red-200",
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
};

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={clsx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", TONES[tone])}>
      {children}
    </span>
  );
}

/** A yes/no state shown as words as well as colour. */
export function Flag({ value, yes, no, goodWhen = true }: { value: boolean; yes: string; no: string; goodWhen?: boolean }) {
  const good = value === goodWhen;
  return <Badge tone={good ? "good" : "neutral"}>{value ? yes : no}</Badge>;
}

/** Eligibility is a state, not a tone: eligible and blocked must never look alike. */
export function Eligibility({ eligible, yes = "eligible", no = "blocked" }: { eligible: boolean; yes?: string; no?: string }) {
  return <StateChip state={eligible ? "ELIGIBLE" : "BLOCKED"} text={eligible ? yes : no} />;
}

export function severityTone(s: string): Tone {
  return s === "HIGH" ? "bad" : s === "MEDIUM" ? "warn" : "neutral";
}

export function findingStatusTone(s: string): Tone {
  return s === "RESOLVED" ? "good" : s === "UNRESOLVED" ? "warn" : "neutral";
}
