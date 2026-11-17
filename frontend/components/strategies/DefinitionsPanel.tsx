"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { ErrorBox, Loading } from "@/components/status/LoadState";
import { EmptyState } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { api } from "@/lib/api/client";

const STUDY_TEXT = { none: "no study yet", registered: "study registered", running: "study running", stopped: "run stopped early", done: "trials done, not judged", judged: "judged" } as const;

/** The strategy definitions written so far, each with its rule in words and how far its study has got. With `canRun`, its study can be opened for the trials, equity curves and verdict. Running is done from the Strategy pipeline page. */
export function DefinitionsPanel({ canRun = false }: { canRun?: boolean }) {
  const defs = useQuery({ queryKey: ["intel", "definitions"], queryFn: api.intelDefinitions, refetchInterval: 15000 });
  return (
    <Panel title="Strategy definitions" actions={<span className="text-xs text-ink-faint">written from alpha candidates; run them from the Strategy pipeline page</span>}>
      {defs.isLoading ? (
        <Loading what="the strategy definitions" />
      ) : defs.error ? (
        <ErrorBox error={defs.error} what="the strategy definitions" />
      ) : !defs.data || defs.data.definitions.length === 0 ? (
        <EmptyState title="No definitions yet">Run scripts/generate_strategies.py to write one for each alpha candidate.</EmptyState>
      ) : (
        <ul className="divide-y divide-line px-5" aria-label="Strategy definitions">
          {defs.data.definitions.map((d) => (
            <li key={`${d.strategy_id}-${d.version}`} className="py-2 text-sm" data-testid="definition">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{d.strategy_id}</span>
                <span className="text-xs text-ink-faint">v{d.version} · {d.rebalance.toLowerCase()} · up to {d.max_positions} stocks</span>
                <span className="text-xs text-ink-soft">{STUDY_TEXT[d.study]}{d.trials_done > 0 ? ` (${d.trials_done} ${d.trials_done === 1 ? "trial" : "trials"})` : ""}{d.study_name ? ` · ${d.study_name.replace(`${d.strategy_id} v${d.version} `, "")}` : ""}</span>
                {d.earlier_verdict !== null && d.study === "none" ? <span className="text-xs text-ink-faint">earlier setup: {d.earlier_verdict ? "passed" : "failed"} validation</span> : null}
                {d.verdict !== null ? <StatusPill tone={d.verdict ? "good" : "bad"}>{d.verdict ? "passed" : "failed validation"}</StatusPill> : null}
                {canRun ? (
                  <span className="ml-auto inline-flex gap-2">
                    {d.experiment_id !== null ? <Link href={`/research/studies/${d.experiment_id}`} className={buttonClass("secondary")}>Open study</Link> : null}
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-sm font-medium text-ink" data-testid="definition-summary">{d.plain.summary}</p>
              <ul className="mt-1 space-y-0.5 text-sm text-ink-soft" aria-label="In plain words">
                <li>{d.plain.buy}</li>
                <li>{d.plain.sell}</li>
                <li>{d.plain.size}</li>
              </ul>
              <details className="mt-1 text-xs text-ink-faint">
                <summary className="cursor-pointer">Technical rule</summary>
                Buy: {d.entry}. Sell: {d.exit}.
              </details>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
