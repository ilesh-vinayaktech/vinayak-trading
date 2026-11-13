"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api, type StrategyBody } from "@/lib/api/client";

const SLOTS = [5, 10, 20];
const CLASSES = [
  { key: "large", label: "Large caps" },
  { key: "mid", label: "Mid caps" },
  { key: "small", label: "Small caps" },
  { key: "micro", label: "Micro caps" },
];
type Screen = NonNullable<StrategyBody["screen"]>;

/** Save the screen on the Screener page as a strategy: each month it holds the best few stocks the screen finds. */
export function SaveScreenDialog({ screen, onClose }: { screen: Omit<Screen, "segments">; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const router = useRouter();
  const [name, setName] = useState("");
  const [slots, setSlots] = useState(10);
  const [segments, setSegments] = useState<string[]>(["large", "mid"]);
  const [saved, setSaved] = useState(false);
  const save = useMutation({
    mutationFn: () => api.createStrategy({ name: name.trim(), universe: "segments", max_instruments: null, timeframe: "1D", params: { max_positions: slots }, screen: { ...screen, segments } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["strategies"] });
      toast.success("Strategy saved. Choose it on the Data Explorer to see its buys and sells.");
      setSaved(true);
    },
  });
  const done = () => {
    onClose();
    router.push("/strategies");
  };
  // the New study page opens with this screen, these caps and this many stocks already chosen
  const backtest = () => router.push(`/research/studies/new?${new URLSearchParams({ screen: JSON.stringify(screen), segments: segments.join(","), slots: String(slots) })}`);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim() && segments.length > 0) save.mutate();
  };
  const toggle = (k: string) => setSegments((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]));
  return (
    <Dialog
      open
      onClose={saved ? done : onClose}
      title={saved ? "Strategy saved" : "Save screen as a strategy"}
      description="After every session the strategy runs this screen over the chosen stocks: a stock that matches is proposed for buying (up to the number below, best first), and a stock it holds is proposed for selling the day it stops matching. You approve each order."
      footer={
        saved ? (
          <>
            <button type="button" onClick={done} className={buttonClass("secondary")}>Go to strategies</button>
            <button type="button" onClick={backtest} className={buttonClass("primary")}>Backtest it</button>
          </>
        ) : (
          <>
            <button type="button" onClick={onClose} className={buttonClass("secondary")}>Cancel</button>
            <button type="submit" form="save-screen-form" disabled={!name.trim() || segments.length === 0 || save.isPending} className={buttonClass("primary")}>Save strategy</button>
          </>
        )
      }
    >
      {saved ? (
        <p className="text-sm">{name.trim()} is saved. Backtest it now to see how it would have done: the study opens with this screen, these caps and {slots} stocks already chosen.</p>
      ) : (
      <form id="save-screen-form" onSubmit={submit} className="space-y-4">
        {save.isError ? <Alert tone="error">{save.error instanceof ApiError ? save.error.message : "Could not save. Try again."}</Alert> : null}
        <Field id="screen-name" label="Name" hint="Up to 60 characters. It must differ from your other strategies.">
          <input id="screen-name" required maxLength={60} value={name} onChange={(e) => setName(e.target.value)} className={inputFull} />
        </Field>
        <Field id="screen-slots" label="Stocks held" hint="The best this many matches are held, equal weight.">
          <select id="screen-slots" value={slots} onChange={(e) => setSlots(Number(e.target.value))} className={inputFull}>
            {SLOTS.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </Field>
        <fieldset>
          <legend className="text-sm font-medium">Choose from</legend>
          <div className="mt-2 flex flex-wrap gap-4">
            {CLASSES.map((c) => (
              <label key={c.key} className="flex items-center gap-1.5 text-sm">
                <input type="checkbox" checked={segments.includes(c.key)} onChange={() => toggle(c.key)} />
                {c.label}
              </label>
            ))}
          </div>
        </fieldset>
      </form>
      )}
    </Dialog>
  );
}
