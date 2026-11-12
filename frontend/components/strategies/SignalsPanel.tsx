"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Field } from "@/components/ui/Field";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { buttonClass, inputFull } from "@/components/ui/styles";
import { ApiError, api } from "@/lib/api/client";
import { fmtMoney } from "@/lib/formatting";
import type { Instrument, SignalDay } from "@/lib/schemas";

const REASON: Record<string, string> = { below_trend: "Fell below its trend average", rsi_above_exit: "Recovered (RSI above the sell level)" };
const why = (r: SignalDay) => (r.reason ? (REASON[r.reason] ?? r.reason) : "");
const num = (s: string | null) => (s === null ? "-" : fmtMoney(s));

export type Mark = { day: string; action: "BUY" | "SELL" };
type Run = { id: string; start: string; end: string; holding: boolean };

const columns: Column<SignalDay>[] = [
  { key: "day", header: "Decided after close of", cell: (r) => <span className="whitespace-nowrap font-medium">{r.day}</span> },
  { key: "action", header: "Signal", cell: (r) => <StatusPill tone={r.action === "BUY" ? "good" : "warn"}>{r.action}</StatusPill> },
  { key: "why", header: "Why", hideBelow: "sm", cell: (r) => <span className="text-ink-soft">{why(r)}</span> },
  { key: "close", header: "Close", className: "text-right", cell: (r) => num(r.close) },
  { key: "rsi", header: "RSI", className: "text-right", hideBelow: "md", cell: (r) => num(r.rsi) },
  { key: "sma", header: "Trend average", className: "text-right", hideBelow: "md", cell: (r) => num(r.sma) },
  { key: "fill", header: "Next open", className: "text-right", cell: (r) => (r.fill_day ? `${num(r.fill_price)} on ${r.fill_day}` : <span className="text-ink-soft">not yet</span>) },
];

/** Run a saved strategy on the open stock: see where it would have said buy or sell, from any starting day. Decisions only. */
export function SignalsPanel({ instrument, start, end, onMarks }: { instrument: Instrument | null; start: string; end: string; onMarks: (m: Mark[]) => void }) {
  const list = useQuery({ queryKey: ["strategies"], queryFn: api.strategies });
  const saved = list.data?.strategies ?? [];
  const [pick, setPick] = useState("");
  const [from, setFrom] = useState<string | null>(null);
  const [to, setTo] = useState<string | null>(null);
  const [holding, setHolding] = useState(false);
  const [run, setRun] = useState<Run | null>(null);
  const id = instrument?.id ?? null;
  const chosen = pick || saved[0]?.config_id || "";
  useEffect(() => {
    setRun(null); // a new stock, a new question
    setFrom(null);
    setTo(null);
  }, [id]);
  const startAt = from ?? start;
  const endAt = to ?? end;
  const result = useQuery({
    queryKey: ["signals", run?.id, id, run?.start, run?.end, run?.holding],
    queryFn: () => api.strategySignals(run?.id as string, { instrument_id: id as number, start: run?.start as string, end: run?.end as string, holding: run?.holding as boolean }),
    enabled: run !== null && id !== null,
  });
  const decisions = (result.data?.days ?? []).filter((d) => d.action !== null);
  useEffect(() => {
    onMarks(run === null || !result.data ? [] : decisions.map((d) => ({ day: d.day, action: d.action as "BUY" | "SELL" })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result.data, run]);
  const blocked = id === null || chosen === "" || !startAt || !endAt || startAt > endAt;
  const failure = result.error instanceof ApiError ? result.error.message : result.isError ? "Could not run the strategy. Try again." : null;
  const pending = result.data?.days.filter((d) => !d.ready).length ?? 0;
  return (
    <Panel title="Strategy signals">
      <div className="space-y-4 px-5 py-5">
        {saved.length === 0 && !list.isLoading ? (
          <p className="text-sm text-ink-soft">You have no saved strategies yet. Create one on the Strategies page, then run it here.</p>
        ) : (
          <form
            className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5 lg:items-end"
            onSubmit={(e) => {
              e.preventDefault();
              if (!blocked) setRun({ id: chosen, start: startAt, end: endAt, holding });
            }}
          >
            <Field id="sig-strategy" label="Strategy">
              <select id="sig-strategy" value={chosen} onChange={(e) => setPick(e.target.value)} className={inputFull}>
                {saved.map((s) => (
                  <option key={s.config_id} value={s.config_id}>{s.name}</option>
                ))}
              </select>
            </Field>
            <Field id="sig-from" label="Replay from" hint="Any starting day.">
              <input id="sig-from" type="date" value={startAt} onChange={(e) => setFrom(e.target.value)} className={inputFull} />
            </Field>
            <Field id="sig-to" label="To">
              <input id="sig-to" type="date" value={endAt} onChange={(e) => setTo(e.target.value)} className={inputFull} />
            </Field>
            <label className="flex items-center gap-2 pb-2 text-sm">
              <input type="checkbox" checked={holding} onChange={(e) => setHolding(e.target.checked)} />
              Already holding it on that day
            </label>
            <button type="submit" disabled={blocked || result.isFetching} className={buttonClass("primary")}>Run strategy</button>
          </form>
        )}
        {failure ? <Alert tone="error">{failure}</Alert> : null}
        {result.data ? (
          <>
            <p className="text-sm" role="status">
              <strong>{result.data.strategy}</strong>: {result.data.summary.buys} buy and {result.data.summary.sells} sell signals between {run?.start} and {run?.end}
              {pending > 0 ? `; ${pending} early days had too little history to decide` : ""}.
            </p>
            <DataTable
              caption="Strategy signals"
              columns={columns}
              rows={decisions}
              rowKey={(r) => r.day}
              empty={<EmptyState icon="scroll" title="No signals">This strategy would not have bought or sold this stock in that period.</EmptyState>}
            />
            <ul className="list-disc space-y-1 pl-5 text-xs text-ink-soft">
              {result.data.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </>
        ) : null}
      </div>
    </Panel>
  );
}
