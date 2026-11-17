"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorBox, Loading } from "@/components/status/LoadState";
import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";

const msg = (e: unknown) => (e instanceof ApiError ? e.message : "could not start");

/** The one place to run: the research families that have studies not run yet (tick a family or single studies), and strategy definitions with no study (run in a family you choose). Each goes through the trials,
 * the development verdict and, if it passes, the inner holdout by itself. */
export function RunPipelineDialog({ open, onClose, codeDirty }: { open: boolean; onClose: () => void; codeDirty: boolean }) {
  const qc = useQueryClient();
  const toast = useToast();
  const unrun = useQuery({ queryKey: ["pipeline", "unrun"], queryFn: api.pipelineUnrun, enabled: open });
  const defs = useQuery({ queryKey: ["intel", "definitions"], queryFn: api.intelDefinitions, enabled: open });
  const options = useQuery({ queryKey: ["study-options"], queryFn: api.studyOptions, enabled: open });
  const [studies, setStudies] = useState<number[]>([]);
  const [picked, setPicked] = useState<string[]>([]);
  const [family, setFamily] = useState("");
  const families = unrun.data?.families ?? [];
  const waiting = (defs.data?.definitions ?? []).filter((d) => d.study === "none");
  const key = (d: { strategy_id: string; version: number }) => `${d.strategy_id}@${d.version}`;
  const familyId = Number(family || options.data?.families[0]?.family_id || 1);
  const count = studies.length + picked.length;
  const run = useMutation({
    mutationFn: async () => {
      const failed: string[] = [];
      for (const id of studies) {
        try {
          await api.requestStudyRun(id, true);
        } catch (e) {
          failed.push(`study ${id}: ${msg(e)}`);
        }
      }
      for (const d of waiting.filter((w) => picked.includes(key(w)))) {
        try {
          await api.runDefinitionStudy(d.strategy_id, d.version, familyId, true);
        } catch (e) {
          failed.push(`${d.strategy_id}: ${msg(e)}`);
        }
      }
      return failed;
    },
    onSuccess: (failed) => {
      void qc.invalidateQueries({ queryKey: ["pipeline"] });
      void qc.invalidateQueries({ queryKey: ["intel"] });
      if (failed.length === 0) {
        toast.success("Queued. Follow them on this page.");
        setStudies([]);
        setPicked([]);
        onClose();
      } else toast.error(failed.join("; "));
    },
  });
  const toggleStudy = (id: number) => setStudies((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  const toggleFamily = (ids: number[]) => setStudies((s) => (ids.every((i) => s.includes(i)) ? s.filter((i) => !ids.includes(i)) : [...new Set([...s, ...ids])]));
  const nothing = unrun.data && defs.data && families.length === 0 && waiting.length === 0;
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
          <button type="button" className={buttonClass("primary")} disabled={count === 0 || run.isPending} onClick={() => run.mutate()}>
            {run.isPending ? "Starting..." : `Run ${count || ""} ${count === 1 ? "strategy" : "strategies"}`}
          </button>
        </>
      }
    >
      <div className="space-y-5">
        {codeDirty ? <Alert tone="warn">There is uncommitted code. A study registered now cannot be reproduced, so it could not be submitted to the outer holdout. Commit first if you mean to submit it.</Alert> : null}
        {unrun.isLoading || defs.isLoading || options.isLoading ? <Loading what="the strategies" /> : null}
        {unrun.isError ? <ErrorBox error={unrun.error} what="the families" /> : null}
        {nothing ? <p className="text-sm text-ink-soft">Everything registered has been run. Register a study (New study) or write new strategy definitions and they appear here.</p> : null}
        {families.length > 0 ? (
          <section className="space-y-2" aria-label="Families not run yet">
            <h3 className="text-sm font-semibold">Families not run yet</h3>
            {families.map((f) => {
              const ids = f.studies.map((s) => s.experiment_id);
              return (
                <div key={f.family_id} className="rounded-lg border border-line">
                  <label className="flex items-center gap-2 border-b border-line bg-slate-50 px-3 py-2 text-sm font-medium">
                    <input type="checkbox" checked={ids.every((i) => studies.includes(i))} onChange={() => toggleFamily(ids)} />
                    {f.name}
                    <span className="text-xs font-normal text-ink-soft">
                      {ids.length} {ids.length === 1 ? "study" : "studies"} not run
                    </span>
                  </label>
                  <ul className="divide-y divide-line">
                    {f.studies.map((s) => (
                      <li key={s.experiment_id}>
                        <label className="flex items-center gap-3 px-3 py-2 text-sm">
                          <input type="checkbox" checked={studies.includes(s.experiment_id)} onChange={() => toggleStudy(s.experiment_id)} />
                          <span className="font-medium">{s.name}</span>
                          <span className="text-xs text-ink-soft">{s.strategy_id}</span>
                        </label>
                      </li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </section>
        ) : null}
        {waiting.length > 0 ? (
          <section className="space-y-2" aria-label="Strategy definitions not run yet">
            <h3 className="text-sm font-semibold">Strategy definitions with no study yet</h3>
            {options.data ? (
              <div className="space-y-1.5">
                <label htmlFor="run-family" className="block text-sm font-medium">
                  Research family for these
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
            <ul className="max-h-60 divide-y divide-line overflow-y-auto rounded-lg border border-line">
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
          </section>
        ) : null}
      </div>
    </Dialog>
  );
}
