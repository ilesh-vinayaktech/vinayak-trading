"use client";

import { OrderContext } from "@/components/paper/OrderContext";
import { UpcomingNote } from "@/components/paper/UpcomingNote";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Alert } from "@/components/ui/Alert";
import { Panel, RelativeTime, StatusPill } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { useToast } from "@/components/ui/Toast";
import { ApiError, api } from "@/lib/api/client";
import { fmtMoney } from "@/lib/formatting";
import type { PaperOrder } from "@/lib/schemas";
import { PriceText, useLiveQuotes } from "@/components/market/LivePrice";
import { RISE_HEADER, RiseText, useRiseOdds } from "@/components/market/RiseCell";
import { HOLD_HEADER, HoldText, useHoldSignal } from "@/components/market/HoldCell";
import { NoteChips, useNotes } from "@/components/market/NoteChips";
import { useVenue } from "@/lib/venue";

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
  const mode = useVenue();
  const q = useQuery({ queryKey: ["paper", mode, "orders"], queryFn: () => api.paperOrders(undefined, mode), refetchInterval: 30_000 });
  const done = () => void qc.invalidateQueries({ queryKey: ["paper"] });
  const approve = useMutation({ mutationFn: ({ id, how }: { id: string; how?: { order_type: "MARKET" | "LIMIT"; limit_price?: string } }) => api.approvePaperOrder(id, how, mode), onSuccess: (_r, v) => { toast.success(mode === "live" ? "Approved. The live process sends it to your broker while live trading is allowed." : v.how?.order_type === "LIMIT" ? `Approved. It fills only at the limit (₹${v.how.limit_price}, rounded to the price step) or better.` : "Approved. It fills at the next live price."); done(); } });
  const reject = useMutation({ mutationFn: (id: string) => api.rejectPaperOrder(id, mode), onSuccess: () => { toast.success("Rejected."); done(); } });
  const all = q.data?.orders ?? [];
  const pending = all.filter((o) => o.status === "PENDING");
  const history = all.filter((o) => o.status !== "PENDING");
  const quotes = useLiveQuotes(pending.map((o) => o.instrument_id));
  const rise = useRiseOdds(pending.map((o) => o.instrument_id));
  const hold = useHoldSignal(pending.map((o) => o.instrument_id));
  const notes = useNotes(pending.map((o) => o.instrument_id));
  const [how, setHow] = useState<Record<string, { type: "MARKET" | "LIMIT"; price: string }>>({}); // the owner's choice per order, made when approving
  const busy = approve.isPending || reject.isPending;
  const error = approve.error ?? reject.error;

  const pendingColumns: Column<PaperOrder>[] = [
    { key: "symbol", header: "Stock", cell: (o) => <div><span className="inline-flex items-center gap-2"><span className="font-medium">{o.symbol}</span><span className="sm:hidden"><SidePill side={o.side} /></span></span><OrderContext symbol={o.symbol} side={o.side} /><UpcomingNote items={o.upcoming} /></div> },
    { key: "side", header: "Action", hideBelow: "sm", cell: (o) => <SidePill side={o.side} /> },
    { key: "qty", header: "Shares", className: "text-right", cell: (o) => fmtMoney(o.qty, 0) },
    { key: "value", header: "About", className: "text-right", hideBelow: "sm", cell: (o) => `₹${fmtMoney(o.ref_price)} each` },
    { key: "live", header: "Live price", className: "text-right", cell: (o) => <PriceText quote={quotes[String(o.instrument_id)]} /> },
    { key: "rise", header: RISE_HEADER, className: "text-right", hideBelow: "md", cell: (o) => <RiseText odds={rise[String(o.instrument_id)]} /> },
    { key: "hold", header: HOLD_HEADER, className: "text-right", hideBelow: "md", cell: (o) => <HoldText signal={hold[String(o.instrument_id)]} /> },
    { key: "notes", header: "Notes", hideBelow: "md", cell: (o) => <NoteChips notes={notes[String(o.instrument_id)]} /> },
    { key: "reason", header: "Why", hideBelow: "md", cell: (o) => <span className="text-ink-soft">{o.reason}</span> },
    { key: "expires", header: "Answer by", hideBelow: "sm", cell: (o) => <span className="text-ink-soft"><RelativeTime iso={o.expires_at} /></span> },
    {
      key: "act",
      header: "",
      className: "text-right",
      cell: (o) => (
        <span className="inline-flex gap-2">
          <span className="inline-flex items-center gap-1">
            <select aria-label={`Order type for ${o.symbol}`} value={how[o.order_id]?.type ?? "MARKET"} onChange={(e) => setHow((h) => ({ ...h, [o.order_id]: { type: e.target.value as "MARKET" | "LIMIT", price: h[o.order_id]?.price ?? o.ref_price } }))} className="rounded border border-line px-1 py-1 text-sm">
              <option value="MARKET">Market</option>
              <option value="LIMIT">Limit</option>
            </select>
            {how[o.order_id]?.type === "LIMIT" ? <input aria-label={`Limit price for ${o.symbol}`} title={o.tick_size ? `Price step ₹${o.tick_size}: the limit is rounded to the nearest step` : "The limit is rounded to the nearest price step"} placeholder={o.tick_size ? `step ${o.tick_size}` : undefined} inputMode="decimal" value={how[o.order_id]?.price ?? ""} onChange={(e) => setHow((h) => ({ ...h, [o.order_id]: { type: "LIMIT", price: e.target.value } }))} className="w-24 rounded border border-line px-2 py-1 text-right text-sm" /> : null}
          </span>
          <button type="button" disabled={busy || (how[o.order_id]?.type === "LIMIT" && !(Number(how[o.order_id]?.price) > 0))} onClick={() => approve.mutate({ id: o.order_id, how: how[o.order_id]?.type === "LIMIT" ? { order_type: "LIMIT", limit_price: how[o.order_id]?.price } : undefined })} className={buttonClass("primary", true)} aria-label={`Approve ${o.side} ${o.symbol}`}>Approve</button>
          <button type="button" disabled={busy} onClick={() => reject.mutate(o.order_id)} className={buttonClass("secondary", true)} aria-label={`Reject ${o.side} ${o.symbol}`}>Reject</button>
        </span>
      ),
    },
  ];
  const historyColumns: Column<PaperOrder>[] = [
    { key: "when", header: "Proposed", cell: (o) => <span className="whitespace-nowrap text-ink-soft"><RelativeTime iso={o.created_at} /></span> },
    { key: "symbol", header: "Stock", cell: (o) => <div><span className="font-medium">{o.symbol}</span><UpcomingNote items={o.upcoming} /></div> },
    { key: "side", header: "Action", cell: (o) => <SidePill side={o.side} /> },
    { key: "qty", header: "Shares", className: "text-right", cell: (o) => fmtMoney(o.qty, 0) },
    { key: "type", header: "Type", hideBelow: "md", cell: (o) => (o.order_type === "LIMIT" ? `Limit ₹${fmtMoney(o.limit_price ?? "0")}` : "Market") },
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
        actions={pending.length > 1 ? <button type="button" disabled={busy} onClick={() => pending.forEach((o) => approve.mutate({ id: o.order_id }))} className={buttonClass("secondary", true)}>Approve all {pending.length} at market</button> : null}
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
