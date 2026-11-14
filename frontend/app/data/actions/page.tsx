"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge } from "@/components/status/Badge";
import { ErrorBox } from "@/components/status/LoadState";
import { DataTable, EmptyState, type Column } from "@/components/ui/DataTable";
import { Panel } from "@/components/ui/Layout";
import { buttonClass } from "@/components/ui/styles";
import { api } from "@/lib/api/client";
import type { ActionWorklist } from "@/lib/schemas";

type Row = ActionWorklist["items"][number];
const PAGE = 200;
const label = (k: string) => k.replaceAll("_", " ");

const COLUMNS: Column<Row>[] = [
  { key: "impact", header: "Impact", className: "tabular-nums", cell: (r) => (r.impact === 0 ? <span className="text-ink-faint">0</span> : <span className="font-semibold">{r.impact}</span>) },
  {
    key: "stock",
    header: "Stock",
    cell: (r) => (
      <span className="font-medium">
        {r.symbol} {r.in_nifty200 ? <Badge tone="good">Nifty 200</Badge> : null}
      </span>
    ),
  },
  { key: "ex", header: "Ex-date", cell: (r) => r.ex_date },
  { key: "kind", header: "Kind", cell: (r) => label(r.kind) },
  {
    key: "move",
    header: "Price move",
    className: "text-right tabular-nums",
    cell: (r) => (r.move_pct === null ? <span className="text-ink-faint" title="No price before this date">no prices</span> : `${Number(r.move_pct) > 0 ? "+" : ""}${r.move_pct}%`),
  },
  { key: "subject", header: "What NSE said", hideBelow: "md", cell: (r) => <span className="text-ink-soft">{r.subject}</span> },
  { key: "reason", header: "Why it needs you", hideBelow: "lg", cell: (r) => <span className="text-ink-soft">{r.reason}</span> },
];

/** Corporate actions waiting for a person, biggest potential effect on prices first. Read-only: deciding is done with scripts/review_actions.py. */
export default function ActionWorklistPage() {
  const [kind, setKind] = useState<string | undefined>();
  const [limit, setLimit] = useState(PAGE);
  const q = useQuery({ queryKey: ["action-worklist", kind, limit], queryFn: () => api.actionWorklist(limit, kind) });
  const d = q.data;
  const all = d ? Object.values(d.by_kind).reduce((a, b) => a + b, 0) : 0;

  return (
    <div className="space-y-4">
      <PageHeader title="Corporate action worklist" subtitle="Splits, demergers, rights issues, buy-backs and dividends the parser could not price on its own, ranked by how much a missing adjustment could move prices you use. Nothing is adjusted until a person decides." />
      {q.error ? <ErrorBox error={q.error} what="the worklist" /> : null}
      {d ? (
        <div className="flex flex-wrap items-center gap-2 text-sm" role="group" aria-label="Kind">
          <button type="button" aria-pressed={kind === undefined} onClick={() => setKind(undefined)} className={buttonClass(kind === undefined ? "primary" : "secondary", true)}>
            all ({all})
          </button>
          {Object.entries(d.by_kind).sort((a, b) => b[1] - a[1]).map(([k, n]) => (
            <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)} className={buttonClass(kind === k ? "primary" : "secondary", true)}>
              {label(k)} ({n})
            </button>
          ))}
        </div>
      ) : null}
      <Panel>
        <DataTable caption="Corporate actions waiting for review" columns={COLUMNS} rows={d?.items} rowKey={(r) => `${r.symbol}-${r.ex_date}-${r.kind}`} loading={q.isLoading} empty={<EmptyState icon="check" title="Nothing waiting">Every action in the queue has a decision.</EmptyState>} />
        {d && d.total > d.items.length ? (
          <p className="flex items-center gap-3 px-4 py-3 text-sm text-ink-soft">
            Showing {d.items.length} of {d.total}.
            <button type="button" onClick={() => setLimit(5000)} className={buttonClass("secondary", true)}>Show all</button>
          </p>
        ) : null}
      </Panel>
    </div>
  );
}
