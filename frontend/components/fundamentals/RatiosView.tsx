import { useQuery } from "@tanstack/react-query";
import { Card, ErrorBox, Loading } from "@/components/status/LoadState";
import { api } from "@/lib/api/client";
import { quarterName } from "@/lib/fundamentals";
import { formatRatio, GROUPS, readingText, snapshot, versusYearAgo, type RatioRow } from "@/lib/ratios";

const CHIP = { good: "bg-emerald-100 text-emerald-800", ok: "bg-amber-100 text-amber-800", weak: "bg-red-100 text-red-800" } as const;
const TONE = { good: "text-emerald-700", bad: "text-red-700", neutral: "text-slate-600" } as const;

function Spark({ row }: { row: RatioRow }) {
  const v = row.history.flatMap((h) => (h.value === null ? [] : [Number(h.value)]));
  if (v.length < 2) return <span className="text-slate-300">–</span>;
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
  const pts = v.map((n, i) => `${(i / (v.length - 1)) * 60},${16 - ((n - lo) / span) * 14}`).join(" ");
  const first = row.history[0]?.period_end ?? "", last = row.history[row.history.length - 1]?.period_end ?? "";
  return (
    <svg viewBox="0 0 60 18" className="h-5 w-16" role="img" aria-label={`${row.label}: ${v.length} quarters, ${quarterName(first)} to ${quarterName(last)}`}>
      <polyline points={pts} fill="none" stroke="#475569" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Line({ row }: { row: RatioRow }) {
  const vs = versusYearAgo(row);
  return (
    <tr className="border-t border-line/60 align-top">
      <td className="px-2 py-2">
        <div className="font-medium" title={`How it is worked out: ${row.formula}`}>{row.label}</div>
        <div className="max-w-md text-xs text-ink-soft">{row.meaning}</div>
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-right text-base font-semibold tabular-nums">
        {formatRatio(row.unit, row.value)}
        {row.value === null && row.note ? <div className="max-w-56 whitespace-normal text-right text-xs font-normal text-ink-soft">{row.note}</div> : null}
      </td>
      <td className="whitespace-nowrap px-2 py-2 text-right text-sm tabular-nums text-ink-soft">
        {formatRatio(row.unit, row.year_ago)}
        {vs ? <div className={`text-xs ${TONE[vs.tone]}`}>{vs.text}</div> : null}
      </td>
      <td className="px-2 py-2"><Spark row={row} /></td>
      <td className="px-2 py-2 text-right">
        {row.reading ? <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${CHIP[row.reading]}`} title={row.reading_basis === "own_past" ? "Compared with this company's own last quarters" : "Rule of thumb for this kind of company"}>{readingText(row)}</span> : <span className="text-xs text-slate-400">{readingText(row)}</span>}
      </td>
    </tr>
  );
}

export function RatiosView({ instrumentId, basis }: { instrumentId: number; basis: string | undefined }) {
  const q = useQuery({ queryKey: ["ratios", instrumentId, basis], queryFn: () => api.ratios(instrumentId, basis) });
  if (q.isLoading) return <Loading what="ratios" />;
  if (q.error) return <ErrorBox error={q.error} what="ratios" />;
  const r = q.data;
  if (!r || r.ratios.length === 0) return <p className="text-sm text-ink-soft">No ratios yet: no results are stored for this company.</p>;
  const top = snapshot(r);
  return (
    <div className="space-y-4" data-testid="ratios-view">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        {top.map((x) => (
          <div key={x.key} className="rounded-lg border border-line bg-panel p-3" data-testid={`snap-${x.key}`}>
            <div className="text-xs text-ink-soft">{x.label}</div>
            <div className="text-lg font-semibold tabular-nums">{formatRatio(x.unit, x.value)}</div>
            {x.reading ? <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${CHIP[x.reading]}`}>{readingText(x)}</span> : null}
          </div>
        ))}
      </div>
      <p className="text-xs text-ink-soft">
        {r.price ? `Price ₹${Number(r.price.value).toLocaleString("en-IN", { maximumFractionDigits: 2 })} (last close, ${r.price.date ?? "date unknown"}). ` : "No price available. "}
        Results to {r.latest_period ? quarterName(r.latest_period) : "–"}. Profit ratios cover the last 12 months; balance-sheet ratios use the latest balance sheet (filed half-yearly).
      </p>
      {GROUPS.map((g) => {
        const rows = r.ratios.filter((x) => x.group === g.key);
        if (rows.length === 0) return null;
        return (
          <Card key={g.key} title={g.title} note={g.blurb}>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-ink-soft">
                  <tr>
                    <th className="px-2 py-1 font-medium">Ratio</th>
                    <th className="px-2 py-1 text-right font-medium">Now</th>
                    <th className="px-2 py-1 text-right font-medium">A year ago</th>
                    <th className="px-2 py-1 font-medium">Last 8 quarters</th>
                    <th className="px-2 py-1 text-right font-medium">Reading</th>
                  </tr>
                </thead>
                <tbody>{rows.map((x) => <Line key={x.key} row={x} />)}</tbody>
              </table>
            </div>
          </Card>
        );
      })}
      <p className="text-xs leading-relaxed text-ink-soft">
        Two kinds of reading. “Strong / Fair / Weak” is a rule of thumb for this kind of company (a bank is judged differently from a manufacturer). For valuation, margins and turnover, which depend on the industry, the reading compares the company with its own last quarters (“Cheaper than usual”, “Usual range”, “Pricier than usual”): it says nothing about other companies. Neither is advice. Hover a ratio name to see how it is worked out.
      </p>
    </div>
  );
}
