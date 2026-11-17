"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { SettingsSection } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";

const STATE_TEXT = {
  awaiting_holdout: "Passed its development test. Waiting for the global holdout (2025 onward), which opens once for all strategies.",
  failed_holdout: "Failed the global holdout: it cannot be paper traded.",
  ready: "Passed the global holdout.",
} as const;

/** Research strategies on the way to paper trading. Only one that passed the global holdout can be started; the others show where they stand. */
export function DefinitionsSection({ hasAccount, current }: { hasAccount: boolean; current: string | null }) {
  const qc = useQueryClient();
  const toast = useToast();
  const list = useQuery({ queryKey: ["paper", "definitions"], queryFn: api.paperDefinitions });
  const start = useMutation({
    mutationFn: (experimentId: number) => api.startPaperDefinition(experimentId),
    onSuccess: () => {
      toast.success("Strategy changed. It applies from the next daily decision.");
      void qc.invalidateQueries({ queryKey: ["paper"] });
      void qc.invalidateQueries({ queryKey: ["strategies"] });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not start it."),
  });
  const rows = list.data?.definitions ?? [];
  return (
    <SettingsSection title="Strategies from research" description="A researched strategy can be paper traded only after it passes the global holdout, the one final test on 2025 onward.">
      {list.isLoading ? <p className="text-sm text-ink-soft">Loading...</p> : list.isError ? <p className="text-sm text-ink-soft">Only the owner can see the state of researched strategies.</p> : rows.length === 0 ? <p className="text-sm text-ink-soft">No researched strategy has passed its development test yet.</p> : (
        <ul className="divide-y divide-line" aria-label="Strategies from research">
          {rows.map((d) => (
            <li key={d.experiment_id} className="flex flex-wrap items-center gap-3 py-2 text-sm" data-testid="research-strategy">
              <div className="min-w-0 flex-1">
                <div className="font-medium">{d.strategy_id} <span className="text-xs font-normal text-ink-faint">v{d.version}</span></div>
                <div className="text-xs text-ink-soft">{current === d.name ? "Running on your account. " : ""}{STATE_TEXT[d.state]}</div>
              </div>
              {d.state === "ready" ? (
                <button type="button" className={buttonClass("secondary")} disabled={!hasAccount || current === d.name || start.isPending} title={hasAccount ? undefined : "Start a paper account first"} onClick={() => start.mutate(d.experiment_id)}>
                  {current === d.name ? "In use" : "Paper trade this"}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </SettingsSection>
  );
}
