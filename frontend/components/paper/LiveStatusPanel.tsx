"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";

const SILENT_AFTER_S = 120;

/** Whether live trading can run right now and, when it cannot, every reason. The same gate the live process refuses to start without. */
export function LiveStatusPanel() {
  const q = useQuery({ queryKey: ["paper", "live-status"], queryFn: api.paperLiveStatus, refetchInterval: 30_000 });
  if (q.isError) return <Alert tone="error" title="Could not check live trading">Try again in a moment.</Alert>;
  if (q.isLoading || !q.data) return <div role="status" aria-label="Checking live trading"><Skeleton className="h-24 w-full" /></div>;
  const d = q.data;
  const p = d.process;
  const alive = p !== null && p.state === "RUNNING" && (p.silent_s ?? Infinity) <= SILENT_AFTER_S;
  return (
    <Panel title="Live trading status">
      <div className="space-y-3 px-6 py-5 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <StatusPill tone={d.open ? "good" : "warn"}>{d.open ? "Live can run" : "Live cannot run yet"}</StatusPill>
          <StatusPill tone={alive ? "good" : "bad"}>{alive ? "Live process running" : p === null ? "Live process has not reported" : `Live process ${p.state.toLowerCase()}, last heard ${p.silent_s ?? "?"} s ago`}</StatusPill>
        </div>
        {d.problems.length > 0 ? (
          <ul className="list-disc space-y-1 pl-5 text-ink-soft">
            {d.problems.map((x) => <li key={x}>{x}</li>)}
          </ul>
        ) : null}
        <p className="text-xs text-ink-soft">An order you approve waits until the live process sends it, and fails if it expires first. Nothing is sent while the gate is closed.</p>
      </div>
    </Panel>
  );
}
