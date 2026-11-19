"use client";

import { useQuery } from "@tanstack/react-query";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";
import type { StockScore } from "@/lib/schemas";

const PARTS = [
  { key: "trend", label: "Trend", weight: 35, hint: "1 and 3-month change, price against its 50-day average, nearness to the 52-week high, ADX" },
  { key: "participation", label: "Volume and delivery", weight: 20, hint: "Volume and delivery % against their norms" },
  { key: "smart_money", label: "Smart money", weight: 30, hint: "Bulk and block deals, insider buying, change in FII, DII and promoter holding" },
  { key: "quality", label: "Quality", weight: 15, hint: "ROE, ROCE, profit growth, low debt" },
] as const;
const colour = (n: number) => (n >= 60 ? "bg-emerald-500" : n >= 40 ? "bg-slate-400" : "bg-red-500");
const verdict = (n: number) => (n >= 60 ? { word: "Strong", cls: "text-emerald-700" } : n >= 40 ? { word: "Neutral", cls: "text-ink-soft" } : { word: "Weak", cls: "text-red-700" });
const sign = (n: number) => `${n > 0 ? "+" : ""}${Math.round(n)}`;

/** The score against its reading about a week ago and about a month ago (the nearest reading at or before that day). */
function changes(points: StockScore["history"]) {
  const last = points[points.length - 1];
  if (!last) return [];
  const t = Date.parse(last.day);
  return [["1 week", 7], ["1 month", 30]].flatMap(([label, days]) => {
    const old = [...points].reverse().find((p) => Date.parse(p.day) <= t - Number(days) * 86_400_000);
    return old ? [{ label: String(label), d: last.score - old.score }] : [];
  });
}

/** One stock's swing score: the number, its four parts, why, and how it has moved. Nothing is shown for a stock that is not a listed share. */
export function ScorePanel({ symbol }: { symbol: string }) {
  const q = useQuery({ queryKey: ["market", "score", symbol], queryFn: () => api.marketScore(symbol), retry: false });
  if (q.isLoading) return <div role="status" aria-label="Loading the score"><Skeleton className="h-24 w-full" /></div>;
  if (q.isError) return null; // not a listed share (404) or not available: show nothing rather than an error on a page about something else
  const d = q.data;
  if (!d) return null;
  return (
    <Panel title="Swing score">
      {!d.scored || d.score === null ? (
        <p className="p-3 text-sm text-ink-soft">{d.symbol} has no score today: it trades under ₹5 crore a day, or too little is known about it. A thinly traded stock is left unscored rather than ranked.</p>
      ) : (
        <div className="grid gap-4 p-3 md:grid-cols-[11rem_1fr]">
          <div>
            <div className="text-4xl font-semibold tabular-nums" aria-label={`Score ${Math.round(d.score)} out of 100`}>{Math.round(d.score)}<span className="text-base font-normal text-ink-soft"> / 100</span></div>
            <p className={`text-sm font-semibold ${verdict(d.score).cls}`}>{verdict(d.score).word}</p>
            {d.setup ? <p className="mt-1 text-sm font-medium">{d.setup}</p> : null}
            <ul className="mt-2 space-y-0.5 text-xs">
              {changes(d.history).map((c) => <li key={c.label} className="text-ink-soft">vs {c.label} ago <span className={`font-medium tabular-nums ${c.d > 0 ? "text-emerald-700" : c.d < 0 ? "text-red-700" : ""}`}>{sign(c.d)}</span></li>)}
            </ul>
            <p className="mt-2 text-xs text-ink-faint">as of {d.as_of}</p>
          </div>
          <div className="space-y-3">
            {d.why ? (
              <div>
                <h3 className="text-xs font-semibold text-ink-soft">What is driving it</h3>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-sm">{d.why.split("; ").map((w) => <li key={w}>{w}</li>)}</ul>
              </div>
            ) : null}
            <ul className="space-y-2.5">
              {PARTS.map((p) => {
                const v = d.components[p.key];
                return (
                  <li key={p.key}>
                    <div className="flex justify-between text-xs"><span>{p.label} <span className="text-ink-faint">({p.weight}%)</span></span><span className="tabular-nums">{v === null ? "no data" : <>{Math.round(v)} <span className={verdict(v).cls}>{verdict(v).word}</span></>}</span></div>
                    <div className="relative mt-0.5 h-1.5 rounded-full bg-slate-100" aria-hidden>
                      {v !== null ? <div className={`h-1.5 rounded-full ${colour(v)}`} style={{ width: `${v}%` }} /> : null}
                      <div className="absolute -top-0.5 left-1/2 h-2.5 w-px bg-slate-400" />
                    </div>
                    <p className="mt-0.5 text-xs text-ink-faint">{p.hint}</p>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      )}
      <p className="border-t border-line px-3 py-2 text-xs text-ink-faint">Each part ranks this stock against every liquid stock; 50 is the middle. A part with no data is left out and the others are re-weighted, never counted as zero. On past data the score had a modest edge (top fifth ahead of the bottom fifth by about 1% over four weeks), mostly from volume and delivery; smart money has not yet earned its weight.</p>
    </Panel>
  );
}
