import { figure } from "@/lib/fundamentals";
import type { Row, Table } from "@/lib/fundamentalsTable";

function cell(row: Row, v: number | undefined): string {
  if (v === undefined) return "–";
  if (row.kind === "percent") return `${v.toFixed(2)}%`;
  if (row.kind === "pershare") return figure("PerShare", String(v));
  return figure("Amount", String(v));
}

function Growth({ label, values }: { label: string; values: (number | null)[] }) {
  return (
    <tr className="text-xs">
      <td className="sticky left-0 bg-panel py-0.5 pl-6 pr-2 text-ink-soft">{label}</td>
      {values.map((g, i) => (
        <td key={i} className={`px-2 py-0.5 text-right tabular-nums ${g === null ? "text-slate-400" : g >= 0 ? "text-emerald-700" : "text-red-700"}`}>
          {g === null ? "–" : `${g > 0 ? "+" : ""}${g.toFixed(1)}%`}
        </td>
      ))}
    </tr>
  );
}

/** Quarters across, oldest to newest with the latest highlighted; QoQ / YoY growth sit under the key lines. */
export function StatementTable({ table, empty }: { table: Table; empty: string }) {
  if (table.rows.length === 0) return <p className="text-sm text-ink-soft">{empty}</p>;
  const last = table.columns.length - 1;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-max text-sm">
        <thead className="border-b border-line text-xs text-ink-soft">
          <tr>
            <th className="sticky left-0 bg-panel px-2 py-2 text-left font-medium">₹ crore</th>
            {table.columns.map((c, i) => (
              <th key={c.end} className={`px-2 py-2 text-right font-medium ${i === last ? "bg-blue-50 text-ink" : ""}`}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.flatMap((r) => [
            <tr key={r.key} className={r.strong ? "border-t border-line/60 font-semibold" : ""}>
              <td className="sticky left-0 bg-panel px-2 py-1.5">{r.label}</td>
              {r.values.map((v, i) => (
                <td key={i} className={`px-2 py-1.5 text-right tabular-nums ${i === last ? "bg-blue-50/60" : ""}`}>{cell(r, v)}</td>
              ))}
            </tr>,
            ...(r.qoq ? [<Growth key={`${r.key}-qoq`} label="QoQ" values={r.qoq} />] : []),
            ...(r.yoy ? [<Growth key={`${r.key}-yoy`} label="YoY" values={r.yoy} />] : []),
          ])}
        </tbody>
      </table>
    </div>
  );
}
