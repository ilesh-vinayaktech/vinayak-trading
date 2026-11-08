"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { LineChart } from "@/components/charts/LineChart";
import { Badge, Flag, findingStatusTone, severityTone } from "@/components/status/Badge";
import { Card, ErrorBox, Loading, Stat } from "@/components/status/LoadState";
import { api } from "@/lib/api/client";
import { fmtDateTime, fmtInt, humanize, shortHash } from "@/lib/formatting";

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
                  <td className="px-2">{u ? <Flag value={u.DAILY_RESEARCH?.eligible ?? false} yes="eligible" no="blocked" /> : <Badge>unknown</Badge>}</td>
                  <td className="px-2">{u ? <Flag value={u.INTRADAY_RESEARCH?.eligible ?? false} yes="eligible" no="blocked" /> : <Badge>unknown</Badge>}</td>
                  <td className="px-2">{u ? <Flag value={u.BENCHMARK_GATE?.eligible ?? false} yes="eligible" no="not eligible" /> : <Badge>unknown</Badge>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function Detail({ id }: { id: number }) {
  const d = useQuery({ queryKey: ["benchmark", id], queryFn: () => api.benchmark(id) });
  const lv = useQuery({ queryKey: ["levels", id], queryFn: () => api.benchmarkLevels(id) });
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

      <Card title="Levels" note="Down-sampled by the API for display; the full series is in the database.">
        {lv.isLoading ? <Loading what="levels" /> : lv.error || !lv.data ? <ErrorBox error={lv.error} what="levels" /> : <LineChart points={lv.data.levels} />}
      </Card>

      {Object.entries(uses).some(([, v]) => v.blockers.length > 0) ? (
        <Card title="What blocks each use">
          {Object.entries(uses).map(([k, v]) =>
            v.blockers.length > 0 ? (
              <div key={k} className="mb-3">
                <div className="text-sm font-medium">{humanize(k)}</div>
                <ul className="ml-5 list-disc text-sm text-ink-soft">
                  {v.blockers.map((x) => (
                    <li key={x}>{x}</li>
                  ))}
                </ul>
              </div>
            ) : null,
          )}
        </Card>
      ) : null}

      <Card title="Findings that apply">
        <ul className="divide-y divide-line">
          {b.findings.map((f) => (
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
          {b.findings.length === 0 ? <li className="py-2 text-sm text-ink-soft">No findings recorded for this benchmark.</li> : null}
        </ul>
      </Card>

      <Card title="Validation history">
        <ul className="divide-y divide-line">
          {b.validations.map((v) => (
            <li key={v.validation_id} className="py-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs">#{v.validation_id}</span>
                <span className="text-ink-soft">{fmtDateTime(v.created_at)}</span>
                <Badge tone={v.technical_validation_passed ? "good" : "bad"}>technical {v.technical_validation_passed ? "passed" : "not passed"}</Badge>
                <Badge tone={v.covers_current_dataset ? "good" : "warn"}>{v.covers_current_dataset ? "covers current data" : "stale: data changed"}</Badge>
                <Badge tone="neutral">report v{v.report_version}</Badge>
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
          <div className="space-y-2 text-sm">
            <p className="text-ink-soft">{b.session_calendar.historical_session_hours}</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(b.session_calendar.outcome_counts_all_series).map(([k, v]) => (
                <Badge key={k} tone={k.includes("PROVISIONAL") ? "warn" : "neutral"}>
                  {humanize(k)}: {fmtInt(v)}
                </Badge>
              ))}
            </div>
            <p className="text-xs text-ink-faint">Counts cover all four series. Instrument-level blocked dates: {b.instrument_level_blocked_dates.join(", ") || "none"}.</p>
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
      <div>
        <h1 className="text-xl font-semibold">Benchmark Explorer</h1>
        <p className="text-sm text-ink-soft">Eligibility, findings and validation history come from the frozen release; the browser calculates nothing.</p>
      </div>
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
