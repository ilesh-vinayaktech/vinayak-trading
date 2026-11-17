"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";

const LOW = 40; // a score under this is in the bottom part of the liquid stocks
const HIGH = 70;

/** What the swing score and the support/resistance map say about the stock of an order, beside it. Facts only: it never blocks or changes the order. Shows nothing while loading or for a stock that has neither. */
export function OrderContext({ symbol, side }: { symbol: string; side: "BUY" | "SELL" }) {
  const score = useQuery({ queryKey: ["market", "score", symbol], queryFn: () => api.marketScore(symbol), retry: false, staleTime: 10 * 60_000 });
  const levels = useQuery({ queryKey: ["market", "levels", symbol], queryFn: () => api.marketLevels(symbol), retry: false, staleTime: 10 * 60_000 });
  const s = score.data?.scored ? score.data : null;
  const l = levels.data?.enough_history ? levels.data : null;
  if (!s && !l) return null;
  const caution =
    s && s.score !== null && ((side === "BUY" && s.score < LOW) || (side === "SELL" && s.score > HIGH))
      ? `The score is ${side === "BUY" ? "low" : "high"} for a ${side === "BUY" ? "buy" : "sale"}.`
      : l && side === "BUY" && l.status?.state.startsWith("Breakdown")
        ? "It has just broken below support."
        : null;
  return (
    <ul className="mt-1 space-y-0.5 text-xs font-normal text-ink-soft" aria-label={`Context for ${symbol}`}>
      {s && s.score !== null ? <li>Score {Math.round(s.score)}/100{s.setup ? `, ${s.setup}` : ""}</li> : null}
      {l?.status ? (
        <li>
          {l.status.state}
          {l.supports?.[0] ? `, support ${l.supports[0].price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : ""}
          {l.resistances?.[0] ? `, resistance ${l.resistances[0].price.toLocaleString("en-IN", { maximumFractionDigits: 2 })}` : ""}
        </li>
      ) : null}
      {caution ? <li className="font-medium text-amber-700">{caution}</li> : null}
    </ul>
  );
}
