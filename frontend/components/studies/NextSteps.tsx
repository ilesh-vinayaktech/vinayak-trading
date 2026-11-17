"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { StatusPill } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import type { StudyVerdict } from "@/lib/schemas";

type Tone = "good" | "bad" | "warn" | "neutral";
const STEP_TONE: Record<Tone, string> = { good: "done", bad: "failed", warn: "next", neutral: "later" };

/** Where a passed strategy goes from here, step by step, so the page never ends at a badge: development verdict, the study's inner holdout, the one global holdout, then paper trading. */
export function NextSteps({ id, inner }: { id: number; inner: StudyVerdict["holdout"] }) {
  const list = useQuery({ queryKey: ["paper", "definitions"], queryFn: api.paperDefinitions });
  const mine = list.data?.definitions.find((d) => d.experiment_id === id);
  if (!mine) return null; // only a strategy definition goes on to paper trading
  const global = mine.state;
  const steps: { name: string; tone: Tone; text: string }[] = [
    { name: "Development verdict", tone: "good", text: "Passed every check." },
    {
      name: "Inner holdout (2023-2024)",
      tone: inner ? (inner.passed ? "good" : "bad") : "warn",
      text: inner ? (inner.passed ? "Passed. These days were seen when the features were chosen, so this is a sanity check." : "Failed.") : "Not opened yet. Optional: a sanity check, not the final test.",
    },
    {
      name: "Global holdout (2025 onward)",
      tone: global === "ready" ? "good" : global === "failed_holdout" ? "bad" : "warn",
      text: global === "ready" ? "Passed." : global === "failed_holdout" ? "Failed. This strategy stops here." : "Next. It is opened once, for every passing strategy together, by the owner (scripts/research_holdout.py). It cannot be repeated.",
    },
    {
      name: "Paper trading",
      tone: global === "ready" ? "warn" : "neutral",
      text: global === "ready" ? "Available now." : "Opens only after the global holdout is passed.",
    },
  ];
  return (
    <div className="space-y-2 border-t border-line pt-4" data-testid="next-steps">
      <h3 className="text-sm font-medium">What happens next</h3>
      <ol className="space-y-1.5 text-sm">
        {steps.map((s) => (
          <li key={s.name} className="flex flex-wrap items-baseline gap-2">
            <StatusPill tone={s.tone}>{STEP_TONE[s.tone]}</StatusPill>
            <span className="font-medium">{s.name}</span>
            <span className="text-xs text-ink-soft">{s.text}</span>
          </li>
        ))}
      </ol>
      {global === "ready" ? <p className="text-sm"><Link href="/paper" className="font-medium text-brand underline">Go to Paper trading</Link></p> : null}
    </div>
  );
}
