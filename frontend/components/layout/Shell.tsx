"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { api } from "@/lib/api/client";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/data/instruments", label: "Data Explorer" },
  { href: "/data/benchmarks", label: "Benchmarks" },
  { href: "/research/backtests", label: "Backtests" },
  { href: "/system", label: "System Activity" },
];

function ApiLight() {
  const { data, isError, isLoading } = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  const ok = data?.api === "ok" && data.database === "ok";
  const label = isLoading ? "checking API" : isError ? "API unreachable" : ok ? "API and database ok" : "API degraded";
  return (
    <span className="flex items-center gap-2 text-xs text-ink-soft" role="status">
      <span className={clsx("h-2.5 w-2.5 rounded-full", isLoading ? "bg-slate-300" : ok ? "bg-emerald-500" : "bg-red-500")} />
      {label}
    </span>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  return (
    <div className="flex min-h-screen">
      <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-panel p-4 md:flex">
        <div className="mb-6">
          <div className="text-sm font-semibold">Vinayak</div>
          <div className="text-xs text-ink-soft">Trading Research Console</div>
        </div>
        <nav className="flex flex-col gap-1" aria-label="Main">
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={clsx(
                "rounded-md px-3 py-2 text-sm",
                path.startsWith(n.href) ? "bg-slate-900 text-white" : "text-ink-soft hover:bg-slate-100",
              )}
            >
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="mt-auto pt-6 text-xs text-ink-faint">Read-only. No orders, no writes.</div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-line bg-panel px-4 py-3">
          <nav className="flex gap-3 md:hidden" aria-label="Mobile">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} className="text-xs text-ink-soft underline">
                {n.label}
              </Link>
            ))}
          </nav>
          <span className="hidden text-sm text-ink-soft md:block">Data, benchmark and research state</span>
          <ApiLight />
        </header>
        <main className="min-w-0 flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
