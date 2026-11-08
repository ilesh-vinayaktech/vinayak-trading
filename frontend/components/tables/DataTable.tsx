"use client";

import { flexRender, getCoreRowModel, getSortedRowModel, useReactTable, type ColumnDef, type SortingState } from "@tanstack/react-table";
import { useState } from "react";

export function DataTable<T>({ data, columns, empty }: { data: T[]; columns: ColumnDef<T, unknown>[]; empty: string }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });
  if (data.length === 0) return <p className="text-sm text-ink-soft">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-line text-xs text-ink-soft">
          {table.getHeaderGroups().map((hg) => (
            <tr key={hg.id}>
              {hg.headers.map((h) => (
                <th key={h.id} className="cursor-pointer select-none px-2 py-2 font-medium" onClick={h.column.getToggleSortingHandler()}>
                  {flexRender(h.column.columnDef.header, h.getContext())}
                  {{ asc: " ↑", desc: " ↓" }[h.column.getIsSorted() as string] ?? ""}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((r) => (
            <tr key={r.id} className="border-b border-line last:border-0">
              {r.getVisibleCells().map((c) => (
                <td key={c.id} className="px-2 py-2 align-top tabular-nums">
                  {flexRender(c.column.columnDef.cell, c.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
