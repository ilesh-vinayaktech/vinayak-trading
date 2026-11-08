import { z } from "zod";

// Response schemas for the read-only research API. Prices and levels stay strings: the UI shows
// what the backend returned and never recomputes adjustments, eligibility or metrics.

export const healthSchema = z.object({ api: z.string(), database: z.string(), redis: z.string() });

const ingestionRow = z.object({
  id: z.number(),
  source: z.string(),
  dataset: z.string(),
  partition: z.string(),
  status: z.string(),
  at: z.string(),
  current_status: z.string(),
  superseded: z.boolean(),
});

const page = <T extends z.ZodTypeAny>(item: T) =>
  z.object({ items: z.array(item), total: z.number(), limit: z.number(), offset: z.number() });

export const seriesStatusSchema = z.object({
  id: z.number(),
  name: z.string(),
  return_type: z.string(),
  ingested: z.boolean(),
  technically_validated: z.boolean(),
  research_eligible_daily: z.boolean(),
  research_eligible_intraday: z.boolean(),
  benchmark_gate_eligible: z.boolean(),
  eligibility_state: z.string(),
});

export const dashboardSchema = z.object({
  platform: z.object({ state: z.string(), reason: z.string() }),
  data: z.object({
    bars: z.number(),
    instruments_with_bars: z.number(),
    first_date: z.string().nullable(),
    last_date: z.string().nullable(),
    bars_on_last_date: z.number(),
    bars_on_previous_date: z.number().nullable(),
    partitions: z.record(z.number()),
    quarantined_partitions: z.array(z.string()),
    instruments: z.record(z.number()),
    freshness: z
      .object({
        latest_bar_session: z.string(),
        expected_latest_session: z.string(),
        next_session: z.string(),
        sessions_behind: z.number(),
        status: z.enum(["CURRENT", "BEHIND"]),
        basis: z.string(),
      })
      .nullable(),
  }),
  benchmarks: z.object({
    release: z.string().nullable(),
    gate: z.string(),
    series: z.array(seriesStatusSchema),
  }),
  corporate_actions: z.object({
    actions_by_status: z.record(z.number()),
    resolutions_by_status: z.record(z.number()),
    total_events: z.number(),
    verified: z.number(),
    pending_review: z.number(),
    review_without_any_resolution: z.number(),
    provisional_adjustments: z.number(),
    no_adjustment_verified: z.number(),
    ignored_with_reason: z.number(),
  }),
  research: z.object({
    backtests: z.number(),
    experiments: z.number(),
    validation_reports: z.number(),
    validation_reports_passed: z.number(),
    latest_run: z
      .object({
        run_id: z.number(),
        strategy_id: z.string(),
        created_at: z.string(),
        accounting_complete: z.boolean(),
        ledger_reconciled: z.boolean(),
      })
      .nullable(),
  }),
  strategies: z.object({ persisted: z.boolean(), note: z.string() }),
  system: z.object({
    database: z.string(),
    redis: z.string(),
    api: z.string(),
    recent_ingestion: z.array(ingestionRow),
  }),
});

export const instrumentSchema = z.object({
  id: z.number(),
  symbol: z.string(),
  isin: z.string().nullable(),
  name: z.string().nullable(),
  status: z.string(),
  listed_on: z.string().nullable(),
  delisted_on: z.string().nullable(),
});

export const actionSchema = z.object({
  ex_date: z.string(),
  kind: z.string(),
  status: z.string(),
  num: z.string().nullable(),
  den: z.string().nullable(),
  amount: z.string().nullable(),
  subject: z.string().nullable(),
});

export const instrumentDetailSchema = instrumentSchema.extend({
  bars: z.object({ first: z.string().nullable(), last: z.string().nullable(), count: z.number() }),
  actions: z.array(actionSchema),
});

const eventRef = z.object({ kind: z.string(), ex_date: z.string() });

export const barsSchema = z.object({
  adjust: z.enum(["none", "split", "total_return"]),
  adjustment_version: z.string(),
  clean: z.boolean(),
  bars: z.array(
    z.object({
      date: z.string(),
      open: z.string(),
      high: z.string(),
      low: z.string(),
      close: z.string(),
      volume: z.string(),
      factor: z.string(),
    }),
  ),
  unapplied: z.array(eventRef),
  provisional: z.array(eventRef),
});

const uses = z.record(z.object({ eligible: z.boolean(), blockers: z.array(z.string()) }));

export const eligibilitySchema = z.object({
  series: z.string(),
  state: z.string(),
  uses,
  disclosed_check_findings: z.record(z.string()).optional(),
});

export const benchmarkSummarySchema = z.object({
  id: z.number(),
  name: z.string(),
  index_symbol: z.string(),
  return_type: z.string(),
  methodology_version: z.string(),
  first: z.string().nullable(),
  last: z.string().nullable(),
  observations: z.number(),
  dataset_hash: z.string(),
  eligibility: eligibilitySchema.nullable(),
});

export const benchmarkListSchema = z.object({
  release: z.string().nullable(),
  gate: z.string(),
  benchmarks: z.array(benchmarkSummarySchema),
});

export const findingSchema = z.object({
  id: z.string(),
  title: z.string(),
  severity: z.string(),
  status: z.string(),
  category: z.string(),
  detail: z.string(),
  blocks: z.array(z.string()),
});

export const validationSchema = z.object({
  validation_id: z.number(),
  created_at: z.string(),
  passed: z.boolean(),
  covers_current_dataset: z.boolean(),
  report_version: z.string(),
  technical_validation_passed: z.boolean(),
  check_states: z.record(z.string()).nullable(),
  owner_accepted_findings: z.array(z.object({ check: z.string(), state: z.string(), label: z.string() })),
  unresolved: z.array(z.string()),
});

// One audit outcome: what it means and what it establishes. Existence, kind and hours are separate
// facts; a missing-value outcome carries no session properties.
export const outcomeSchema = z.object({
  code: z.string(),
  count: z.number(),
  label: z.string(),
  existence: z.string().nullable(),
  kind: z.string().nullable(),
  hours: z.string().nullable(),
});

export const benchmarkDetailSchema = benchmarkSummarySchema.extend({
  release: z.string().nullable(),
  gate: z.string(),
  findings: z.array(findingSchema),
  validations: z.array(validationSchema),
  session_calendar: z
    .object({
      calendar_version: z.record(z.unknown()),
      evidence: z.array(z.string()),
      all_series: z.array(outcomeSchema),
      this_series: z
        .object({
          series: z.string(),
          observed: z.array(outcomeSchema),
          missing: z.array(outcomeSchema),
        })
        .nullable(),
      listed_special_sessions: z
        .object({
          listed_sessions: z.number(),
          kind: z.record(z.number()),
          opening_time: z.record(z.number()),
          closing_time: z.record(z.number()),
        })
        .nullable(),
      historical_session_hours: z.string(),
    })
    .nullable(),
  instrument_level_blocked_dates: z.array(z.string()),
});

export const levelsSchema = z.object({
  levels: z.array(z.object({ date: z.string(), level: z.string() })),
  total_observations: z.number(),
  returned: z.number(),
  downsampled: z.boolean(),
  method: z.string(),
});

export const backtestRowSchema = z.object({
  run_id: z.number(),
  strategy_id: z.string(),
  strategy_version: z.string(),
  reader_mode: z.string(),
  created_at: z.string(),
  metrics: z.record(z.unknown()),
  accounting_complete: z.boolean(),
  ledger_reconciled: z.boolean(),
  result_hash: z.string(),
});

export const backtestPageSchema = page(backtestRowSchema);

export const activitySchema = z.object({
  ingestion: page(ingestionRow),
  validations: z.array(
    z.object({
      benchmark_id: z.number(),
      name: z.string(),
      latest: validationSchema.nullable(),
    }),
  ),
  backtests: z.array(backtestRowSchema),
  jobs: z.object({ persisted: z.boolean(), note: z.string() }),
});

const indicatorParam = z.object({
  key: z.string(),
  label: z.string(),
  default: z.string(),
  min: z.string(),
  max: z.string(),
  integer: z.boolean(),
});
const indicatorOutput = z.object({ key: z.string(), label: z.string(), kind: z.enum(["line", "histogram", "dots"]), color: z.string() });

export const indicatorCatalogSchema = z.object({
  indicators: z.array(
    z.object({
      name: z.string(),
      label: z.string(),
      group: z.string(),
      pane: z.enum(["overlay", "pane"]),
      description: z.string(),
      params: z.array(indicatorParam),
      outputs: z.array(indicatorOutput),
      levels: z.array(z.string()),
    }),
  ),
});

export const indicatorSeriesSchema = z.object({
  adjust: z.enum(["none", "split", "total_return"]),
  adjustment_version: z.string(),
  dates: z.array(z.string()),
  indicators: z.array(
    z.object({
      spec: z.string(),
      name: z.string(),
      label: z.string(),
      pane: z.enum(["overlay", "pane"]),
      params: z.record(z.string()),
      levels: z.array(z.string()),
      outputs: z.array(indicatorOutput.extend({ values: z.array(z.string().nullable()) })),
    }),
  ),
});

export type IndicatorDef = z.infer<typeof indicatorCatalogSchema>["indicators"][number];
export type IndicatorResult = z.infer<typeof indicatorSeriesSchema>["indicators"][number];
export type IndicatorSeries = z.infer<typeof indicatorSeriesSchema>;

export type Dashboard = z.infer<typeof dashboardSchema>;
export type Instrument = z.infer<typeof instrumentSchema>;
export type InstrumentDetail = z.infer<typeof instrumentDetailSchema>;
export type Bars = z.infer<typeof barsSchema>;
export type BenchmarkSummary = z.infer<typeof benchmarkSummarySchema>;
export type BenchmarkDetail = z.infer<typeof benchmarkDetailSchema>;
export type Finding = z.infer<typeof findingSchema>;
export type BacktestRow = z.infer<typeof backtestRowSchema>;
export type Outcome = z.infer<typeof outcomeSchema>;
export type Levels = z.infer<typeof levelsSchema>;
export type Activity = z.infer<typeof activitySchema>;
export type IngestionRow = Activity["ingestion"]["items"][number];
export type Adjust = Bars["adjust"];
