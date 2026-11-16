"use client";

import type { SignalDay } from "@/lib/schemas";

/** The strategy's buy and sell decisions for the open stock, newest first, each with WHY: which conditions passed and which failed, with the numbers. Reads what the chart already drew. */
export function DecisionList({ days, name }: { days: SignalDay[]; name: string }) {
  const decisions = days.filter((d) => d.action).reverse();
  return (
    <section className="rounded-xl border border-line bg-white" aria-label="Strategy decisions" data-testid="decision-list">
      <header className="border-b border-line px-5 py-3 text-sm font-semibold">
        {name}: {decisions.length} decision{decisions.length === 1 ? "" : "s"} in this range
      </header>
      {decisions.length === 0 ? (
        <p className="px-5 py-4 text-sm text-ink-soft">No buy or sell in this range.</p>
      ) : (
        <ul className="divide-y divide-line px-5">
          {decisions.map((d) => (
            <li key={d.day} className="py-3 text-sm" data-testid="decision">
              <div className="flex flex-wrap items-center gap-2">
                <span className={`rounded px-2 py-0.5 text-xs font-semibold text-white ${d.action === "BUY" ? "bg-emerald-600" : "bg-red-600"}`}>{d.action}</span>
                <span className="font-medium">{d.day}</span>
                <span className="text-xs text-ink-soft">
                  close {d.close}
                  {d.fill_day ? ` · filled ${d.fill_day} at ${d.fill_price}` : " · not filled yet (last bar)"}
                </span>
              </div>
              <div className="mt-1 whitespace-pre-line text-xs text-ink-soft">{d.reason}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
