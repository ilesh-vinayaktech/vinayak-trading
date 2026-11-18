"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert } from "@/components/ui/Alert";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";

const mood = (v: number) => (v >= 0.15 ? "Positive" : v <= -0.15 ? "Negative" : "Mixed");
const READING = { positive: { label: "Positive", tone: "good" }, negative: { label: "Negative", tone: "bad" }, mixed: { label: "Mixed", tone: "neutral" } } as const;
const tone = (v: number | null) => (v === null ? "neutral" : v >= 0.15 ? "good" : v <= -0.15 ? "bad" : "neutral");
const ago = (iso: string) => {
  const h = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 3_600_000));
  return h < 1 ? "just now" : h < 24 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
};

/** What the market headlines say: the mood by day, the stocks named most, and the latest headlines. Each headline is read by the Laya model (a keyword list until it is scored); a gauge, not a forecast. */
export function NewsPanel() {
  const q = useQuery({ queryKey: ["market", "news"], queryFn: api.marketNews, refetchInterval: 15 * 60_000 });
  if (q.isError) return <Alert tone="error" title="Could not load the news">Try again in a moment.</Alert>;
  if (q.isLoading || !q.data) return <div role="status" aria-label="Loading the news"><Skeleton className="h-32 w-full" /></div>;
  const d = q.data;
  if (d.items.length === 0) return <Alert tone="info" title="No news yet">The news job has not run.</Alert>;
  const today = d.mood.at(-1);
  return (
    <Panel title="News mood">
      <div className="flex flex-wrap items-center gap-3 px-3 pt-2 text-sm">
        {today ? <><StatusPill tone={tone(today.avg)}>{mood(today.avg)}</StatusPill><span className="text-ink-soft">{today.positive} positive and {today.negative} negative of {today.n} scored headlines on {today.day}</span></> : <span className="text-ink-soft">No scored headlines in the last week.</span>}
      </div>
      {d.mood.length > 1 && (
        <div className="flex items-end gap-1 px-3 pt-3" role="img" aria-label="Average headline mood by day">
          {d.mood.map((m) => (
            <div key={m.day} className="flex flex-1 flex-col items-center text-[10px] text-ink-faint" title={`${m.day}: ${m.avg.toFixed(2)} from ${m.n} headlines`}>
              <div className="flex h-12 w-full flex-col justify-center"><div className={m.avg >= 0 ? "self-center bg-emerald-500" : "self-center bg-red-500"} style={{ height: `${Math.max(2, Math.abs(m.avg) * 48)}px`, width: "70%", transform: `translateY(${m.avg >= 0 ? "-" : ""}${Math.abs(m.avg) * 24}px)` }} /></div>
              {m.day.slice(5)}
            </div>
          ))}
        </div>
      )}
      {d.stocks.length > 0 && (
        <p className="px-3 pt-3 text-xs text-ink-soft">Named most in the last 3 days: {d.stocks.map((s) => `${s.symbol} (${s.mentions}, ${mood(s.avg).toLowerCase()})`).join(", ")}.</p>
      )}
      <ul className="divide-y divide-line px-3 pb-1 pt-2 text-sm">
        {d.items.slice(0, 10).map((i) => (
          <li key={i.url} className="flex items-start justify-between gap-3 py-1.5">
            <span><a href={i.url} target="_blank" rel="noopener noreferrer" className="hover:underline">{i.title}</a><span className="block text-xs text-ink-faint">{i.source}, {ago(i.published_at)}{i.symbols.length > 0 ? `, ${i.symbols.join(" ")}` : ""}</span></span>
            {i.reading !== null && <span title={i.reading_model === "laya" ? `Read by the Laya model${i.laya_confidence !== null ? `, ${Math.round(i.laya_confidence * 100)}% sure` : ""}` : "Read by the keyword list (not yet scored by the model)"}><StatusPill tone={READING[i.reading].tone}>{READING[i.reading].label}</StatusPill></span>}
          </li>
        ))}
      </ul>
      <p className="border-t border-line px-3 py-2 text-xs text-ink-faint">Headlines from public RSS feeds, read by the Laya model running on this machine (a keyword list for any it has not scored yet). On 38 headlines labelled by hand it agreed with the label 82% of the time, against 74% for the keyword list: better, not proven. It has not been tested against what prices did next.</p>
    </Panel>
  );
}
