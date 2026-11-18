"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { LiveQuote } from "@/lib/schemas";

export const money = (n: number) => n.toLocaleString("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });

/** The latest price of every stock in a list, in one request, refreshed every few seconds while the page is open. A stock with no price is simply absent. */
export function useLiveQuotes(ids: number[]): Record<string, LiveQuote> {
  const key = [...new Set(ids)].sort((a, b) => a - b);
  const q = useQuery({ queryKey: ["live", "quotes", key.join(",")], queryFn: () => api.liveQuotes(key), enabled: key.length > 0, refetchInterval: 5_000, staleTime: 2_000, retry: false, placeholderData: (prev) => prev });
  return q.data?.quotes ?? {};
}

/** A coloured percentage with its sign; nothing shown without a figure. */
export function Pct({ v, digits = 2 }: { v: number | null | undefined; digits?: number }) {
  if (v === null || v === undefined || Number.isNaN(v)) return <span className="text-ink-faint">–</span>;
  return <span className={v > 0 ? "text-emerald-700" : v < 0 ? "text-red-700" : ""}>{v > 0 ? "+" : ""}{v.toFixed(digits)}%</span>;
}

/** Price and day change of one stock as inline text, for a DataTable cell. A price from the last close (the feed is off, or the stock is not followed) is marked as such. */
export function PriceText({ quote }: { quote: LiveQuote | undefined }) {
  if (!quote) return <span className="text-ink-faint">–</span>;
  const title = quote.source === "live" ? `Live price, as of ${quote.as_of}` : `Last close (no live price), ${quote.as_of.slice(0, 10)}`;
  return (
    <span className="whitespace-nowrap tabular-nums" title={title}>
      {money(Number(quote.ltp))}
      <span className="ml-1.5 text-xs"><Pct v={quote.change_pct} /></span>
      {quote.source === "close" ? <span className="ml-1 text-[10px] text-ink-faint">close</span> : null}
    </span>
  );
}

/** The same for a plain table row. */
export function PriceCell({ quote }: { quote: LiveQuote | undefined }) {
  return <td className="px-2 text-right"><PriceText quote={quote} /></td>;
}
