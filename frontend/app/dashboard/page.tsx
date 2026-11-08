"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { Badge, Flag } from "@/components/status/Badge";
import { Card, ErrorBox, Loading, Stat } from "@/components/status/LoadState";
import { api } from "@/lib/api/client";
import { fmtDateTime, fmtInt, humanize } from "@/lib/formatting";

/** How old the newest bar is, as a plain calendar-day difference (display only). */
function FreshnessBadge({ lastDate }: { lastDate: string }) {
  const days = Math.floor((Date.now() - new Date(`${lastDate}T00:00:00Z`).getTime()) / 86_400_000);
  const tone = days <= 4 ? "good" : days <= 10 ? "warn" : "bad";
  return <Badge tone={tone}>newest bar {lastDate} ({days <= 0 ? "today" : `${days} day${days === 1 ? "" : "s"} old`})</Badge>;
}

export default function DashboardPage() {
  const { data: d, error, isLoading } = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard });
  if (isLoading) return <Loading what="dashboard" />;
  if (error || !d) return <ErrorBox error={error} what="the dashboard" />;

  const bars = d.data;
  const barsNote =
    bars.bars_on_previous_date !== null
      ? `${fmtInt(bars.bars_on_last_date)} bars on the last date, ${fmtInt(bars.bars_on_previous_date)} the day before`
      : undefined;
  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        subtitle="Ingested, technically validated, research-eligible and gate-eligible are four different things; they are shown separately below."
        actions={bars.last_date ? <FreshnessBadge lastDate={bars.last_date} /> : null}
      />

      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Platform status" note={d.platform.reason}>
          <Badge tone="neutral">{d.platform.state}</Badge>
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
            <Badge tone="neutral">redis {d.system.redis}</Badge>
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
                    <Flag value={s.research_eligible_daily} yes="eligible" no="blocked" />
                  </td>
                  <td className="px-2">
                    <Flag value={s.research_eligible_intraday} yes="eligible" no="blocked" />
                  </td>
                  <td className="px-2">
                    <Flag value={s.benchmark_gate_eligible} yes="eligible" no="not eligible" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Corporate actions" note="Review items are not applied to prices until resolved.">
          <div className="flex flex-wrap gap-2">
            {Object.entries(d.corporate_actions.actions_by_status).map(([k, v]) => (
              <Badge key={k} tone={k === "ok" ? "good" : "warn"}>
                {k === "ok" ? "verified" : humanize(k)}: {fmtInt(v)}
              </Badge>
            ))}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {Object.entries(d.corporate_actions.resolutions_by_status).map(([k, v]) => (
              <Badge key={k} tone={k === "provisional" ? "warn" : "neutral"}>
                resolution {humanize(k)}: {v}
              </Badge>
            ))}
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
          <Badge tone="neutral">{d.strategies.persisted ? "persisted" : "not persisted yet"}</Badge>
        </Card>
      </div>
    </div>
  );
}
