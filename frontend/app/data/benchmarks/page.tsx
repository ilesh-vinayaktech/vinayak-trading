"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, Eligibility, findingStatusTone, severityTone } from "@/components/status/Badge";
import { StateChip } from "@/components/status/StateChip";
import { Card, ErrorBox, Loading, Stat } from "@/components/status/LoadState";
import { api } from "@/lib/api/client";
import { fmtDateTime, fmtInt, humanize, shortHash } from "@/lib/formatting";
import type { Finding, Outcome } from "@/lib/schemas";

function List() {
  const { data, error, isLoading } = useQuery({ queryKey: ["benchmarks"], queryFn: api.benchmarks });
  if (isLoading) return <Loading what="benchmarks" />;
  if (error || !data) return <ErrorBox error={error} what="benchmarks" />;
  return (
    <Card title={`Benchmarks - release ${data.release ?? "none"}`} note={`Benchmark gate: ${data.gate}. Daily research eligibility is not benchmark-gate eligibility.`}>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line text-xs text-ink-soft">
            <tr>
              <th className="py-2 pr-2">Benchmark</th>
              <th className="px-2">Coverage</th>
              <th className="px-2">Daily research</th>
              <th className="px-2">Intraday research</th>
              <th className="px-2">Gate</th>
            </tr>
          </thead>
          <tbody>
            {data.benchmarks.map((b) => {
              const u = b.eligibility?.uses;
              return (
                <tr key={b.id} className="border-b border-line last:border-0">
                  <td className="py-2 pr-2">
                    <Link className="underline" href={`/data/benchmarks?id=${b.id}`}>
                      {b.name}
                    </Link>
                    <div className="text-xs text-ink-faint">{humanize(b.return_type)}</div>
                  </td>
                  <td className="px-2 text-xs text-ink-soft">
                    {b.first} to {b.last}
                    <div>{fmtInt(b.observations)} observations</div>
                  </td>
                  <td className="px-2">{u ? <Eligibility eligible={u.DAILY_RESEARCH?.eligible ?? false} /> : <StateChip state="UNKNOWN" />}</td>
                  <td className="px-2">{u ? <Eligibility eligible={u.INTRADAY_RESEARCH?.eligible ?? false} /> : <StateChip state="UNKNOWN" />}</td>
                  <td className="px-2">{u ? <Eligibility eligible={u.BENCHMARK_GATE?.eligible ?? false} no="not eligible" /> : <StateChip state="UNKNOWN" />}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

const SEVERITY_ORDER: Record<string, number> = { HIGH: 0, MEDIUM: 1, LOW: 2, INFO: 3 };

/** Open problems first, then the most severe; resolved items sink to the bottom. */
function sortFindings(fs: Finding[]): Finding[] {
  const rank = (f: Finding) => (f.status === "UNRESOLVED" ? 0 : f.status === "RESOLVED" ? 2 : 1);
  return [...fs].sort((a, b) => rank(a) - rank(b) || (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9) || a.id.localeCompare(b.id));
}

const RANGES = [
  { key: "1Y", years: 1 },
  { key: "3Y", years: 3 },
  { key: "5Y", years: 5 },
  { key: "10Y", years: 10 },
  { key: "All", years: 0 },
] as const;

/** First date of a "last N years" window (a request parameter only; the API does the selecting). */
function windowStart(last: string, years: number): string | undefined {
  if (years === 0) return undefined;
  const d = new Date(`${last}T00:00:00Z`);
  d.setUTCFullYear(d.getUTCFullYear() - years);
  return d.toISOString().slice(0, 10);
}

function Existence({ value }: { value: string | null }) {
  const tone = value === "CONFIRMED" ? "good" : value === "PROVISIONAL" || value === "UNCONFIRMED" ? "warn" : "neutral";
  return <Badge tone={tone}>{value ? value.toLowerCase().replace(/_/g, " ") : "-"}</Badge>;
}

function OutcomeTable({ rows, caption }: { rows: Outcome[]; caption: string }) {
  const withProps = rows.some((r) => r.existence !== null);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <caption className="pb-1 text-left text-xs font-medium text-ink-soft">{caption}</caption>
        <thead className="border-b border-line text-xs text-ink-soft">
          <tr>
            <th className="py-1 pr-2">What the audit found</th>
            <th className="px-2 text-right">Dates</th>
            {withProps ? (
              <>
                <th className="px-2">Existence</th>
                <th className="px-2">Kind</th>
                <th className="px-2">Hours</th>
              </>
            ) : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.code} className="border-b border-line last:border-0">
              <td className="py-1 pr-2">{r.label}</td>
              <td className="px-2 text-right tabular-nums">{fmtInt(r.count)}</td>
              {withProps ? (
                <>
                  <td className="px-2"><Existence value={r.existence} /></td>
                  <td className="px-2"><Existence value={r.kind} /></td>
                  <td className="px-2"><Existence value={r.hours} /></td>
                </>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function reportLabel(v: string): string {
  return v.startsWith("legacy") ? "legacy report format" : `report v${v}`;
}

function FindingList({ items }: { items: Finding[] }) {
  return (
    <ul className="divide-y divide-line">
      {sortFindings(items).map((f) => (
        <li key={f.id} className="py-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs">{f.id}</span>
            <Badge tone={severityTone(f.severity)}>{f.severity}</Badge>
            <Badge tone={findingStatusTone(f.status)}>{humanize(f.status)}</Badge>
            <span className="text-sm font-medium">{f.title}</span>
          </div>
          <p className="mt-1 text-sm text-ink-soft">{f.detail}</p>
        </li>
      ))}
    </ul>
  );
}

/** Active blockers first, then decisions already taken, then closed items. */
function Findings({ findings }: { findings: Finding[] }) {
  const active = findings.filter((f) => f.status === "UNRESOLVED");
  const resolved = findings.filter((f) => f.status === "RESOLVED");
  const accepted = findings.filter((f) => f.status !== "UNRESOLVED" && f.status !== "RESOLVED");
  return (
    <>
      <Card title={`Active findings (${active.length})`} note="Unresolved: these are the current limits on how this benchmark may be used.">
        {active.length ? <FindingList items={active} /> : <p className="text-sm text-ink-soft">No active findings.</p>}
      </Card>
      {accepted.length ? (
        <Card title={`Accepted findings (${accepted.length})`} note="Accepted with evidence: explained, not numerically reconciled. The check itself still fails.">
          <FindingList items={accepted} />
        </Card>
      ) : null}
      {resolved.length ? (
        <Card title={`Resolved findings (${resolved.length})`}>
          <FindingList items={resolved} />
        </Card>
      ) : null}
    </>
  );
}

function Detail({ id }: { id: number }) {
  const [range, setRange] = useState<(typeof RANGES)[number]["key"]>("All");
  const d = useQuery({ queryKey: ["benchmark", id], queryFn: () => api.benchmark(id) });
  const years = RANGES.find((r) => r.key === range)?.years ?? 0;
  const last = d.data?.last ?? null;
  const lv = useQuery({
    queryKey: ["levels", id, range, last],
    queryFn: () => api.benchmarkLevels(id, last ? windowStart(last, years) : undefined),
    enabled: last !== null,
    placeholderData: (prev) => prev,
  });
  if (d.isLoading) return <Loading what="benchmark" />;
  if (d.error || !d.data) return <ErrorBox error={d.error} what="the benchmark" />;
  const b = d.data;
  const uses = b.eligibility?.uses ?? {};
  const open = b.findings.filter((f) => f.status === "UNRESOLVED");
  return (
    <div className="space-y-4">
      <Link href="/data/benchmarks" className="text-sm underline">
        All benchmarks
      </Link>
      <Card title={b.name}>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Stat label="Coverage" value={`${b.first} to ${b.last}`} hint={`${fmtInt(b.observations)} observations`} />
          <Stat label="Dataset hash" value={<code className="text-sm">{shortHash(b.dataset_hash, 16)}</code>} />
          <Stat label="Release" value={b.release ?? "none"} />
          <Stat label="Methodology" value={<span className="text-sm">{b.methodology_version}</span>} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Badge tone="neutral">state: {b.eligibility ? humanize(b.eligibility.state) : "unknown (no release artifacts)"}</Badge>
          {Object.entries(uses).map(([k, v]) => (
            <Badge key={k} tone={v.eligible ? "good" : "neutral"}>
              {humanize(k)}: {v.eligible ? "eligible" : "blocked"}
            </Badge>
          ))}
          <Badge tone="neutral">gate {b.gate}</Badge>
        </div>
        {open.length > 0 ? (
          <p className="mt-3 text-sm text-amber-800">
            {open.length} unresolved finding{open.length === 1 ? "" : "s"} apply. This benchmark must not be read as fully validated.
          </p>
        ) : null}
      </Card>

      <Card title="Levels">
        <div className="mb-3 flex flex-wrap items-center gap-2" role="group" aria-label="Date range">
          {RANGES.map((r) => (
            <button key={r.key} type="button" aria-pressed={range === r.key} onClick={() => setRange(r.key)} className={`rounded px-3 py-1 text-xs ${range === r.key ? "bg-slate-900 text-white" : "bg-slate-100 text-ink-soft hover:bg-slate-200"}`}>
              {r.key}
            </button>
          ))}
          {lv.data ? (
            <span className="ml-auto text-xs text-ink-soft" data-testid="sampling-note">
              {lv.data.downsampled
                ? `Showing ${fmtInt(lv.data.returned)} of ${fmtInt(lv.data.total_observations)} observations: down-sampled, every peak and trough kept. Pick a shorter range to see every observation.`
                : `Showing all ${fmtInt(lv.data.total_observations)} observations in this range.`}
            </span>
          ) : null}
        </div>
        {lv.isLoading ? <Loading what="levels" /> : lv.error || !lv.data ? <ErrorBox error={lv.error} what="levels" /> : <LineChart points={lv.data.levels} />}
      </Card>

      {Object.entries(uses).some(([, v]) => v.blockers.length > 0) ? (
        <Card title="What blocks each use" note="Any unresolved finding blocks the benchmark gate; only the named ones block research.">
          {Object.entries(uses).map(([k, v]) =>
            v.blockers.length > 0 ? (
              <details key={k} className="mb-2 rounded-md border border-line p-3" open={k !== "BENCHMARK_GATE"}>
                <summary className="cursor-pointer text-sm font-medium">
                  {humanize(k)} <span className="font-normal text-ink-soft">({v.blockers.length} blocker{v.blockers.length === 1 ? "" : "s"})</span>
                </summary>
                <ul className="ml-5 mt-2 list-disc text-sm text-ink-soft">
                  {v.blockers.map((x) => (
                    <li key={x}>{x}</li>
                  ))}
                </ul>
              </details>
            ) : null,
          )}
        </Card>
      ) : null}

      <Findings findings={b.findings} />

      <Card title="Validation history">
        <ul className="divide-y divide-line">
          {b.validations.map((v) => (
            <li key={v.validation_id} className="py-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs">#{v.validation_id}</span>
                <span className="text-ink-soft">{fmtDateTime(v.created_at)}</span>
                <Badge tone={v.technical_validation_passed ? "good" : "bad"}>technical {v.technical_validation_passed ? "passed" : "not passed"}</Badge>
                <Badge tone={v.covers_current_dataset ? "good" : "warn"}>{v.covers_current_dataset ? "covers current data" : "stale: data changed"}</Badge>
                <Badge tone="neutral">{reportLabel(v.report_version)}</Badge>
              </div>
              {v.owner_accepted_findings.length > 0 ? (
                <p className="mt-1 text-xs text-ink-soft">
                  Accepted or unresolved checks: {v.owner_accepted_findings.map((a) => `${a.check} (${humanize(a.state)}: ${a.label})`).join("; ")}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </Card>

      <Card title="Session-calendar dependencies">
        {b.session_calendar ? (
          <div className="space-y-4 text-sm">
            <p className="text-ink-soft">{b.session_calendar.historical_session_hours}</p>
            {b.session_calendar.listed_special_sessions ? (
              <div>
                <div className="mb-1 text-xs font-medium text-ink-soft">
                  The {b.session_calendar.listed_special_sessions.listed_sessions} listed special sessions: what is established
                </div>
                <table className="text-left text-sm">
                  <tbody>
                    <tr className="border-b border-line">
                      <th className="py-1 pr-6 font-medium">Session existence</th>
                      <td><Existence value="CONFIRMED" /> <span className="text-xs text-ink-soft">by an exchange file (no benchmark-only sessions remain)</span></td>
                    </tr>
                    {(
                      [
                        ["Session kind", b.session_calendar.listed_special_sessions.kind],
                        ["Opening time", b.session_calendar.listed_special_sessions.opening_time],
                        ["Closing time", b.session_calendar.listed_special_sessions.closing_time],
                      ] as const
                    ).map(([label, counts]) => (
                      <tr key={label} className="border-b border-line last:border-0">
                        <th className="py-1 pr-6 font-medium">{label}</th>
                        <td className="flex flex-wrap gap-2 py-1">
                          {Object.entries(counts).map(([k, n]) => (
                            <Badge key={k} tone={k === "CONFIRMED" || k === "VERIFIED" ? "good" : "warn"}>
                              {k.toLowerCase()}: {fmtInt(n)}
                            </Badge>
                          ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
            {b.session_calendar.this_series ? (
              <div className="grid gap-4 lg:grid-cols-2">
                <OutcomeTable rows={b.session_calendar.this_series.observed} caption="Dates this series has a value on" />
                <OutcomeTable rows={b.session_calendar.this_series.missing} caption="Dates inside its coverage with no value" />
              </div>
            ) : (
              <p className="text-ink-soft">No per-series calendar evidence for this benchmark.</p>
            )}
            <p className="text-xs text-ink-faint">
              All four series together: {b.session_calendar.all_series.map((r) => `${r.label}: ${fmtInt(r.count)}`).join("; ")}. Instrument-level blocked dates:{" "}
              {b.instrument_level_blocked_dates.join(", ") || "none"}.
            </p>
          </div>
        ) : (
          <p className="text-sm text-ink-soft">No calendar evidence loaded.</p>
        )}
      </Card>
    </div>
  );
}

function Page() {
  const raw = useSearchParams().get("id");
  const id = raw !== null && /^\d+$/.test(raw) ? Number(raw) : null;
  return (
    <div className="space-y-6">
      <PageHeader title="Benchmark Explorer" subtitle="Eligibility, findings and validation history come from the frozen release; the browser calculates nothing." />
      {id === null ? <List /> : <Detail id={id} />}
    </div>
  );
}

export default function BenchmarksPage() {
  return (
    <Suspense fallback={<Loading what="benchmarks" />}>
      <Page />
    </Suspense>
  );
}
