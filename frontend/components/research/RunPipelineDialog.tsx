"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorBox, Loading } from "@/components/status/LoadState";
import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";

/** The one place to run strategies: pick the research family and the strategies that have not been run yet, then run them. Each goes through the trials, the development verdict and (if it passes) the inner holdout by itself. */
export function RunPipelineDialog({ open, onClose, codeDirty }: { open: boolean; onClose: () => void; codeDirty: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const defs = useQuery({ queryKey: ["intel", "definitions"], queryFn: api.intelDefinitions, enabled: open });
  const options = useQuery({ queryKey: ["study-options"], queryFn: api.studyOptions, enabled: open });
  const [picked, setPicked] = useState<string[]>([]);
  const [family, setFamily] = useState("");
  const waiting = (defs.data?.definitions ?? []).filter((d) => d.study === "none");
  const key = (d: { strategy_id: string; version: number }) => `${d.strategy_id}@${d.version}`;
  const familyId = Number(family || options.data?.families[0]?.family_id || 1);
  const run = useMutation({
    mutationFn: async () => {
      const failed: string[] = [];
      for (const d of waiting.filter((w) => picked.includes(key(w)))) {
        try {
          await api.runDefinitionStudy(d.strategy_id, d.version, familyId, true);
        } catch (e) {
          failed.push(`${d.strategy_id}: ${e instanceof ApiError ? e.message : "could not start"}`);
        }
      }
      return failed;
    },
    onSuccess: (failed) => {
      void qc.invalidateQueries({ queryKey: ["pipeline"] });
      void qc.invalidateQueries({ queryKey: ["intel"] });
      if (failed.length === 0) {
        toast.success("Queued. Follow them on this page.");
        setPicked([]);
        onClose();
      } else toast.error(failed.join("; "));
    },
  });
  const all = waiting.length > 0 && picked.length === waiting.length;
  return (
    <Dialog
      open={open}
      title="Run strategies"
      description="Each one runs its trials, is judged against the development bar, and runs the inner holdout (2023-2024) if it passes. The outer holdout stays your separate step."
      onClose={onClose}
      footer={
        <>
          <button type="button" className={buttonClass("secondary")} onClick={onClose}>
            Cancel
          </button>
          <button type="button" className={buttonClass("primary")} disabled={picked.length === 0 || run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? "Starting..." : `Run ${picked.length || ""} ${picked.length === 1 ? "strategy" : "strategies"}`}
          </button>
        </>
      }
    >
      <div className="space-y-4">
        {codeDirty ? <Alert tone="warn">There is uncommitted code. A study registered now cannot be reproduced, so it could not be submitted to the outer holdout. Commit first if you mean to submit it.</Alert> : null}
        {defs.isLoading || options.isLoading ? <Loading what="the strategies" /> : null}
        {defs.isError ? <ErrorBox error={defs.error} what="the strategies" /> : null}
        {options.data ? (
          <div className="space-y-1.5">
            <label htmlFor="run-family" className="block text-sm font-medium">
              Research family
            </label>
            <select id="run-family" className={inputFull} value={family || String(options.data.families[0]?.family_id ?? "")} onChange={(e) => setFamily(e.target.value)}>
              {options.data.families.map((f) => (
                <option key={f.family_id} value={String(f.family_id)}>
                  {f.name} ({f.trials} tries so far)
                </option>
              ))}
            </select>
            <p className="text-xs text-ink-soft">Every try counts against the family, so the pass bar rises as the family grows.</p>
          </div>
        ) : null}
        {defs.data ? (
          waiting.length === 0 ? (
            <p className="text-sm text-ink-soft">Every strategy has been run already. New ones appear here once they are written.</p>
          ) : (
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm font-medium">
                <input type="checkbox" checked={all} onChange={() => setPicked(all ? [] : waiting.map(key))} />
                Not run yet ({waiting.length})
              </label>
              <ul className="max-h-72 divide-y divide-line overflow-y-auto rounded-lg border border-line">
                {waiting.map((d) => (
                  <li key={key(d)}>
                    <label className="flex items-start gap-3 px-3 py-2 text-sm">
                      <input className="mt-1" type="checkbox" checked={picked.includes(key(d))} onChange={() => setPicked((p) => (p.includes(key(d)) ? p.filter((x) => x !== key(d)) : [...p, key(d)]))} />
                      <span>
                        <span className="font-medium">{d.strategy_id}</span>
                        <span className="block text-xs text-ink-soft">{d.plain.summary}</span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          )
        ) : null}
      </div>
    </Dialog>
  );
}
