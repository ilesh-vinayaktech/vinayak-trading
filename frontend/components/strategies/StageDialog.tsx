"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";
import { fmtDateTime } from "@/lib/formatting";
import type { StrategyConfig } from "@/lib/schemas";

const STAGES = ["RESEARCH", "PAPER", "LIVE"] as const;
export const STAGE_LABEL = { RESEARCH: "Research", PAPER: "Paper trading", LIVE: "Live" } as const;
const message = (e: unknown) => (e instanceof ApiError ? e.message : "Could not move the strategy. Try again.");

/** Move a strategy between research, paper trading and live. Up needs a reason; live also needs the backtest run that justifies it,
 *  and the server lists every reason it is refused. Moving down is always allowed. */
export function StageDialog({ strategy, onClose }: { strategy: StrategyConfig; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const now = STAGES.indexOf(strategy.stage);
  const targets = STAGES.filter((s, i) => s !== strategy.stage && (i < now || i === now + 1));
  const [to, setTo] = useState<string>(targets[0] ?? "");
  const [reason, setReason] = useState("");
  const [runId, setRunId] = useState("");
  const history = useQuery({ queryKey: ["strategy-stage", strategy.config_id], queryFn: () => api.strategyStage(strategy.config_id) });
  const move = useMutation({
    mutationFn: () => api.moveStrategyStage(strategy.config_id, { to_stage: to, reason: reason.trim(), run_id: to === "LIVE" ? Number(runId) || null : null }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["strategies"] });
      toast.success(`${strategy.name} is now in ${STAGE_LABEL[to as keyof typeof STAGE_LABEL] ?? to}.`);
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (reason.trim()) move.mutate();
  };
  return (
    <Dialog
      open
      onClose={onClose}
      title={`Stage of ${strategy.name}`}
      description={`Now: ${STAGE_LABEL[strategy.stage]}. Paper trading is unvalidated research. Going live needs a backtest run that passed every check.`}
      footer={
        <>
          <button type="button" onClick={onClose} className={buttonClass("secondary")}>Close</button>
          <button type="submit" form="stage-form" disabled={!reason.trim() || !to || move.isPending} className={buttonClass("primary")}>Move</button>
        </>
      }
    >
      <form id="stage-form" onSubmit={submit} className="space-y-4">
        {move.isError ? <Alert tone="error" title="Not moved">{message(move.error)}</Alert> : null}
        <Field id="stage-to" label="Move to">
          <select id="stage-to" value={to} onChange={(e) => setTo(e.target.value)} className={inputFull}>
            {targets.map((s) => <option key={s} value={s}>{STAGE_LABEL[s]}</option>)}
          </select>
        </Field>
        {to === "LIVE" ? (
          <Field id="stage-run" label="Backtest run that justifies it" hint="The run number from the Backtests page. It must be of this strategy, with these settings, and pass every check.">
            <input id="stage-run" inputMode="numeric" value={runId} onChange={(e) => setRunId(e.target.value)} className={inputFull} />
          </Field>
        ) : null}
        <Field id="stage-reason" label="Reason" hint="Kept with who approved it and when. It cannot be edited later.">
          <input id="stage-reason" required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} className={inputFull} />
        </Field>
      </form>
      <div className="mt-5">
        <h3 className="mb-1 text-sm font-medium">History</h3>
        {history.data && history.data.history.length === 0 ? <p className="text-sm text-ink-soft">No moves yet: it has only been research.</p> : null}
        <ul className="space-y-2 text-sm">
          {history.data?.history.map((h) => (
            <li key={h.change_id}>
              <span className="font-medium">{h.from_stage.toLowerCase()} to {h.to_stage.toLowerCase()}</span>
              <span className="text-ink-soft"> · {h.approver} · {fmtDateTime(h.at)}{h.run_id ? ` · run #${h.run_id}` : ""} · {h.reason}</span>
              {h.waived.map((w) => <span key={w} className="block text-xs text-amber-700">{w}</span>)}
            </li>
          ))}
        </ul>
      </div>
    </Dialog>
  );
}
