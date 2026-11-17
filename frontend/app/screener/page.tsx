"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { SaveScreenDialog } from "@/components/strategies/SaveScreenDialog";
import { Alert } from "@/components/ui/Alert";
import { EmptyState, Skeleton } from "@/components/ui/DataTable";
import { Panel, Tabs } from "@/components/ui/Layout";
import { buttonClass, inputClass } from "@/components/ui/styles";
import { ApiError, api } from "@/lib/api/client";
import type { ScreenerCondition, ScreenerMeta } from "@/lib/schemas";

type Cat = "all" | ScreenerMeta["presets"][number]["category"];
type Cond = { field: string; op: string; lo: string; hi: string };
const OPS: Record<string, string> = {
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  eq: "=",
  ne: "≠",
  between: "between",
};
const UNIT: Record<string, string> = {
  pct: "%",
  x: "",
  days: " d",
  crore: " Cr",
  inr: "₹",
  text: "",
};
const BASE_COLS = ["price", "chg_1d", "score"];

const fmt = (v: string | number | boolean | null | undefined, unit: string) => {
  if (v === null || v === undefined) return "–";
  const n = Number(v);
  if (unit === "text" || Number.isNaN(n)) return String(v);
  const s = n.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return unit === "inr" ? `₹${s}` : `${s}${UNIT[unit] ?? ""}`;
};
const toCond = (c: ScreenerCondition): Cond => {
  const [lo, hi] = Array.isArray(c.value)
    ? (c.value as unknown[]).map(String)
    : [String(c.value), ""];
  return { field: c.field, op: c.op, lo: lo ?? "", hi: hi ?? "" };
};
const toApi = (c: Cond): ScreenerCondition => ({
  field: c.field,
  op: c.op,
  value: c.op === "between" ? [c.lo, c.hi] : c.lo,
});

export default function ScreenerPage() {
  const meta = useQuery({
    queryKey: ["screener-meta"],
    queryFn: api.screenerMeta,
    staleTime: Infinity,
  });
  const router = useRouter();
  const [cat, setCat] = useState<Cat>("all");
  const [conds, setConds] = useState<Cond[]>([]);
  const [match, setMatch] = useState<"all" | "any">("all");
  const [sort, setSort] = useState<{ key: string; desc: boolean } | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const run = useMutation({ mutationFn: api.runScreener });

  const fields = useMemo(() => meta.data?.fields ?? [], [meta.data]);
  const byKey = useMemo(() => new Map(fields.map((f) => [f.key, f])), [fields]);
  const go = (cs: Cond[], m: "all" | "any", s: typeof sort) =>
    run.mutate({
      conditions: cs.map(toApi),
      match: m,
      sort: s?.key,
      descending: s?.desc,
    });

  const pick = (p: ScreenerMeta["presets"][number]) => {
    const cs = p.conditions.map(toCond),
      s = { key: p.sort, desc: p.descending };
    setActive(p.id);
    setConds(cs);
    setMatch("all");
    setSort(s);
    go(cs, "all", s);
  };
  const sortBy = (key: string) => {
    const s = { key, desc: sort?.key === key ? !sort.desc : true };
    setSort(s);
    go(conds, match, s);
  };
  const edit = (i: number, patch: Partial<Cond>) =>
    setConds(conds.map((c, j) => (j === i ? { ...c, ...patch } : c)));

  const cols = useMemo(() => {
    const keys = [
      ...BASE_COLS,
      ...conds.map((c) => c.field),
      ...(sort ? [sort.key] : []),
    ];
    return [...new Set(keys)].filter((k) => byKey.has(k));
  }, [conds, sort, byKey]);
  const used = [...conds.map((c) => c.field), ...(sort ? [sort.key] : [])];
  const canBacktest =
    conds.length > 0 &&
    used.every((k) => {
      const f = byKey.get(k);
      return ["technical", "fundamental"].includes(f?.kind ?? "") || (f?.kind === "score" && f.unit !== "text"); // the numeric swing-score fields have a point-in-time history
    });
  const asScreen = () => ({
    conditions: conds.map(toApi),
    match,
    sort: sort?.key ?? conds[0]?.field ?? "price",
    descending: sort?.desc ?? true,
  });
  const backtest = () => {
    const screen = asScreen();
    router.push(
      `/research/studies/new?screen=${encodeURIComponent(JSON.stringify(screen))}`,
    );
  };
  const presets = (meta.data?.presets ?? []).filter(
    (p) => cat === "all" || p.category === cat,
  );
  const err =
    run.error instanceof ApiError
      ? run.error.message
      : run.error
        ? "Could not run the screen."
        : null;

  return (
    <>
      <PageHeader
        title="Stock screener"
        subtitle="Filter listed stocks on fundamentals (from filed results) and technicals (from daily prices). Screens are rules of thumb for finding candidates to research, not advice."
      />
      <div className="space-y-6">
        <Panel title="Ready-made screens">
          <div className="p-5">
            <Tabs<Cat>
              label="Screen type"
              value={cat}
              onChange={setCat}
              tabs={[
                { key: "all", label: "All" },
                { key: "fundamental", label: "Fundamental" },
                { key: "technical", label: "Technical" },
                { key: "combined", label: "Combined" },
                { key: "smart_money", label: "Smart money" },
                { key: "score", label: "Scores" },
              ]}
            />
            {meta.isLoading ? (
              <Skeleton className="mt-4 h-24" />
            ) : (
              <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {presets.map((p) => (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => pick(p)}
                    aria-pressed={active === p.id}
                    className={`rounded-lg border p-3 text-left transition-colors hover:border-brand ${active === p.id ? "border-brand bg-brand-soft" : "border-line"}`}
                  >
                    <span className="block text-sm font-semibold">
                      {p.name}
                    </span>
                    <span className="mt-1 block text-xs text-ink-soft">
                      {p.description}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>
        </Panel>

        {saving ? (
          <SaveScreenDialog screen={asScreen()} onClose={() => setSaving(false)} />
        ) : null}
        <Panel title="Your conditions">
          <div className="p-5">
            <div className="space-y-2">
              {conds.map((c, i) => {
                const f = byKey.get(c.field);
                const text = f?.unit === "text";
                return (
                  <div key={i} className="flex flex-wrap items-center gap-2">
                    <select
                      aria-label="Field"
                      className={inputClass}
                      value={c.field}
                      onChange={(e) =>
                        edit(i, {
                          field: e.target.value,
                          op:
                            byKey.get(e.target.value)?.unit === "text"
                              ? "eq"
                              : c.op === "in"
                                ? "gt"
                                : c.op,
                        })
                      }
                    >
                      {["fundamental", "technical", "smart_money", "score", "market", "profile"].map((k) => (
                        <optgroup key={k} label={k === "smart_money" ? "smart money (latest filings, not for backtests)" : k === "score" ? "swing score (the numeric fields can be backtested)" : k === "market" ? "market zone (can be backtested)" : k}>
                          {fields
                            .filter((x) => (x.group === "market" ? "market" : x.kind) === k)
                            .map((x) => (
                              <option key={x.key} value={x.key}>
                                {x.label}
                              </option>
                            ))}
                        </optgroup>
                      ))}
                    </select>
                    <select
                      aria-label="Operator"
                      className={inputClass}
                      value={c.op}
                      onChange={(e) => edit(i, { op: e.target.value })}
                    >
                      {(text ? ["eq", "ne"] : Object.keys(OPS)).map((o) => (
                        <option key={o} value={o}>
                          {OPS[o]}
                        </option>
                      ))}
                    </select>
                    <input
                      aria-label="Value"
                      className={`${inputClass} w-28`}
                      value={c.lo}
                      placeholder={
                        text ? "large / mid / small / micro" : "value"
                      }
                      onChange={(e) => edit(i, { lo: e.target.value })}
                    />
                    {c.op === "between" ? (
                      <input
                        aria-label="Upper value"
                        className={`${inputClass} w-28`}
                        value={c.hi}
                        placeholder="and"
                        onChange={(e) => edit(i, { hi: e.target.value })}
                      />
                    ) : null}
                    <button
                      type="button"
                      className={buttonClass("ghost", true)}
                      onClick={() => setConds(conds.filter((_, j) => j !== i))}
                    >
                      Remove
                    </button>
                  </div>
                );
              })}
              {conds.length === 0 ? (
                <p className="text-sm text-ink-soft">
                  Pick a ready-made screen above, or add your own conditions.
                </p>
              ) : null}
            </div>
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <button
                type="button"
                className={buttonClass("secondary")}
                disabled={!fields.length}
                onClick={() => {
                  setActive(null);
                  setConds([
                    ...conds,
                    { field: "pe", op: "lte", lo: "20", hi: "" },
                  ]);
                }}
              >
                Add condition
              </button>
              <label className="text-sm text-ink-soft">
                Match{" "}
                <select
                  className={inputClass}
                  value={match}
                  onChange={(e) => setMatch(e.target.value as "all" | "any")}
                >
                  <option value="all">all conditions</option>
                  <option value="any">any condition</option>
                </select>
              </label>
              <button
                type="button"
                className={buttonClass("primary")}
                disabled={!conds.length || run.isPending}
                onClick={() => go(conds, match, sort)}
              >
                {run.isPending ? "Running…" : "Run screen"}
              </button>
              <button
                type="button"
                className={buttonClass("secondary")}
                disabled={!canBacktest}
                onClick={backtest}
              >
                Backtest as a strategy
              </button>
              <button
                type="button"
                className={buttonClass("secondary")}
                disabled={!canBacktest}
                onClick={() => setSaving(true)}
              >
                Save as a strategy
              </button>
            </div>
            {conds.length > 0 && !canBacktest ? (
              <p className="mt-2 text-xs text-ink-soft">
                A market-cap class or a view against its sector cannot be a condition here: a study or a saved strategy picks its market-cap segments separately.
              </p>
            ) : null}
          </div>
        </Panel>

        {run.isPending ? (
          <Panel>
            <div
              className="flex items-center gap-3 p-5 text-sm text-ink-soft"
              role="status"
            >
              <span
                className="h-4 w-4 animate-spin rounded-full border-2 border-line border-t-brand"
                aria-hidden
              />
              Running screen across all listed stocks…
            </div>
            <Skeleton className="mx-5 mb-5 h-40" />
          </Panel>
        ) : null}

        {err ? <Alert tone="error">{err}</Alert> : null}
        {run.data && !run.isPending ? (
          <Panel
            title={`${run.data.total} stock${run.data.total === 1 ? "" : "s"} match${run.data.rows.length < run.data.total ? ` (showing ${run.data.rows.length})` : ""}`}
          >
            {run.data.rows.length === 0 ? (
              <EmptyState title="Nothing matches">
                Loosen a condition. A stock with no figure for a field never
                matches a condition on it.
              </EmptyState>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <caption className="sr-only">Screen results</caption>
                  <thead>
                    <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-soft">
                      <th scope="col" className="px-5 py-2 font-medium">
                        Stock
                      </th>
                      {cols.map((k) => (
                        <th
                          key={k}
                          scope="col"
                          className="px-5 py-2 text-right font-medium"
                          aria-sort={
                            sort?.key === k
                              ? sort.desc
                                ? "descending"
                                : "ascending"
                              : undefined
                          }
                        >
                          <button
                            type="button"
                            onClick={() => sortBy(k)}
                            className="uppercase hover:text-ink"
                          >
                            {byKey.get(k)?.label}
                            {sort?.key === k ? (sort.desc ? " ↓" : " ↑") : ""}
                          </button>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line">
                    {run.data.rows.map((r) => (
                      <tr
                        key={String(r.instrument_id)}
                        className="hover:bg-slate-50"
                      >
                        <td className="px-5 py-2">
                          <Link
                            href={`/data/instruments?id=${r.instrument_id}`}
                            className="font-medium text-brand hover:underline"
                          >
                            {r.symbol}
                          </Link>
                          <span className="block max-w-56 truncate text-xs text-ink-soft">
                            {r.name}
                          </span>
                        </td>
                        {cols.map((k) => (
                          <td
                            key={k}
                            className="px-5 py-2 text-right tabular-nums"
                          >
                            {fmt(r[k], byKey.get(k)?.unit ?? "x")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        ) : null}
      </div>
    </>
  );
}
