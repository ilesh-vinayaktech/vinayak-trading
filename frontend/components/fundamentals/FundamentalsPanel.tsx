"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { RatiosView } from "@/components/fundamentals/RatiosView";
import { StatementTable } from "@/components/fundamentals/StatementTable";
import { SummaryView } from "@/components/fundamentals/SummaryView";
import { Badge } from "@/components/status/Badge";
import { Card, ErrorBox, Loading } from "@/components/status/LoadState";
import { api } from "@/lib/api/client";
import { balanceTable, cashTable, quarterlyTable } from "@/lib/fundamentalsTable";
import { figure, label, lines, quarterName, type Period, type Scope } from "@/lib/fundamentals";

const SECTIONS: { scope: Scope; title: string; note: string }[] = [
  { scope: "quarter", title: "Profit and loss, for the quarter", note: "Amounts in ₹ crore; per-share figures as reported." },
  { scope: "instant", title: "Balance sheet, at the quarter end", note: "Companies file a balance sheet half-yearly, so only the September and March quarters have one." },
  { scope: "ytd", title: "Year to date, including cash flow", note: "From the start of the financial year to the quarter end. The cash flow statement is half-yearly too." },
];

function Table({ periods, scope, filter }: { periods: Period[]; scope: Scope; filter: string }) {
  const rows = lines(periods, scope, filter);
  if (rows.length === 0) return <p className="text-sm text-ink-soft">{filter ? "No line matches." : "No filing reports these figures."}</p>;
  return (
    <div className="max-h-[32rem] overflow-auto">
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 border-b border-line bg-panel text-xs text-ink-soft">
          <tr>
            <th className="px-2 py-2 font-medium">Line</th>
            {periods.map((p) => (
              <th key={p.period_end} className="px-2 py-2 text-right font-medium">{quarterName(p.period_end)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((n) => (
            <tr key={n} className="border-b border-line/60">
              <td className="px-2 py-1.5" title={n}>{label(n)}</td>
              {periods.map((p) => (
                <td key={p.period_end} className="px-2 py-1.5 text-right tabular-nums">{figure(n, p[scope][n])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Quarterly results as filed with NSE, for the instrument on the Data Explorer. More sections will be added here. */
export function FundamentalsPanel({ instrumentId, symbol }: { instrumentId: number; symbol: string }) {
  const [basis, setBasis] = useState<string | undefined>();
  const [filter, setFilter] = useState("");
  const [view, setView] = useState<"summary" | "ratios" | "all">("summary");
  const q = useQuery({ queryKey: ["fundamentals", instrumentId, basis], queryFn: () => api.fundamentals(instrumentId, basis) });
  const every = q.data?.periods ?? [];
  const periods = [...every].slice(0, 8);
  const newest = periods[0];
  const oldest = periods[periods.length - 1];

  return (
    <section className="space-y-4" aria-label="Fundamentals">
      <h2 className="text-base font-semibold tracking-tight">Fundamentals</h2>
      {q.isLoading ? <Loading what="fundamentals" /> : null}
      {q.error ? <ErrorBox error={q.error} what="fundamentals" /> : null}
      {q.data && !newest ? <p className="text-sm text-ink-soft">No quarterly results are stored for {symbol} yet.</p> : null}
      {q.data && newest && oldest ? (
        <>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <div role="group" aria-label="Basis" className="flex overflow-hidden rounded-md border border-line">
              {q.data.bases.map((b) => (
                <button key={b} type="button" aria-pressed={b === q.data.basis} onClick={() => setBasis(b)} className={`px-3 py-1.5 ${b === q.data.basis ? "bg-slate-900 text-white" : "hover:bg-slate-100"}`}>
                  {b === "CONSOLIDATED" ? "Consolidated" : "Standalone"}
                </button>
              ))}
            </div>
            <div role="group" aria-label="View" className="flex overflow-hidden rounded-md border border-line">
              {(["summary", "ratios", "all"] as const).map((v) => (
                <button key={v} type="button" aria-pressed={view === v} onClick={() => setView(v)} className={`px-3 py-1.5 ${view === v ? "bg-slate-900 text-white" : "hover:bg-slate-100"}`}>
                  {v === "summary" ? "Summary" : v === "ratios" ? "Ratios" : "All figures"}
                </button>
              ))}
            </div>
            <span className="text-xs text-ink-soft">
              {periods.length} quarters, {quarterName(oldest.period_end)} to {quarterName(newest.period_end)} · latest filed {newest.filed_at.slice(0, 10)}
            </span>
            <Badge tone={newest.audited ? "good" : "neutral"}>{newest.audited ? "audited" : "unaudited"}</Badge>
          </div>
          {view === "summary" ? (
            <SummaryView periods={every} />
          ) : view === "ratios" ? (
            <RatiosView instrumentId={instrumentId} basis={q.data.basis ?? undefined} />
          ) : (
            <>
              <Card title="Quarterly results" note="Growth under each key line: QoQ is against the previous quarter, YoY against the same quarter a year earlier. Operating profit is revenue less expenses, with interest and depreciation added back.">
                <StatementTable table={quarterlyTable(every)} empty="No quarterly figures." />
              </Card>
              <Card title="Balance sheet" note="Filed half-yearly (September and March).">
                <StatementTable table={balanceTable(every)} empty="No balance sheet has been filed in these quarters." />
              </Card>
              <Card title="Cash flow" note="Year to date from the start of the financial year; filed half-yearly.">
                <StatementTable table={cashTable(every)} empty="No cash flow statement has been filed in these quarters." />
              </Card>
              <details className="rounded-xl border border-line bg-panel p-5 shadow-card">
                <summary className="cursor-pointer text-base font-semibold tracking-tight">Every line item the filings report</summary>
                <div className="mt-4 space-y-6">
                  <input aria-label="Filter lines" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter lines (e.g. tax, borrowings)" className="w-72 rounded-md border border-line px-3 py-1.5 text-sm outline-none focus:border-blue-500" />
                  {SECTIONS.map((s) => (
                    <div key={s.scope}>
                      <h3 className="mb-1 text-sm font-semibold">{s.title}</h3>
                      <p className="mb-2 text-xs text-ink-soft">{s.note}</p>
                      <Table periods={periods} scope={s.scope} filter={filter} />
                    </div>
                  ))}
                </div>
              </details>
            </>
          )}
        </>
      ) : null}
    </section>
  );
}
