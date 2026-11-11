"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { fmtDateTime, fmtRelative } from "@/lib/formatting";
import { Icon } from "./Icon";

/** A bordered panel for tables and lists that run edge to edge (a Card has padding; this does not). */
export function Panel({ title, actions, children }: { title?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="overflow-hidden rounded-xl border border-line bg-panel shadow-card">
      {title || actions ? (
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3.5">
          {title ? <h2 className="text-sm font-semibold tracking-tight">{title}</h2> : <span />}
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}

/** A settings block: what it is on the left, the controls on the right, like the account pages of a mature product. */
export function SettingsSection({ title, description, children }: { title: string; description?: ReactNode; children: ReactNode }) {
  return (
    <section className="grid gap-4 border-b border-line py-8 first:pt-0 last:border-b-0 md:grid-cols-3 md:gap-10">
      <div>
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {description ? <p className="mt-1 text-sm leading-relaxed text-ink-soft">{description}</p> : null}
      </div>
      <div className="min-w-0 md:col-span-2">{children}</div>
    </section>
  );
}

export type Tab<K extends string> = { key: K; label: string; count?: number };

/** Section tabs under a page title. Real tablist semantics, arrow keys move between tabs. */
export function Tabs<K extends string>({ tabs, value, onChange, label }: { tabs: Tab<K>[]; value: K; onChange: (k: K) => void; label: string }) {
  return (
    <div role="tablist" aria-label={label} className="flex min-w-0 flex-1 gap-1 overflow-x-auto overflow-y-hidden border-b border-line">
      {tabs.map((t, i) => {
        const active = t.key === value;
        return (
          <button
            key={t.key}
            role="tab"
            type="button"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.key)}
            onKeyDown={(e) => {
              const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
              if (step) onChange(tabs[(i + step + tabs.length) % tabs.length]?.key ?? t.key);
            }}
            className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${active ? "border-brand text-brand-dark" : "border-transparent text-ink-soft hover:text-ink"}`}
          >
            {t.label}
            {t.count !== undefined ? <span className={`ml-2 rounded-full px-1.5 py-0.5 text-xs ${active ? "bg-brand-soft text-brand-dark" : "bg-slate-100 text-ink-soft"}`}>{t.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-2">
      <ol className="flex flex-wrap items-center gap-1 text-xs text-ink-soft">
        {items.map((c, i) => (
          <li key={c.label} className="flex items-center gap-1">
            {i > 0 ? <Icon name="chevron" size={12} className="-rotate-90 text-ink-faint" /> : null}
            {c.href ? <Link href={c.href} className="hover:text-ink hover:underline">{c.label}</Link> : <span aria-current="page">{c.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function DefinitionList({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <dl className="divide-y divide-line text-sm">
      {items.map((i) => (
        <div key={i.label} className="flex items-start justify-between gap-4 py-2.5">
          <dt className="text-ink-soft">{i.label}</dt>
          <dd className="text-right font-medium">{i.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A status with a coloured dot and a word, so the state never rests on colour alone. */
export function StatusPill({ tone, children }: { tone: "good" | "warn" | "bad" | "neutral" | "info"; children: ReactNode }) {
  const dot = { good: "bg-emerald-500", warn: "bg-amber-500", bad: "bg-red-500", neutral: "bg-slate-400", info: "bg-blue-500" }[tone];
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-white px-2.5 py-0.5 text-xs font-medium text-ink">
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${dot}`} />
      {children}
    </span>
  );
}

/** "2 hours ago" with the exact time on hover and for screen readers, so lists read quickly without losing precision. */
export function RelativeTime({ iso, now }: { iso: string; now?: number }) {
  return (
    <time dateTime={iso} title={fmtDateTime(iso)}>
      {fmtRelative(iso, now)}
    </time>
  );
}
