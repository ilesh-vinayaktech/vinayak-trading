"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import type { StockNote } from "@/lib/schemas";

export const NOTE_LIMIT = 60; // what the server will answer for in one request

/** The notes of every stock in a list, in one request, refreshed each minute. Only the first NOTE_LIMIT ids are asked about; a stock with nothing to note is absent. */
export function useNotes(ids: number[]): Record<string, StockNote[]> {
  const key = [...new Set(ids)].sort((a, b) => a - b).slice(0, NOTE_LIMIT);
  const q = useQuery({ queryKey: ["market", "notes", key.join(",")], queryFn: () => api.stockNotes(key), enabled: key.length > 0, refetchInterval: 60_000, staleTime: 30_000, retry: false, placeholderData: (prev) => prev });
  return q.data?.notes ?? {};
}

const TONE: Record<StockNote["tone"], string> = {
  good: "border-emerald-200 bg-emerald-50 text-emerald-800",
  bad: "border-red-200 bg-red-50 text-red-800",
  warn: "border-amber-200 bg-amber-50 text-amber-800",
  info: "border-sky-200 bg-sky-50 text-sky-800",
};

function Chip({ n }: { n: StockNote }) {
  return <span className={`inline-block whitespace-nowrap rounded-full border px-2 py-0.5 text-xs ${TONE[n.tone]}`} title={n.detail ?? n.text}>{n.text}</span>;
}

/** The most important few notes of one stock as small coloured chips; the rest are one "+n" chip whose tooltip lists them. Hover a chip for its full reading. */
export function NoteChips({ notes, max = 3 }: { notes: StockNote[] | undefined; max?: number }) {
  if (!notes || notes.length === 0) return <span className="text-ink-faint">–</span>;
  const rest = notes.slice(max);
  return (
    <span className="flex flex-wrap gap-1" aria-label="Notes">
      {notes.slice(0, max).map((n) => <Chip key={n.kind + n.text} n={n} />)}
      {rest.length > 0 ? <span className="inline-block rounded-full border border-line px-2 py-0.5 text-xs text-ink-soft" title={rest.map((n) => n.text).join("; ")}>+{rest.length}</span> : null}
    </span>
  );
}

/** The same as a full list with each note's reading written out, for a stock's own page. */
export function NoteList({ notes }: { notes: StockNote[] | undefined }) {
  if (!notes || notes.length === 0) return <p className="text-sm text-ink-soft">Nothing stands out about this stock right now.</p>;
  return (
    <ul className="space-y-1.5" aria-label="Notes">
      {notes.map((n) => (
        <li key={n.kind + n.text} className="flex flex-wrap items-baseline gap-x-2 text-sm"><Chip n={n} /><span className="text-ink-soft">{n.detail}</span></li>
      ))}
    </ul>
  );
}
