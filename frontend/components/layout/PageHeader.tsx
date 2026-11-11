import type { ReactNode } from "react";
import { Breadcrumbs } from "@/components/ui/Layout";

/** The title block of a page: optional breadcrumb trail, a clear title and description, and the page's primary actions. */
export function PageHeader({ title, subtitle, actions, breadcrumbs }: { title: string; subtitle?: string; actions?: ReactNode; breadcrumbs?: { label: string; href?: string }[] }) {
  return (
    <div className="mb-6">
      {breadcrumbs ? <Breadcrumbs items={breadcrumbs} /> : null}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle ? <p className="mt-1 max-w-3xl text-sm text-ink-soft">{subtitle}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}
