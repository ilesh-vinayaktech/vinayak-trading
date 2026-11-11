import type { ReactNode } from "react";
import { Icon, type IconName } from "./Icon";
import { buttonClass } from "./styles";

export type Column<T> = { key: string; header: string; cell: (row: T) => ReactNode; className?: string; hideBelow?: "sm" | "md" | "lg" };
const HIDE = { sm: "hidden sm:table-cell", md: "hidden md:table-cell", lg: "hidden lg:table-cell" };

export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse rounded bg-slate-200/70 ${className}`} />;
}

export function EmptyState({ icon = "info", title, children, action }: { icon?: IconName; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <span aria-hidden="true" className="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-slate-100 text-ink-faint">
        <Icon name={icon} size={22} />
      </span>
      <p className="text-sm font-semibold">{title}</p>
      {children ? <p className="mt-1 max-w-sm text-sm text-ink-soft">{children}</p> : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

/** A list as a real table: sticky-feeling header, row hover, loading skeleton, an empty state, and columns that drop away on narrow screens. */
export function DataTable<T>({ caption, columns, rows, rowKey, loading, empty }: { caption: string; columns: Column<T>[]; rows: T[] | undefined; rowKey: (row: T) => string; loading?: boolean; empty: ReactNode }) {
  const cls = (c: Column<T>) => `${c.hideBelow ? HIDE[c.hideBelow] : ""} ${c.className ?? ""}`;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line text-xs font-medium uppercase tracking-wide text-ink-soft">
            {columns.map((c) => (
              <th key={c.key} scope="col" className={`px-4 py-3 font-medium ${cls(c)}`}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-line">
          {loading && !rows
            ? Array.from({ length: 5 }, (_, i) => (
                <tr key={i} aria-hidden="true">
                  {columns.map((c) => (
                    <td key={c.key} className={`px-4 py-4 ${cls(c)}`}><Skeleton className="h-4 w-3/4" /></td>
                  ))}
                </tr>
              ))
            : rows?.map((r) => (
                <tr key={rowKey(r)} className="transition-colors hover:bg-slate-50/70">
                  {columns.map((c) => (
                    <td key={c.key} className={`px-4 py-3.5 align-middle ${cls(c)}`}>{c.cell(r)}</td>
                  ))}
                </tr>
              ))}
        </tbody>
      </table>
      {rows && rows.length === 0 && !loading ? empty : null}
    </div>
  );
}

export function Pagination({ offset, pageSize, total, onChange }: { offset: number; pageSize: number; total: number; onChange: (offset: number) => void }) {
  if (total === 0) return null;
  return (
    <div className="flex items-center justify-between border-t border-line px-4 py-3 text-xs text-ink-soft">
      <span>
        {offset + 1}–{Math.min(offset + pageSize, total)} of {total}
      </span>
      <span className="flex gap-2">
        <button type="button" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - pageSize))} className={buttonClass("secondary", true)}>Previous</button>
        <button type="button" disabled={offset + pageSize >= total} onClick={() => onChange(offset + pageSize)} className={buttonClass("secondary", true)}>Next</button>
      </span>
    </div>
  );
}
