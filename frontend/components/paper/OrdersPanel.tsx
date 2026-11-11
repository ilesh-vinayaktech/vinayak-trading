"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Alert } from "@/components/ui/Alert";
import { Panel, RelativeTime, StatusPill } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";
import { fmtMoney } from "@/lib/formatting";
import type { PaperOrder } from "@/lib/schemas";

const message = (e: unknown) => (e instanceof ApiError ? e.message : "Could not save. Try again.");
const TONE: Record<PaperOrder["status"], "good" | "warn" | "bad" | "neutral" | "info"> = { PENDING: "warn", APPROVED: "info", FILLED: "good", REJECTED: "neutral", EXPIRED: "neutral", FAILED: "bad" };
const LABEL: Record<PaperOrder["status"], string> = { PENDING: "Needs your answer", APPROVED: "Approved, waiting to fill", FILLED: "Filled", REJECTED: "Rejected", EXPIRED: "Expired", FAILED: "Failed" };

export function SidePill({ side }: { side: PaperOrder["side"] }) {
  return <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-semibold ${side === "BUY" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>{side}</span>;
}

/** The orders the strategy proposed. Each waits for its owner; nothing fills until it is approved, and nothing here is real. */
export function OrdersPanel({ only }: { only?: "pending" }) {
  const qc = useQueryClient();
  const toast = useToast();
  const q = useQuery({ queryKey: ["paper", "orders"], queryFn: () => api.paperOrders(), refetchInterval: 30_000 });
  const done = () => void qc.invalidateQueries({ queryKey: ["paper"] });
  const approve = useMutation({ mutationFn: (id: string) => api.approvePaperOrder(id), onSuccess: () => { toast.success("Approved. It fills at the next live price."); done(); } });
  const reject = useMutation({ mutationFn: (id: string) => api.rejectPaperOrder(id), onSuccess: () => { toast.success("Rejected."); done(); } });
  const all = q.data?.orders ?? [];
  const pending = all.filter((o) => o.status === "PENDING");
  const history = all.filter((o) => o.status !== "PENDING");
  const busy = approve.isPending || reject.isPending;
  const error = approve.error ?? reject.error;

  const pendingColumns: Column<PaperOrder>[] = [
    { key: "symbol", header: "Stock", cell: (o) => <span className="inline-flex items-center gap-2"><span className="font-medium">{o.symbol}</span><span className="sm:hidden"><SidePill side={o.side} /></span></span> },
    { key: "side", header: "Action", hideBelow: "sm", cell: (o) => <SidePill side={o.side} /> },
    { key: "qty", header: "Shares", className: "text-right", cell: (o) => fmtMoney(o.qty, 0) },
    { key: "value", header: "About", className: "text-right", hideBelow: "sm", cell: (o) => `₹${fmtMoney(o.ref_price)} each` },
    { key: "reason", header: "Why", hideBelow: "md", cell: (o) => <span className="text-ink-soft">{o.reason}</span> },
    { key: "expires", header: "Answer by", hideBelow: "sm", cell: (o) => <span className="text-ink-soft"><RelativeTime iso={o.expires_at} /></span> },
    {
      key: "act",
      header: "",
      className: "text-right",
      cell: (o) => (
        <span className="inline-flex gap-2">
          <button type="button" disabled={busy} onClick={() => approve.mutate(o.order_id)} className={buttonClass("primary", true)} aria-label={`Approve ${o.side} ${o.symbol}`}>Approve</button>
          <button type="button" disabled={busy} onClick={() => reject.mutate(o.order_id)} className={buttonClass("secondary", true)} aria-label={`Reject ${o.side} ${o.symbol}`}>Reject</button>
        </span>
      ),
    },
  ];
  const historyColumns: Column<PaperOrder>[] = [
    { key: "when", header: "Proposed", cell: (o) => <span className="whitespace-nowrap text-ink-soft"><RelativeTime iso={o.created_at} /></span> },
    { key: "symbol", header: "Stock", cell: (o) => <span className="font-medium">{o.symbol}</span> },
    { key: "side", header: "Action", cell: (o) => <SidePill side={o.side} /> },
    { key: "qty", header: "Shares", className: "text-right", cell: (o) => fmtMoney(o.qty, 0) },
    { key: "fill", header: "Filled at", className: "text-right", hideBelow: "sm", cell: (o) => (o.fill_price ? `₹${fmtMoney(o.fill_price)}` : <span className="text-ink-faint">-</span>) },
    { key: "status", header: "Status", cell: (o) => <span title={o.failure ?? undefined}><StatusPill tone={TONE[o.status]}>{LABEL[o.status]}</StatusPill></span> },
    { key: "note", header: "Note", hideBelow: "md", cell: (o) => <span className="text-ink-soft">{o.failure ?? o.reason}</span> },
  ];

  return (
    <div className="space-y-6">
      {q.isError ? <Alert tone="error" title="Could not load the orders">Try again in a moment.</Alert> : null}
      {error ? <Alert tone="error">{message(error)}</Alert> : null}
      <Panel
        title="Waiting for your answer"
        actions={pending.length > 1 ? <button type="button" disabled={busy} onClick={() => pending.forEach((o) => approve.mutate(o.order_id))} className={buttonClass("secondary", true)}>Approve all {pending.length}</button> : null}
      >
        <DataTable caption="Orders waiting for your answer" columns={pendingColumns} rows={q.data ? pending : undefined} rowKey={(o) => o.order_id} loading={q.isLoading} empty={<EmptyState icon="tasks" title="Nothing to approve">The strategy decides once a day after the market closes. New proposals appear here.</EmptyState>} />
      </Panel>
      {only === "pending" ? null : (
        <Panel title="Order history">
          <DataTable caption="Order history" columns={historyColumns} rows={q.data ? history : undefined} rowKey={(o) => o.order_id} loading={q.isLoading} empty={<EmptyState icon="scroll" title="No orders yet">Approved, rejected and filled orders are listed here.</EmptyState>} />
        </Panel>
      )}
    </div>
  );
}
