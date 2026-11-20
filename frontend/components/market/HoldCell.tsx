"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { HoldSignalLatest } from "@/lib/schemas";

type Item = HoldSignalLatest["items"][string];

/** The newest hold signal of every stock in a list, in one request (it changes once a night, so it is kept for ten minutes). A stock outside the scored universe is simply absent. */
export function useHoldSignal(ids: number[]): Record<string, Item> {
  const key = [...new Set(ids)].sort((a, b) => a - b).slice(0, 300);
  const q = useQuery({ queryKey: ["market", "hold-latest", key.join(",")], queryFn: () => api.marketHoldLatest(key), enabled: key.length > 0, staleTime: 10 * 60_000, retry: false, placeholderData: (previous) => previous });
  return q.data?.items ?? {};
}

export const HOLD_HEADER = "Hold signal";
export const HOLD_HELP =
  "A frozen rule, scored each night: every stock is ranked 0 to 100 by a model's chance of beating the median stock over the next 5 sessions. BUY: not held and rank 90 or more (buy at the next open). HOLD: held, rank still above 20. SELL: held and rank 20 or lower (sell at the next open). A dash is neither. Long only; a lean from past prices, not advice or an order.";

const TONE: Record<Item["action"], string> = { BUY: "font-semibold text-emerald-700", SELL: "font-semibold text-red-700", HOLD: "text-ink", NONE: "text-ink-faint" };

/** The call as plain text with the rank beside it. A stock the rule is not holding but that ranks 20 or lower reads "weak": the rule would sell it if it held it. */
export function HoldText({ signal }: { signal: Item | undefined }) {
  if (!signal) return <span className="text-ink-faint" title="Not scored: outside the stocks the rule ranks (liquid stocks listed by the end of 2024)">–</span>;
  const weak = signal.action === "NONE" && signal.rank_pct <= 20;
  const label = signal.action === "NONE" ? (weak ? "weak" : "–") : signal.action;
  const tone = weak ? "text-red-700" : TONE[signal.action];
  const title = `${signal.day}: rank ${Math.round(signal.rank_pct)} of 100 (chance of beating the median stock ${(signal.prob * 100).toFixed(1)}%). ${
    signal.action === "BUY" ? "Buy at the next open." : signal.action === "SELL" ? "Sell at the next open." : signal.action === "HOLD" ? `Held since ${signal.entry_day ?? "an earlier day"}.` : weak ? "Not held by the rule; at this rank it would sell." : "Not held; a buy needs rank 90 or more."
  }`;
  return (
    <span className={`whitespace-nowrap tabular-nums ${tone}`} title={title}>
      {label}
      <span className="ml-1 text-[10px] font-normal text-ink-faint">r{Math.round(signal.rank_pct)}</span>
    </span>
  );
}

/** The same for a plain table row. */
export function HoldCell({ signal }: { signal: Item | undefined }) {
  return <td className="px-2 text-right"><HoldText signal={signal} /></td>;
}
