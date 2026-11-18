"use client";

import { useQuery } from "@tanstack/react-query";
import { NoteList, useNotes } from "@/components/market/NoteChips";
import { Skeleton } from "@/components/ui/DataTable";
import { Panel, StatusPill } from "@/components/ui/Layout";
import { api } from "@/lib/api/client";

const mood = (v: number) => (v >= 0.15 ? "Positive" : v <= -0.15 ? "Negative" : "Mixed");
const tone = (v: number | null) => (v === null ? "neutral" : v >= 0.15 ? "good" : v <= -0.15 ? "bad" : "neutral");
const ago = (iso: string) => {
  const h = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 3_600_000));
  return h < 1 ? "just now" : h < 24 ? `${h}h ago` : `${Math.round(h / 24)}d ago`;
};

/** What is worth knowing about one stock right now, then every recent headline that names it. The notes are facts about the chart and the tape, not signals. */
export function StockNotesPanel({ instrumentId, symbol }: { instrumentId: number; symbol: string }) {
  const notes = useNotes([instrumentId]);
  const news = useQuery({ queryKey: ["market", "news", "for", symbol], queryFn: () => api.marketNewsFor(symbol), staleTime: 5 * 60_000, retry: false });
  return (
    <Panel title={`${symbol}: what to notice`}>
      <div className="p-3"><NoteList notes={notes[String(instrumentId)]} /></div>
      <h3 className="border-t border-line px-3 pt-2 text-xs font-semibold uppercase tracking-wide text-ink-soft">Headlines naming {symbol} (30 days)</h3>
      {news.isError ? <p className="p-3 text-sm text-ink-soft">The headlines could not be loaded just now.</p> : null}
      {news.isLoading ? <div role="status" aria-label="Loading the headlines" className="p-3"><Skeleton className="h-16 w-full" /></div> : null}
      {news.data && news.data.items.length === 0 ? <p className="p-3 text-sm text-ink-soft">No headline in the public feeds names {symbol}. The feeds cover the large and mid caps most.</p> : null}
      {news.data && news.data.items.length > 0 ? (
        <ul className="divide-y divide-line px-3 pb-1 pt-1 text-sm">
          {news.data.items.slice(0, 10).map((i) => (
            <li key={i.url} className="flex items-start justify-between gap-3 py-1.5">
              <span><a href={i.url} target="_blank" rel="noopener noreferrer" className="hover:underline">{i.title}</a><span className="block text-xs text-ink-faint">{i.source}, {ago(i.published_at)}</span></span>
              {i.sentiment !== null ? <StatusPill tone={tone(i.sentiment)}>{mood(i.sentiment)}</StatusPill> : null}
            </li>
          ))}
        </ul>
      ) : null}
      <p className="border-t border-line px-3 py-2 text-xs text-ink-faint">The sentiment is a word-list reading and has not been shown to predict returns.</p>
    </Panel>
  );
}
