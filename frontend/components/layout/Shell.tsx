"use client";

import { useQuery } from "@tanstack/react-query";
import clsx from "clsx";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Avatar } from "@/components/ui/Alert";
import { Icon, type IconName } from "@/components/ui/Icon";
import { api } from "@/lib/api/client";
import { useAuth } from "@/lib/auth";
import { isPublicPath } from "@/lib/publicPaths";

type Item = { href: string; label: string; icon: IconName; need?: string };
// `need` hides what a role would be refused anyway; the server is what actually enforces it
const GROUPS: { title: string; items: Item[] }[] = [
  {
    title: "Research",
    items: [
      { href: "/dashboard", label: "Dashboard", icon: "dashboard" },
      { href: "/data/instruments", label: "Data Explorer", icon: "chart" },
      { href: "/data/benchmarks", label: "Benchmarks", icon: "benchmark" },
      { href: "/research/backtests", label: "Backtests", icon: "flask" },
    ],
  },
  {
    title: "Operations",
    items: [
      { href: "/research/reviews", label: "Reviews", icon: "review", need: "ops:read" },
      { href: "/system", label: "System Activity", icon: "activity", need: "ops:read" },
      { href: "/support", label: "Support", icon: "support", need: "tickets:own" },
      { href: "/tasks", label: "Tasks", icon: "tasks", need: "crm:read" },
    ],
  },
  {
    title: "Administration",
    items: [
      { href: "/users", label: "Users", icon: "users", need: "users:read" },
      { href: "/audit", label: "Audit log", icon: "scroll", need: "audit:read" },
    ],
  },
  {
    title: "Account",
    items: [
      { href: "/kite", label: "Kite connection", icon: "plug", need: "kite:own" },
      { href: "/account/security", label: "Account security", icon: "shield" },
    ],
  },
];

function ApiLight() {
  const { data, isError, isLoading } = useQuery({ queryKey: ["health"], queryFn: api.health, refetchInterval: 30_000 });
  const ok = data?.api === "ok" && data.database === "ok";
  const label = isLoading ? "checking API" : isError ? "API unreachable" : ok ? "API and database ok" : "API degraded";
  return (
    <span className="flex items-center gap-2 text-xs text-ink-soft" role="status">
      <span className={clsx("h-2.5 w-2.5 rounded-full", isLoading ? "bg-slate-300" : ok ? "bg-emerald-500" : "bg-red-500")} />
      <span className="hidden sm:inline">{label}</span>
    </span>
  );
}

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <span aria-hidden="true" className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-sm font-bold text-white">V</span>
      <span>
        <span className="block text-sm font-semibold leading-tight">Vinayak</span>
        <span className="block text-xs leading-tight text-ink-soft">Trading Research Console</span>
      </span>
    </div>
  );
}

function NavList({ groups, path, onNavigate, label }: { groups: { title: string; items: Item[] }[]; path: string; onNavigate?: () => void; label: string }) {
  return (
    <nav className="space-y-5" aria-label={label}>
      {groups.map((g) => (
        <div key={g.title}>
          <div className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">{g.title}</div>
          <ul className="space-y-0.5">
            {g.items.map((n) => {
              const active = path === n.href || path.startsWith(`${n.href}/`);
              return (
                <li key={n.href}>
                  <Link href={n.href} onClick={onNavigate} aria-current={active ? "page" : undefined} className={clsx("flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors", active ? "bg-brand-soft font-medium text-brand-dark" : "text-ink-soft hover:bg-slate-100 hover:text-ink")}>
                    <Icon name={n.icon} className={active ? "text-brand" : "text-ink-faint"} />
                    {n.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function AccountMenu({ name, role, onSignOut }: { name: string; role: string; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !root.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return (
    <div ref={root} className="relative">
      <button type="button" aria-label="Account menu" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)} className="flex items-center gap-2 rounded-lg px-1.5 py-1 hover:bg-slate-100">
        <Avatar name={name} />
        <span className="hidden text-left md:block">
          <span className="block text-sm font-medium leading-tight" data-testid="who">{name} · {role}</span>
        </span>
        <Icon name="chevron" size={16} className="text-ink-faint" />
      </button>
      {open ? (
        <div role="menu" aria-label="Account" className="absolute right-0 top-11 z-40 w-56 rounded-lg border border-line bg-white py-1 shadow-lg">
          <div className="border-b border-line px-3 py-2 text-xs text-ink-soft">
            Signed in as <span className="font-medium text-ink">{name}</span>
          </div>
          <Link role="menuitem" href="/account/security" onClick={() => setOpen(false)} className="flex items-center gap-2.5 px-3 py-2 text-sm text-ink hover:bg-slate-50">
            <Icon name="shield" className="text-ink-faint" /> Account security
          </Link>
          <button role="menuitem" type="button" onClick={onSignOut} className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-sm text-ink hover:bg-slate-50">
            <Icon name="logout" className="text-ink-faint" /> Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const { user, loading, can, signOut } = useAuth();
  const [drawer, setDrawer] = useState(false);
  const onPublic = isPublicPath(path);
  const restricted = Boolean(user && (user.enrolment_required || user.must_change_password));
  useEffect(() => {
    if (loading || onPublic) return;
    if (!user) router.replace(`/login?next=${encodeURIComponent(path)}`);
    else if (restricted && path !== "/account/security") router.replace("/account/security");
  }, [loading, onPublic, user, restricted, path, router]);
  useEffect(() => setDrawer(false), [path]);
  if (onPublic) return <>{children}</>;
  if (loading || !user || (restricted && path !== "/account/security")) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-2 text-sm text-ink-soft" role="status">
        <span>Loading...</span>
        <a href={path} className="text-xs text-blue-700 underline">Taking long? Reload</a>
      </div>
    );
  }
  const groups = restricted ? [] : GROUPS.map((g) => ({ ...g, items: g.items.filter((n) => !n.need || can(n.need)) })).filter((g) => g.items.length > 0);
  const sidebar = restricted ? (
    <p className="rounded-lg bg-amber-50 px-3 py-2.5 text-xs leading-relaxed text-amber-900">Finish the account setup on this page to unlock the rest of the console.</p>
  ) : (
    <NavList groups={groups} path={path} label="Main" />
  );
  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:shadow">
        Skip to content
      </a>
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col overflow-y-auto border-r border-line bg-panel px-3 py-5 md:flex">
        <div className="mb-6 px-3"><Brand /></div>
        {sidebar}
        <div className="mt-auto px-3 pt-6 text-[11px] leading-relaxed text-ink-faint">Research console. Strategies and orders are not enabled yet.</div>
      </aside>
      {drawer ? (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button type="button" aria-label="Close menu" className="absolute inset-0 bg-slate-900/40" onClick={() => setDrawer(false)} />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85%] overflow-y-auto bg-panel px-3 py-5 shadow-xl">
            <div className="mb-6 flex items-center justify-between px-3">
              <Brand />
              <button type="button" aria-label="Close menu" onClick={() => setDrawer(false)} className="rounded-lg p-1.5 text-ink-soft hover:bg-slate-100"><Icon name="close" /></button>
            </div>
            {restricted ? sidebar : <NavList groups={groups} path={path} label="Mobile" onNavigate={() => setDrawer(false)} />}
          </div>
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col overflow-x-hidden">
        <header className="sticky top-0 z-30 flex items-center justify-between gap-3 border-b border-line bg-panel/95 px-4 py-2.5 backdrop-blur md:px-6">
          <div className="flex items-center gap-2">
            <button type="button" aria-label="Open menu" onClick={() => setDrawer(true)} className="rounded-lg p-1.5 text-ink-soft hover:bg-slate-100 md:hidden"><Icon name="menu" size={20} /></button>
            <span className="md:hidden"><Brand /></span>
          </div>
          <div className="flex items-center gap-4">
            <ApiLight />
            <AccountMenu name={user.name} role={user.role} onSignOut={() => void signOut()} />
          </div>
        </header>
        <main id="main" className="w-full max-w-[1680px] min-w-0 flex-1 p-4 md:p-8">{children}</main>
      </div>
    </div>
  );
}
