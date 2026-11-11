"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { isPublicPath } from "@/lib/publicPaths";

// `need` hides what the role would be refused anyway; the server is what actually enforces it
const NAV: { href: string; label: string; need?: string }[] = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/data/instruments", label: "Data Explorer" },
  { href: "/data/benchmarks", label: "Benchmarks" },
  { href: "/research/backtests", label: "Backtests" },
  { href: "/research/reviews", label: "Reviews", need: "ops:read" },
  { href: "/system", label: "System Activity", need: "ops:read" },
  { href: "/users", label: "Users", need: "users:read" },
  { href: "/audit", label: "Audit log", need: "audit:read" },
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
  const router = useRouter();
  const { user, loading, can, signOut } = useAuth();
  const onLogin = isPublicPath(path);
  const restricted = Boolean(user && (user.enrolment_required || user.must_change_password));
  useEffect(() => {
    if (loading || onLogin) return;
    if (!user) router.replace(`/login?next=${encodeURIComponent(path)}`);
    else if (restricted && path !== "/account/security") router.replace("/account/security");
  }, [loading, onLogin, user, restricted, path, router]);
  if (onLogin) return <>{children}</>;
  if (loading || !user || (restricted && path !== "/account/security")) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-ink-soft" role="status">
        Loading...
      </div>
    );
  }
  const nav = restricted ? [] : NAV.filter((n) => !n.need || can(n.need));
  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:shadow">
        Skip to content
      </a>
      <aside className="hidden w-60 shrink-0 flex-col border-r border-line bg-panel p-4 md:flex">
        <div className="mb-6">
          <div className="text-sm font-semibold">Vinayak</div>
          <div className="text-xs text-ink-soft">Trading Research Console</div>
        </div>
        <nav className="flex flex-col gap-1" aria-label="Main">
          {nav.map((n) => (
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
        <div className="mt-auto space-y-2 pt-6">
          <Link href="/account/security" className={clsx("block rounded-md px-3 py-2 text-sm", path.startsWith("/account") ? "bg-slate-900 text-white" : "text-ink-soft hover:bg-slate-100")}>
            Account security
          </Link>
          <div className="px-3 text-xs text-ink-faint">No orders. The only write is a recorded review decision.</div>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col overflow-x-hidden">
        <header className="sticky top-0 z-10 flex flex-col gap-2 border-b border-line bg-panel px-4 py-3 md:flex-row md:items-center md:justify-between">
          <nav className="flex flex-wrap gap-x-4 gap-y-1 md:hidden" aria-label="Mobile">
            {nav.map((n) => (
              <Link key={n.href} href={n.href} className="text-xs text-ink-soft underline">
                {n.label}
              </Link>
            ))}
          </nav>
          <span className="hidden text-sm text-ink-soft md:block">Data, benchmark and research state</span>
          <div className="flex items-center gap-4">
            <ApiLight />
            <span className="text-xs text-ink-soft" data-testid="who">
              {user.name} · {user.role}
            </span>
            <button type="button" onClick={() => void signOut()} className="rounded-md border border-line px-2 py-1 text-xs hover:bg-slate-50">
              Sign out
            </button>
          </div>
        </header>
        <main id="main" className="w-full max-w-[1680px] min-w-0 flex-1 p-4 md:p-6">{children}</main>
      </div>
    </div>
  );
}
