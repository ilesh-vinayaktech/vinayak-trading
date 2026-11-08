"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, Eligibility, Flag } from "@/components/status/Badge";
import { StateChip } from "@/components/status/StateChip";
import { Card, ErrorBox, Loading, Stat } from "@/components/status/LoadState";
import { api } from "@/lib/api/client";
import { fmtDateTime, fmtInt, humanize } from "@/lib/formatting";
import type { Dashboard } from "@/lib/schemas";

type Freshness = NonNullable<Dashboard["data"]["freshness"]>;

/** Freshness is judged by exchange sessions (computed by the API), never by calendar-day subtraction. */
function FreshnessPanel({ f }: { f: Freshness }) {
  const fmt = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", weekday: "short", timeZone: "UTC" });
  return (
    <div className="rounded-md border border-line bg-panel px-3 py-2 text-xs" data-testid="freshness">
      <div className="flex items-center gap-2">
        <Badge tone={f.status === "CURRENT" ? "good" : "bad"}>data {f.status === "CURRENT" ? "current" : `${f.sessions_behind} session${f.sessions_behind === 1 ? "" : "s"} behind`}</Badge>
      </div>
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-ink-soft">
        <dt>Latest bar session</dt>
        <dd className="text-ink">{fmt(f.latest_bar_session)}</dd>
        <dt>Latest expected session</dt>
        <dd className="text-ink">{fmt(f.expected_latest_session)}</dd>
        <dt>Next session</dt>
        <dd className="text-ink">{fmt(f.next_session)}</dd>
      </dl>
      <p className="mt-1 max-w-xs text-ink-faint">{f.basis}</p>
    </div>
  );
}

export default function DashboardPage() {
  const { data: d, error, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });
  if (isLoading) return <Loading what="dashboard" />;
  if (error || !d) return <ErrorBox error={error} what="the dashboard" />;

  const bars = d.data;
  const ca = d.corporate_actions;
  const barsNote =
    bars.bars_on_previous_date !== null
      ? `${fmtInt(bars.bars_on_last_date)} bars on the last date, ${fmtInt(bars.bars_on_previous_date)} the day before`
      : undefined;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        subtitle="Ingested, technically validated, research-eligible and gate-eligible are four different things; they are shown separately below."
        actions={bars.freshness ? <FreshnessPanel f={bars.freshness} /> : null}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Platform status" note={d.platform.reason}>
          <StateChip state="UNKNOWN" text={d.platform.state.toLowerCase()} />
        </Card>
        <Card title="Data health" note={barsNote}>
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Latest date" value={bars.last_date ?? "none"} hint={`from ${bars.first_date ?? "-"}`} />
            <Stat label="Bars" value={fmtInt(bars.bars)} hint={`${fmtInt(bars.instruments_with_bars)} instruments`} />
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(bars.partitions).map(([k, v]) => (
              <Badge key={k} tone={k === "loaded" ? "good" : "neutral"}>
                {humanize(k)}: {fmtInt(v)}
              </Badge>
            ))}
            <Badge tone={bars.quarantined_partitions.length ? "bad" : "good"}>
              quarantined: {bars.quarantined_partitions.length}
            </Badge>
          </div>
        </Card>
        <Card title="System health">
          <div className="flex flex-wrap gap-2">
            <Badge tone={d.system.api === "ok" ? "good" : "bad"}>API {d.system.api}</Badge>
            <Badge tone={d.system.database === "ok" ? "good" : "bad"}>database {d.system.database}</Badge>
            <StateChip state="NOT_CONFIGURED" text="redis not configured" />
          </div>
          <p className="mt-3 text-xs text-ink-faint">
            Last ingestion event: {d.system.recent_ingestion[0] ? fmtDateTime(d.system.recent_ingestion[0].at) : "none"}
          </p>
        </Card>
      </div>

      <Card
        title={`Benchmarks (release ${d.benchmarks.release ?? "none"})`}
        note={`Benchmark gate: ${d.benchmarks.gate}. "Eligible for research" is not "eligible for benchmark validation".`}
      >
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-xs text-ink-soft">
              <tr>
                <th className="py-2 pr-2">Series</th>
                <th className="px-2">Ingested</th>
                <th className="px-2">Technically validated</th>
                <th className="px-2">Daily research</th>
                <th className="px-2">Intraday research</th>
                <th className="px-2">Gate</th>
              </tr>
            </thead>
            <tbody>
              {d.benchmarks.series.map((s) => (
                <tr key={s.id} className="border-b border-line last:border-0">
                  <td className="py-2 pr-2">
                    <Link className="underline" href={`/data/benchmarks?id=${s.id}`}>
                      {s.name}
                    </Link>
                  </td>
                  <td className="px-2">
                    <Flag value={s.ingested} yes="yes" no="no" />
                  </td>
                  <td className="px-2">
                    <Flag value={s.technically_validated} yes="yes" no="no (see findings)" />
                  </td>
                  <td className="px-2">
                    <Eligibility eligible={s.research_eligible_daily} />
                  </td>
                  <td className="px-2">
                    <Eligibility eligible={s.research_eligible_intraday} />
                  </td>
                  <td className="px-2">
                    <Eligibility eligible={s.benchmark_gate_eligible} no="not eligible" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Corporate actions" note="Pending review and provisional adjustments can change research prices; verified ones are applied.">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Total events" value={fmtInt(ca.total_events)} />
            <Stat label="Verified" value={fmtInt(ca.verified)} hint="applied to prices" />
          </div>
          <div className="mt-3 space-y-2">
            <div className="flex items-center justify-between rounded-md border border-amber-300 bg-amber-50 px-3 py-2">
              <span className="text-sm font-medium text-amber-900">Pending review</span>
              <span className="text-lg font-semibold tabular-nums text-amber-900" data-testid="pending-review">{fmtInt(ca.pending_review)}</span>
            </div>
            <div className="flex items-center justify-between rounded-md border border-amber-300 bg-amber-50 px-3 py-2">
              <span className="text-sm font-medium text-amber-900">Provisional adjustments</span>
              <span className="text-lg font-semibold tabular-nums text-amber-900" data-testid="provisional">{fmtInt(ca.provisional_adjustments)}</span>
            </div>
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge tone="neutral">no adjustment (verified): {fmtInt(ca.no_adjustment_verified)}</Badge>
              <Badge tone="neutral">ignored with reason: {fmtInt(ca.ignored_with_reason)}</Badge>
              <Badge tone={ca.review_without_any_resolution ? "warn" : "good"}>review with no decision yet: {fmtInt(ca.review_without_any_resolution)}</Badge>
            </div>
          </div>
        </Card>
        <Card title="Research">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Backtests" value={d.research.backtests} />
            <Stat label="Experiments" value={d.research.experiments} />
            <Stat label="Validation reports" value={d.research.validation_reports} hint={`${d.research.validation_reports_passed} passed`} />
            <Stat label="Latest run" value={d.research.latest_run ? `#${d.research.latest_run.run_id}` : "none"} />
          </div>
        </Card>
        <Card title="Strategies" note={d.strategies.note}>
          {d.strategies.persisted ? <Badge tone="good">persisted</Badge> : <StateChip state="NOT_IMPLEMENTED" text="not persisted yet" />}
        </Card>
      </div>
    </div>
  );
}
