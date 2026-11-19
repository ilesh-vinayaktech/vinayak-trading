"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { NoteList, useNotes } from "@/components/market/NoteChips";
import { Dialog } from "@/components/ui/Dialog";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";

const READING = { positive: { label: "Positive", tone: "good" }, negative: { label: "Negative", tone: "bad" }, mixed: { label: "Mixed", tone: "neutral" } } as const;
const ago = (iso: string) => {
  const h = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 3_600_000));
  return h < 1 ? "just now" : h < 24 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
};

const TOP = 3;
type NewsItem = NonNullable<ReturnType<typeof useNews>["data"]>["items"][number];
const useNews = (symbol: string) => useQuery({ queryKey: ["market", "news", "for", symbol], queryFn: () => api.marketNewsFor(symbol), staleTime: 5 * 60_000, retry: false });

function Headlines({ items }: { items: NewsItem[] }) {
  return (
    <ul className="divide-y divide-line px-3 pb-1 pt-1 text-sm">
      {items.map((i) => (
        <li key={i.url} className="flex items-start justify-between gap-3 py-1.5">
          <span><a href={i.url} target="_blank" rel="noopener noreferrer" className="hover:underline">{i.title}</a><span className="block text-xs text-ink-faint">{i.source}, {ago(i.published_at)}</span></span>
          {i.reading !== null ? <span title={i.reading_model === "laya" ? `Read by the Laya model${i.laya_confidence !== null ? `, ${Math.round(i.laya_confidence * 100)}% sure` : ""}` : "Read by the keyword list (not yet scored by the model)"}><StatusPill tone={READING[i.reading].tone}>{READING[i.reading].label}</StatusPill></span> : null}
        </li>
      ))}
    </ul>
  );
}

/** What is worth knowing about one stock right now, then every recent headline that names it. The notes are facts about the chart and the tape, not signals. */
export function StockNotesPanel({ instrumentId, symbol }: { instrumentId: number; symbol: string }) {
  const notes = useNotes([instrumentId]);
  const news = useNews(symbol);
  const [all, setAll] = useState(false);
  return (
    <Panel title={`${symbol}: what to notice`}>
      <div className="p-3"><NoteList notes={notes[String(instrumentId)]} /></div>
      <h3 className="border-t border-line px-3 pt-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">Headlines naming {symbol} (30 days)</h3>
      {news.isError ? <p className="p-3 text-sm text-ink-soft">The headlines could not be loaded just now.</p> : null}
      {news.isLoading ? <div role="status" aria-label="Loading the headlines" className="p-3"><Skeleton className="h-16 w-full" /></div> : null}
      {news.data && news.data.items.length === 0 ? <p className="p-3 text-sm text-ink-soft">No headline in the public feeds names {symbol}. The feeds cover the large and mid caps most.</p> : null}
      {news.data && news.data.items.length > 0 ? (
        <>
          <Headlines items={news.data.items.slice(0, TOP)} />
          {news.data.items.length > TOP ? (
            <div className="px-3 pb-2">
              <button type="button" onClick={() => setAll(true)} className="text-sm font-medium text-brand hover:underline">View all {news.data.items.length} headlines</button>
            </div>
          ) : null}
          <Dialog open={all} title={`Headlines naming ${symbol}`} description="Last 30 days, newest first. Each opens in a new tab." onClose={() => setAll(false)}>
            <div className="max-h-[60vh] overflow-y-auto"><Headlines items={news.data.items} /></div>
          </Dialog>
        </>
      ) : null}
      <p className="border-t border-line px-3 py-2 text-xs text-ink-faint">Each headline is read by the Laya model (or, until it has scored it, a keyword list). Neither has been shown to predict returns.</p>
    </Panel>
  );
}
