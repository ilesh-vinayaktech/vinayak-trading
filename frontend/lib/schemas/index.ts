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

const jobRun = z.object({ started_at: z.string(), finished_at: z.string(), status: z.enum(["ok", "failed", "skipped"]), attempts: z.number(), detail: z.string() });
const scheduledJob = z.object({ name: z.string(), description: z.string(), calendar: z.string(), last_run: jobRun.nullable(), last_success_at: z.string().nullable() });
export type ScheduledJob = z.infer<typeof scheduledJob>;

export const dashboardSchema = z.object({
  platform: z.object({ status: z.enum(["OK", "ATTENTION", "DOWN"]), reasons: z.array(z.object({ level: z.enum(["attention", "down"]), text: z.string() })) }),
  scorecards: z.object({ platform_correctness: z.object({ status: z.enum(["OK", "ATTENTION", "FAIL", "INCOMPLETE"]), items: z.array(z.object({ name: z.string(), status: z.enum(["PASS", "WARN", "FAIL", "UNKNOWN"]), detail: z.string() })) }), strategy_validity: z.object({ status: z.enum(["OK", "ATTENTION", "FAIL", "INCOMPLETE"]), items: z.array(z.object({ name: z.string(), status: z.enum(["PASS", "WARN", "FAIL", "UNKNOWN"]), detail: z.string() })) }), operational_reliability: z.object({ status: z.enum(["OK", "ATTENTION", "FAIL", "INCOMPLETE"]), items: z.array(z.object({ name: z.string(), status: z.enum(["PASS", "WARN", "FAIL", "UNKNOWN"]), detail: z.string() })) }) }).optional(),
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
  jobs: z.array(scheduledJob),
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
  upcoming: z.array(actionSchema),
});

const figures = z.record(z.string(), z.string());
export const fundamentalsSchema = z.object({
  instrument_id: z.number(),
  symbol: z.string(),
  bases: z.array(z.string()),
  basis: z.string().nullable(),
  periods: z.array(
    z.object({
      period_start: z.string(),
      period_end: z.string(),
      filed_at: z.string(),
      audited: z.boolean(),
      bank: z.boolean(),
      rounding: z.string(),
      quarter: figures,
      ytd: figures,
      instant: figures,
    }),
  ),
});

export const ratiosSchema = z.object({
  instrument_id: z.number(),
  symbol: z.string(),
  bases: z.array(z.string()),
  basis: z.string().nullable(),
  bank: z.boolean(),
  latest_period: z.string().nullable(),
  price: z.object({ value: z.string(), date: z.string().nullable() }).nullable(),
  ratios: z.array(
    z.object({
      key: z.string(),
      label: z.string(),
      group: z.enum(["valuation", "profitability", "growth", "strength", "efficiency", "cash"]),
      unit: z.enum(["pct", "x", "days", "inr", "crore"]),
      meaning: z.string(),
      formula: z.string(),
      better: z.enum(["high", "low"]).nullable(),
      value: z.string().nullable(),
      note: z.string().nullable(),
      as_of: z.string().nullable(),
      reading: z.enum(["good", "ok", "weak"]).nullable(),
      reading_basis: z.enum(["rule", "own_past"]).nullable(),
      year_ago: z.string().nullable(),
      history: z.array(z.object({ period_end: z.string(), value: z.string().nullable() })),
    }),
  ),
});

const eventRef = z.object({ kind: z.string(), ex_date: z.string() });

export const TIMEFRAMES = ["1m", "3m", "5m", "10m", "15m", "30m", "45m", "1h", "2h", "3h", "4h", "1d", "1w", "1mo"] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];

export const barsSchema = z.object({
  adjust: z.enum(["none", "split", "total_return"]),
  timeframe: z.enum(TIMEFRAMES),
  adjustment_version: z.string(),
  clean: z.boolean(),
  source: z.enum(["kite", "nse"]).optional(), // where the daily prices came from (minute bars are always Kite)
  bars: z.array(
    z.object({
      date: z.string(), // the IST trading day
      time: z.number().optional(), // intraday bars only: UTC epoch seconds of the bar open
      open: z.string(),
      high: z.string(),
      low: z.string(),
      close: z.string(),
      volume: z.string(),
      factor: z.string(),
      instrument_id: z.number().optional(), // the instrument that traded the bar (differs across an ISIN change)
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
  label: z.string().nullable(),
  study: z.object({ experiment_id: z.number(), name: z.string() }).nullable(),
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
  times: z.array(z.number()).optional(), // intraday only: UTC epoch seconds of each bar open
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
export type Fundamentals = z.infer<typeof fundamentalsSchema>;
export type Ratios = z.infer<typeof ratiosSchema>;
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

const reviewOption = z.object({
  value: z.string(),
  label: z.string(),
  needs_date: z.boolean(),
  date_label: z.string().optional(),
  has_end: z.boolean().optional(),
  needs_evidence: z.boolean().optional(),
});
const reviewDecision = z.object({
  decision_id: z.number(),
  decision: z.string(),
  effective_date: z.string().nullable(),
  effective_to: z.string().nullable(),
  evidence_ref: z.string(),
  note: z.string(),
  reviewer: z.string(),
  decided_at: z.string(),
});
export const reviewListSchema = z.object({
  writes_enabled: z.boolean(),
  total: z.number(),
  decided: z.number(),
  items: z.array(
    z.object({
      id: z.string(),
      kind: z.string(),
      title: z.string(),
      question: z.string(),
      category: z.string(),
      context: z.record(z.string()),
      leads: z.array(z.string()),
      options: z.array(reviewOption),
      latest: reviewDecision.nullable(),
    }),
  ),
});
export const reviewHistorySchema = z.array(reviewDecision);
export type ReviewItem = z.infer<typeof reviewListSchema>["items"][number];
export type ReviewDecision = z.infer<typeof reviewDecision>;
export type ReviewDraft = { decision: string; reviewer: string; effective_date?: string; effective_to?: string; evidence_ref: string; note: string };


// ---- portal: sign-in and the signed-in user ------------------------------------------------------------------------
export const userSchema = z.object({
  id: z.string(),
  email: z.string(),
  name: z.string(),
  role: z.enum(["ADMIN", "OPERATOR", "TRADER", "VIEWER"]),
  permissions: z.array(z.string()),
  mfa_enabled: z.boolean(),
  enrolment_required: z.boolean(), // an admin/operator who has not set up a second factor yet
  must_change_password: z.boolean(),
});
export const meSchema = z.object({ user: userSchema });
export const loginSchema = z.union([z.object({ mfa_required: z.literal(true) }), meSchema]);
export const okSchema = z.object({ ok: z.boolean() });
export const mfaEnrolSchema = z.object({ secret: z.string(), uri: z.string() });
export const recoverySchema = z.object({ recovery_codes: z.array(z.string()) });
export const sessionListSchema = z.object({
  sessions: z.array(
    z.object({
      session_id: z.string(),
      created_at: z.string(),
      last_seen_at: z.string(),
      expires_at: z.string(),
      ip: z.string().nullable(),
      user_agent: z.string().nullable(),
      current: z.boolean(),
    }),
  ),
});
export type User = z.infer<typeof userSchema>;
export type SessionRow = z.infer<typeof sessionListSchema>["sessions"][number];


// ---- portal: user administration and the audit trail ---------------------------------------------------------------
export const ROLES = ["ADMIN", "OPERATOR", "TRADER", "VIEWER"] as const;
export const STATUSES = ["INVITED", "ACTIVE", "SUSPENDED", "DISABLED"] as const;
export const userRowSchema = z.object({
  id: z.string(),
  email: z.string(),
  name: z.string(),
  role: z.enum(ROLES),
  status: z.enum(STATUSES),
  mfa_enabled: z.boolean(),
  last_login_at: z.string().nullable(),
  created_at: z.string(),
  tags: z.array(z.string()),
});
export const userListSchema = z.object({ total: z.number(), items: z.array(userRowSchema) });
export const userDetailSchema = userRowSchema.extend({
  must_change_password: z.boolean(),
  password_changed_at: z.string().nullable(),
  created_by: z.string().nullable(),
  recovery_codes_left: z.number(),
  active_sessions: z.number(),
});
export const inviteResultSchema = z.object({ id: z.string(), invite_url: z.string() });
export const inviteLinkSchema = z.object({ invite_url: z.string() });
export const resetLinkSchema = z.object({ reset_url: z.string() });
export const endedSchema = z.object({ ended: z.number() });
export const auditSchema = z.object({
  events: z.array(
    z.object({
      id: z.number(),
      at: z.string(),
      actor_user_id: z.string().nullable(),
      actor: z.string(),
      action: z.string(),
      target_type: z.string().nullable(),
      target_id: z.string().nullable(),
      detail: z.record(z.unknown()),
      ip: z.string().nullable(),
    }),
  ),
});
export type UserRow = z.infer<typeof userRowSchema>;
export type UserDetail = z.infer<typeof userDetailSchema>;
export type AuditEvent = z.infer<typeof auditSchema>["events"][number];
export type Role = (typeof ROLES)[number];
export type Status = (typeof STATUSES)[number];


// ---- portal: the signed-in user's own Kite connection --------------------------------------------------------------
export const kiteConnectionSchema = z.object({
  state: z.enum(["not_configured", "saved", "connected", "expired"]),
  api_key_hint: z.string().nullable(), // the last four characters only: the key, secret and token never reach the browser
  kite_user_id: z.string().nullable(),
  connected_at: z.string().nullable(),
  token_expires_at: z.string().nullable(),
  is_system: z.boolean(),
  redirect_url: z.string(), // the address to register as the redirect URL of the user's Kite Connect app
});
export const kiteLoginSchema = z.object({ login_url: z.string() });
export const kiteUserSchema = z.object({ kite_user: z.string() });
export const kiteSystemSchema = z.object({
  feed: z.object({ owner_id: z.string(), owner: z.string(), api_key_hint: z.string(), state: z.enum(["saved", "connected", "expired"]), token_expires_at: z.string().nullable() }).nullable(),
});
export type KiteConnection = z.infer<typeof kiteConnectionSchema>;


// ---- portal CRM and support tickets -------------------------------------------------------------------------------
export const noteListSchema = z.object({ notes: z.array(z.object({ id: z.string(), body: z.string(), created_at: z.string(), author: z.string() })) });
export const tagListSchema = z.object({ tags: z.array(z.object({ tag: z.string(), users: z.number() })) });
export const staffListSchema = z.object({ staff: z.array(z.object({ id: z.string(), name: z.string(), role: z.string() })) });
export const taskSchema = z.object({
  id: z.string(),
  title: z.string(),
  detail: z.string(),
  due_date: z.string().nullable(),
  status: z.enum(["OPEN", "DONE"]),
  created_at: z.string(),
  completed_at: z.string().nullable(),
  owner: z.string(),
  owner_id: z.string(),
  about: z.string().nullable(),
  about_id: z.string().nullable(),
});
export const taskListSchema = z.object({ tasks: z.array(taskSchema) });
export const TICKET_STATUSES = ["OPEN", "PENDING", "RESOLVED", "CLOSED"] as const;
export const PRIORITIES = ["LOW", "NORMAL", "HIGH"] as const;
export const ticketRowSchema = z.object({
  id: z.string(),
  number: z.number(),
  subject: z.string(),
  status: z.enum(TICKET_STATUSES),
  priority: z.enum(PRIORITIES),
  requester: z.string(),
  requester_id: z.string(),
  assignee: z.string().nullable(),
  assignee_id: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export const ticketListSchema = z.object({ total: z.number(), items: z.array(ticketRowSchema) });
export const ticketDetailSchema = ticketRowSchema.extend({
  messages: z.array(z.object({ id: z.string(), body: z.string(), internal: z.boolean(), created_at: z.string(), author: z.string(), mine: z.boolean() })),
});
export const ticketCreatedSchema = z.object({ number: z.number() });
export const idSchema = z.object({ id: z.string() });
export const tagSchema = z.object({ tag: z.string() });
export type Task = z.infer<typeof taskSchema>;
export type TicketRow = z.infer<typeof ticketRowSchema>;
export type TicketStatus = (typeof TICKET_STATUSES)[number];


// ---- portal dashboards ----------------------------------------------------------------------------------------------
const countsSchema = z.record(z.string(), z.number());
export const myDashboardSchema = z.object({
  kite: kiteConnectionSchema,
  tickets: z.object({ open: z.number(), latest: z.array(z.object({ ticket_id: z.string(), number: z.number(), subject: z.string(), status: z.string(), updated_at: z.string() })) }),
  tasks: z.object({ open: z.number(), overdue: z.number() }),
  security: z.object({ mfa_enabled: z.boolean(), last_login_at: z.string().nullable(), active_sessions: z.number() }),
});
export const opsDashboardSchema = z.object({
  users: z.object({ by_status: countsSchema, by_role: countsSchema }),
  signins: z.object({ successes_24h: z.number(), failures_24h: z.number() }),
  tickets: z.object({ open: z.number(), unassigned: z.number() }),
  tasks: z.object({ open: z.number(), overdue: z.number() }),
  kite: z.object({ connected: z.number(), feed: kiteSystemSchema.shape.feed }),
  feed: z.object({ state: z.enum(["STARTING", "CONNECTED", "RECONNECTING", "TOKEN_EXPIRED", "STOPPED"]), detail: z.string(), subscribed: z.number(), heartbeat_age: z.number(), tick_age: z.number().nullable() }).nullable(),
  recent: z.array(z.object({ id: z.number(), at: z.string(), actor: z.string(), action: z.string() })),
});
export type MyDashboard = z.infer<typeof myDashboardSchema>;
export type OpsDashboard = z.infer<typeof opsDashboardSchema>;


// ---- portal: the trading calendar (holidays and special sessions the live feed follows) ---------------------------------
export const marketCalendarSchema = z.object({
  today: z.object({ day: z.string(), windows: z.array(z.object({ start: z.string(), end: z.string() })) }),
  exceptions: z.array(z.object({ id: z.number(), day: z.string(), kind: z.enum(["SESSION", "CLOSED"]), start: z.string().nullable(), end: z.string().nullable(), note: z.string(), source: z.enum(["nse", "manual"]), needs_times: z.boolean() })),
});
export const marketIdSchema = z.object({ id: z.number() });
export type MarketCalendar = z.infer<typeof marketCalendarSchema>;


// ---- paper trading (UNVALIDATED research: nothing here places a real order) ----------------------------------------------
const decimal = z.string(); // money and quantities arrive as decimal strings and are only ever formatted, never computed
export const paperParamsSchema = z.object({ trend_sma: z.number(), entry_rsi: z.number(), exit_rsi: z.number(), max_positions: z.number() });
export const screenConfigSchema = z.object({
  screen: z.object({
    conditions: z.array(z.object({ field: z.string(), op: z.string(), value: z.unknown() })),
    match: z.string(),
    sort: z.string(),
    descending: z.boolean(),
  }),
  segments: z.array(z.string()),
});
export const paperAccountSchema = z.object({
  label: z.string(),
  options: z.object({
    universes: z.array(z.object({ key: z.string(), label: z.string() })),
    timeframes: z.array(z.object({ key: z.string(), label: z.string(), available: z.boolean() })),
    params: z.object({ trend_sma: z.array(z.number()), entry_rsi: z.array(z.number()), exit_rsi: z.array(z.number()), max_positions: z.array(z.number()) }),
  }),
  account: z
    .object({
      strategy_id: z.string(),
      enabled: z.boolean(),
      mode: z.string(),
      initial_cash: decimal,
      started_on: z.string(),
      attention: z.string().nullable(),
      universe: z.string(),
      max_instruments: z.number().nullable(),
      timeframe: z.string(),
      params: paperParamsSchema.partial(), // a screener account only has max_positions
      screen: screenConfigSchema.nullable(), // the rules of a screener strategy, else null
      definition: z.string().nullable(), // the name of the strategy definition the account follows, else null
    })
    .nullable(),
});
export const paperDefinitionsSchema = z.object({
  label: z.string(),
  definitions: z.array(z.object({ experiment_id: z.number(), strategy_id: z.string(), version: z.number(), name: z.string(), state: z.enum(["awaiting_holdout", "failed_holdout", "ready"]) })),
});
export type PaperDefinitions = z.infer<typeof paperDefinitionsSchema>;
export const paperSummarySchema = z.object({
  equity: decimal,
  cash: decimal,
  invested: decimal,
  pnl: z.object({ realized: decimal, unrealized: decimal, fees: decimal, net: decimal }),
  positions: z.array(z.object({ instrument_id: z.number(), symbol: z.string(), qty: decimal, avg_cost: decimal, last_price: decimal, value: decimal, unrealized: decimal, upcoming: z.array(actionSchema) })),
  equity_curve: z.array(z.object({ day: z.string(), equity: decimal })),
  pending_orders: z.number(),
});
export const PAPER_STATUSES = ["PENDING", "APPROVED", "REJECTED", "EXPIRED", "FILLED", "FAILED"] as const;
export const paperOrderSchema = z.object({
  order_id: z.string(),
  symbol: z.string(),
  side: z.enum(["BUY", "SELL"]),
  qty: decimal,
  ref_price: decimal,
  reason: z.string(),
  status: z.enum(PAPER_STATUSES),
  decision_day: z.string(),
  created_at: z.string(),
  expires_at: z.string(),
  fill_price: decimal.nullable(),
  fill_commission: decimal.nullable(),
  fill_day: z.string().nullable(),
  failure: z.string().nullable(),
  order_type: z.enum(["MARKET", "LIMIT"]),
  limit_price: decimal.nullable(),
  tick_size: decimal.nullable(), // the exchange price step of an open order's stock (a limit is rounded to it by the server)
  upcoming: z.array(actionSchema), // announced actions within days of an order that is still open
});
export const marketZoneSchema = z.object({
  latest: z
    .object({
      day: z.string(),
      age_days: z.number(),
      fear_greed: z.number().nullable(),
      label: z.string().nullable(),
      trend: z.string().nullable(), // BULL | BEAR | SIDEWAYS | UNKNOWN
      volatility: z.string().nullable(), // CALM | NORMAL | STRESSED | UNKNOWN
      universe: z.number(),
      advancers: z.number(),
      decliners: z.number(),
      unchanged: z.number(),
      pct_above_50: z.number().nullable(),
      pct_above_200: z.number().nullable(),
      highs: z.number(),
      lows: z.number(),
    })
    .nullable(),
  drivers: z.array(z.object({ key: z.string(), name: z.string(), score: z.number() })), // greediest first
  history: z.array(z.object({ day: z.string(), fear_greed: z.number().nullable(), trend: z.string().nullable() })), // oldest first
});
export type MarketZone = z.infer<typeof marketZoneSchema>;
export const sectorRotationSchema = z.object({
  as_of: z.string().nullable(),
  benchmark: z.string(),
  sectors: z.array(
    z.object({
      name: z.string(),
      score: z.number(), // 0 to 100, ranked across the sectors
      close: z.number(),
      ret_1d: z.number().nullable(),
      ret_5d: z.number().nullable(),
      ret_21d: z.number().nullable(),
      ret_63d: z.number().nullable(),
      ret_252d: z.number().nullable(),
      above_50: z.boolean(),
      above_200: z.boolean(),
      rs_ratio: z.number(), // against its own 50-day norm: 100 is steady
      rs_momentum: z.number(),
      quadrant: z.string(), // Leading | Improving | Weakening | Lagging
    }),
  ),
});
export type SectorRotation = z.infer<typeof sectorRotationSchema>;
const evidenceSchema = z.object({ feature: z.string(), value: z.number(), effect: z.number() }); // effect in log-odds: above 0 pushed towards UP
export const forecastSchema = z.object({
  as_of: z.string().nullable(),
  market: z.array(z.object({ horizon_days: z.number(), p_up: z.number(), evidence: z.array(evidenceSchema) })),
  sectors: z.array(z.object({ name: z.string(), p_1d: z.number().nullable(), p_5d: z.number().nullable(), evidence: z.array(evidenceSchema) })), // most bullish first
  record: z.array(
    z.object({
      subject: z.string(),
      horizon_days: z.number(),
      live: z.boolean(), // false = walk-forward history
      n: z.number(),
      hit_rate: z.number(),
      base_rate: z.number(),
      base_hit: z.number(),
      brier_skill: z.number(),
      beats_guessing: z.boolean(),
      calibration: z.array(z.object({ predicted: z.number(), actual: z.number(), n: z.number() })),
    }),
  ),
  misses: z.array(z.object({ as_of: z.string(), p_up: z.number(), realized: z.number(), went_up: z.boolean(), evidence: z.array(evidenceSchema) })),
  labels: z.record(z.string(), z.string()).optional(),
});
export type Forecast = z.infer<typeof forecastSchema>;
export const liveStatusSchema = z.object({
  account: z.boolean(),
  open: z.boolean(), // the gate is open: live can run
  problems: z.array(z.string()),
  stage: z.string(),
  process: z.object({ state: z.string(), silent_s: z.number().nullable(), detail: z.string() }).nullable(),
});
export type LiveStatus = z.infer<typeof liveStatusSchema>;
export const paperOrdersSchema = z.object({ orders: z.array(paperOrderSchema) });
export const paperRunsSchema = z.object({
  runs: z.array(z.object({ decision_day: z.string(), status: z.enum(["PROPOSED", "NO_CHANGE", "SKIPPED", "ERROR"]), reason: z.string().nullable(), orders: z.number(), universe: z.string().nullable(), strategy_version: z.string(), created_at: z.string() })),
});
export type PaperAccount = z.infer<typeof paperAccountSchema>;
export type PaperSummary = z.infer<typeof paperSummarySchema>;
export type PaperOrder = z.infer<typeof paperOrderSchema>;
export type PaperRun = z.infer<typeof paperRunsSchema>["runs"][number];


// ---- trading costs: schedules per provider, with effective dates, sources and a calculator ---------------------------------
export const COST_STATUSES = ["verified", "extracted_unverified", "assumed_backfill"] as const;
export const costScheduleSchema = z.object({
  schedule_id: z.string(),
  version: z.string(),
  name: z.string(),
  broker: z.string(),
  product: z.enum(["DELIVERY", "INTRADAY"]),
  valid_from: z.string(),
  valid_until: z.string().nullable(),
  status: z.enum(COST_STATUSES),
  verified_by: z.string().nullable(),
  verified_at: z.string().nullable(),
  notes: z.string(),
  assumptions: z.array(z.string()),
  contract_note_min_brokerage: z.string().nullable(),
  components: z.array(z.object({ type: z.string(), side: z.enum(["BUY", "SELL", "BOTH"]), basis: z.string(), rate_pct: z.string().nullable(), amount: z.string().nullable(), minimum: z.string().nullable(), maximum: z.string().nullable(), source: z.string() })),
  sources: z.array(z.object({ key: z.string(), url: z.string(), retrieved_at: z.string(), quote: z.string(), locator: z.string() })),
});
export const costSchedulesSchema = z.object({ schedules: z.array(costScheduleSchema) });
export const costPreviewSchema = z.object({
  schedule: z.object({ id: z.string(), version: z.string(), status: z.enum(COST_STATUSES), valid_from: z.string(), valid_until: z.string().nullable() }),
  value: z.string(),
  lines: z.array(z.object({ type: z.string(), amount: z.string(), formula: z.string() })),
  total: z.string(),
});
export type CostSchedule = z.infer<typeof costScheduleSchema>;
export type CostPreview = z.infer<typeof costPreviewSchema>;

// ---- strategies: saved, named settings (UNVALIDATED research) -------------------------------------------------------------
export const strategyConfigSchema = z.object({
  config_id: z.string(),
  name: z.string(),
  strategy_id: z.string(),
  universe: z.string(),
  max_instruments: z.number().nullable(),
  timeframe: z.string(),
  params: paperParamsSchema.partial(), // a screener strategy only has max_positions
  screen: screenConfigSchema.nullable(), // the rules of a screener strategy, else null
  in_use: z.boolean(),
  created_at: z.string(),
  stage: z.enum(["RESEARCH", "PAPER", "LIVE"]),
});
export const strategiesSchema = z.object({ label: z.string(), options: paperAccountSchema.shape.options, strategies: z.array(strategyConfigSchema) });
export const stageHistorySchema = z.object({
  label: z.string(),
  stage: z.enum(["RESEARCH", "PAPER", "LIVE"]),
  history: z.array(z.object({
    change_id: z.number(), from_stage: z.string(), to_stage: z.string(), approver: z.string(), at: z.string(),
    run_id: z.number().nullable(), reason: z.string(), waived: z.array(z.string()),
  })),
});
export type StageHistory = z.infer<typeof stageHistorySchema>;
export const strategyCreatedSchema = z.object({ config_id: z.string() });
export type StrategyConfig = z.infer<typeof strategyConfigSchema>;
export type Strategies = z.infer<typeof strategiesSchema>;

// ---- strategy signals: one stock's buy/sell decisions (UNVALIDATED research, decisions only) ----------------------------------
export const signalDaySchema = z.object({
  day: z.string(),
  close: z.string(),
  sma: z.string().nullable(),
  rsi: z.string().nullable(),
  ready: z.boolean(),
  action: z.enum(["BUY", "SELL"]).nullable(),
  reason: z.string().nullable(),
  holding_after: z.boolean(),
  fill_day: z.string().nullable(),
  fill_price: z.string().nullable(),
});
export const signalsSchema = z.object({
  label: z.string(),
  strategy: z.string(),
  params: paperParamsSchema.partial(),
  notes: z.array(z.string()),
  summary: z.object({ buys: z.number(), sells: z.number() }),
  days: z.array(signalDaySchema),
});
export type Signals = z.infer<typeof signalsSchema>;
export type SignalDay = z.infer<typeof signalDaySchema>;

// ---- live price of one stock: the feed's latest quote (decimal strings) ------------------------------------------------------
export const liveSchema = z.object({
  today: z.string(), // the server's day in India
  // the candle still forming for the requested timeframe: `time` is a date (1d/1w/1mo) or UTC epoch seconds (intraday)
  candle: z.object({ time: z.union([z.number(), z.string()]), open: z.string(), high: z.string(), low: z.string(), close: z.string(), volume: z.string() }).nullable(),
  live: z.boolean(), // the feed is connected and has ticked within the last 30 seconds
  feed: z.object({ state: z.string().nullable(), last_tick_at: z.string().nullable() }),
  session_date: z.string().nullable(), // the day (India) of the quote
  quote: z
    .object({ ltp: z.string(), open: z.string().nullable(), high: z.string().nullable(), low: z.string().nullable(), prev_close: z.string().nullable(), volume: z.string().nullable(), updated_at: z.string() })
    .nullable(),
});
export type Live = z.infer<typeof liveSchema>;

// ---- backtest studies: the owner's choices, locked at registration ------------------------------------------------------------
export const studyOptionsSchema = z.object({
  strategies: z.array(z.object({ id: z.string(), params: z.array(z.object({ name: z.string(), choices: z.array(z.number()).nullable(), default: z.number() })) })),
  segments: z.array(z.string()),
  timeframes: z.array(z.string()),
  brokers: z.array(z.object({ broker: z.string(), product: z.string() })),
  benchmarks: z.array(z.object({ name: z.string(), usable: z.boolean(), default: z.boolean() })),
  frozen_through: z.string().nullable(),
  survivorship_safe_from: z.string(),
  segment_lists_from: z.string(),
  max_trials: z.number(),
  holdout_share: z.array(z.number()),
  thresholds: z.record(z.string(), z.string()),
  families: z.array(z.object({ family_id: z.number(), name: z.string(), hypothesis: z.string(), studies: z.number(), trials: z.number() })),
});
export const familyCreatedSchema = z.object({ family_id: z.number() });
export const studySpecSchema = z.object({
  family_id: z.number().nullable().optional(),
  name: z.string(),
  hypothesis: z.string(),
  strategy_id: z.string(),
  grid: z.record(z.string(), z.array(z.number())),
  screen: z.object({ conditions: z.array(z.object({ field: z.string(), op: z.string(), value: z.unknown() })), match: z.enum(["all", "any"]), sort: z.string(), descending: z.boolean() }).nullable().optional(),
  universe: z.object({ segments: z.array(z.string()), before_segment_lists: z.string(), min_history_sessions: z.number() }),
  timeframe: z.string(),
  start: z.string(),
  end: z.string(),
  holdout_start: z.string(),
  capital: z.string(),
  capacity_multiple: z.string(),
  broker: z.string(),
  product: z.string(),
  slippage: z.object({ base_bps: z.string(), participation_bps_per_pct: z.string(), volatility_fraction: z.string() }),
  min_order_value: z.string(),
  max_order_value: z.string().nullable(),
  benchmark: z.string(),
  thresholds: z.record(z.string(), z.string()),
  accept_survivorship_bias: z.boolean(),
  filing_lag_days: z.number().optional(), // absent in studies registered before the field existed
});
export const studySchema = z.object({
  experiment_id: z.number(),
  name: z.string(),
  strategy_id: z.string(),
  hypothesis: z.string(),
  registered_at: z.string(),
  holdout_opened_at: z.string().nullable(),
  spec: studySpecSchema,
  combinations: z.array(z.record(z.string(), z.number())),
  data_freeze: z.object({ id: z.string(), through: z.string() }),
  cost_schedules: z.array(z.object({ schedule_id: z.string(), version: z.string(), broker: z.string(), product: z.string(), status: z.string(), valid_from: z.string(), valid_until: z.string().nullable() })),
  trials_planned: z.number(),
  trials_run: z.number(),
  sha256: z.string(),
  owner_user_id: z.string().nullable(),
});
export const studiesSchema = z.object({ studies: z.array(studySchema) });
export const studyCreatedSchema = z.object({ experiment_id: z.number() });
export type StudyOptions = z.infer<typeof studyOptionsSchema>;
export type StudySpec = z.infer<typeof studySpecSchema>;
export type Study = z.infer<typeof studySchema>;

export const studyRunSchema = z.object({
  run_id: z.number(),
  experiment_id: z.number(),
  kind: z.enum(["trials", "verdict", "holdout"]),
  status: z.enum(["QUEUED", "RUNNING", "DONE", "FAILED", "CANCELLED"]),
  total: z.number(),
  done: z.number(),
  current: z.string().nullable(),
  step_done: z.number(),
  step_total: z.number(),
  cancel_requested: z.boolean(),
  progress: z.object({ fraction: z.number(), elapsed_seconds: z.number(), eta_seconds: z.number().nullable(), step_done: z.number(), step_total: z.number() }).nullable(),
  error: z.string().nullable(),
  requested_by: z.string().nullable(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
});
export const studyTrialSchema = z.object({
  trial_id: z.number(),
  params: z.record(z.string(), z.number()),
  status: z.enum(["DONE", "FAILED"]),
  metrics: z.record(z.string(), z.number().nullable()).nullable(),
  error: z.string().nullable(),
  seconds: z.number().nullable(),
  finished_at: z.string(),
  backtest_run: z.number().nullable(),
});
export const studyResultsSchema = z.object({
  run: studyRunSchema.nullable(),
  trials: z.array(studyTrialSchema),
  universe_coverage: z.array(z.object({ list: z.string(), from: z.string(), until: z.string(), in_segments: z.number(), matched: z.number(), usable: z.number() })),
});
export const studyRunCreatedSchema = z.object({ run_id: z.number() });
export type StudyRun = z.infer<typeof studyRunSchema>;
export type StudyTrial = z.infer<typeof studyTrialSchema>;
export type StudyResults = z.infer<typeof studyResultsSchema>;

const nstr = z.string().nullable();
export const backtestReportSchema = z.object({
  study: z.object({ experiment_id: z.number(), name: z.string() }).nullable(),
  run_id: z.number(),
  strategy_id: z.string(),
  strategy_version: z.string(),
  label: z.string().nullable(),
  params: z.record(z.unknown()),
  start: z.string().nullable(),
  end: z.string().nullable(),
  created_at: z.string(),
  headline: z.object({ initial: z.string(), final: nstr, change: nstr, return: nstr, max_drawdown: z.string(), charges: z.string(), dividends: z.string() }),
  summary: z.object({
    trades: z.number(), wins: z.number(), losses: z.number(), win_rate: nstr, net_pnl: z.string(),
    gross_profit: z.string(), gross_loss: z.string(), profit_factor: nstr, avg_win: nstr, avg_loss: nstr,
    charges: z.string(), avg_holding_days: nstr, pre_charge_pnl: z.string(), cost_drag: nstr,
  }),
  curve: z.array(z.object({ date: z.string(), equity: z.string(), drawdown: z.string() })),
  round_trips: z.array(z.object({
    instrument_id: z.number(), symbol: z.string(), qty: z.string(), entry_day: z.string(), entry_price: z.string(),
    exit_day: z.string(), exit_price: z.string(), gross: z.string(), charges: z.string(), net: z.string(),
    holding_days: z.number(), return: nstr,
  })),
  benchmark: z
    .object({
      name: z.string(), note: nstr, curve: z.array(z.object({ date: z.string(), level: z.string() })),
      return: nstr, final: nstr, max_drawdown: nstr, sharpe: nstr,
      strategy_return: nstr, strategy_max_drawdown: nstr, strategy_sharpe: nstr,
    })
    .nullable(),
  monthly: z.array(z.object({ month: z.string(), net: z.string(), trades: z.number() })),
  by_weekday: z.array(z.object({ weekday: z.string(), trades: z.number(), net: z.string(), win_rate: nstr })),
  distribution: z.array(z.object({ label: z.string(), count: z.number() })),
  open_positions: z.array(z.object({ symbol: z.string(), instrument_id: z.number(), qty: z.string(), lots: z.number(), entry_day: z.string(), entry_price: z.string() })),
  by_stock: z.array(z.object({ symbol: z.string(), trades: z.number(), net: z.string(), win_rate: nstr, charges: z.string() })),
});
export type BacktestReport = z.infer<typeof backtestReportSchema>;

export const gateStatusSchema = z.enum(["PASS", "FAIL", "INSUFFICIENT_EVIDENCE", "NOT_APPLICABLE"]);
/** A check's result. `status` is absent on reports stored before the four-way verdicts: see gateState. */
export const gateSchema = z.object({ name: z.string(), passed: z.boolean(), detail: z.string(), status: gateStatusSchema.optional() });
export const studyHoldoutSchema = z.object({
  run_id: z.number(),
  passed: z.boolean(),
  created_at: z.string(),
  evidence: z.record(z.string(), z.number().nullable()),
  gates: z.array(gateSchema),
  refs: z.object({ chosen: z.record(z.string(), z.number()), benchmark: z.string(), benchmark_note: z.string().nullable(), window: z.array(z.string()), verdict_report: z.number() }),
});
export const studyVerdictSchema = z.object({
  holdout: studyHoldoutSchema.nullable(),
  holdout_run: studyRunSchema.nullable(),
  run: studyRunSchema.nullable(),
  report: z
    .object({
      report_id: z.number(),
      run_id: z.number(),
      passed: z.boolean(),
      thresholds_status: z.string(),
      n_trials: z.number(),
      created_at: z.string(),
      evidence: z.record(z.string(), z.number().nullable()),
      gates: z.array(gateSchema),
      refs: z.object({
        chosen: z.record(z.string(), z.number()),
        benchmark: z.string(),
        benchmark_note: z.string().nullable(),
        windows: z.array(z.object({
          train_from: z.string(), train_to: z.string(), test_from: z.string(), test_to: z.string(),
          chosen: z.record(z.string(), z.number()), sharpe: z.number().nullable(), return: z.number(),
        })),
        walk_forward: z.object({ train: z.number(), test: z.number(), embargo: z.number() }),
        cost_2x_run: z.number(),
        capital_run: z.number(),
        capital_multiple: z.string(),
      }),
    })
    .nullable(),
  trials_done: z.number(),
  trials_planned: z.number(),
});
export type StudyVerdict = z.infer<typeof studyVerdictSchema>;

// ---- screener (fundamental + technical) ----------------------------------------------------------------------------------
export const screenerMetaSchema = z.object({
  fields: z.array(z.object({ key: z.string(), label: z.string(), group: z.string(), kind: z.enum(["fundamental", "technical", "profile", "smart_money"]), unit: z.string() })),
  presets: z.array(z.object({
    id: z.string(), name: z.string(), category: z.enum(["fundamental", "technical", "combined", "smart_money", "score"]), description: z.string(), sort: z.string(), descending: z.boolean(),
    conditions: z.array(z.object({ field: z.string(), op: z.string(), value: z.unknown() })),
  })),
});
export const screenerRunSchema = z.object({ total: z.number(), sort: z.string().nullable(), as_of: z.string().nullable().optional(), rows: z.array(z.record(z.string(), z.union([z.string(), z.number(), z.boolean(), z.null()]))) });
export type ScreenerMeta = z.infer<typeof screenerMetaSchema>;
export type ScreenerCondition = { field: string; op: string; value?: unknown };

export const actionWorklistSchema = z.object({
  total: z.number(),
  by_kind: z.record(z.number()),
  items: z.array(
    z.object({
      symbol: z.string(),
      ex_date: z.string(),
      kind: z.string(),
      subject: z.string(),
      reason: z.string(),
      prev_close: z.string().nullable(),
      ex_close: z.string().nullable(),
      move_pct: z.string().nullable(),
      in_nifty200: z.boolean(),
      has_prices: z.boolean(),
      impact: z.number(),
    }),
  ),
});
export type ActionWorklist = z.infer<typeof actionWorklistSchema>;

const riskEvent = z.object({ ts: z.string(), scope: z.string().nullable(), mode: z.string(), by: z.string(), reason: z.string() });
const riskScope = z.object({ mode: z.string(), by: z.string(), reason: z.string(), ts: z.string() });
export const riskStateSchema = z.object({
  label: z.string(),
  account: z.object({ strategy_id: z.string() }).nullable(),
  switch: z.object({ effective: z.enum(["RUNNING", "PAUSE", "CANCEL", "FLATTEN"]), global: riskScope.nullable(), strategy: riskScope.nullable() }),
  events: z.array(riskEvent),
  limits: z.record(z.unknown()).nullable(),
  limit_keys: z.array(z.object({ key: z.string(), kind: z.string(), help: z.string() })),
  can_global: z.boolean(),
});
export type RiskState = z.infer<typeof riskStateSchema>;
export type SwitchAction = "pause" | "cancel" | "resume" | "flatten";

const regulatoryItem = z.object({
  topic: z.string(),
  label: z.string(),
  help: z.string(),
  example: z.record(z.unknown()),
  status: z.enum(["ok", "stale", "missing"]),
  value: z.unknown().nullable(),
  source: z.string().nullable(),
  effective_from: z.string().nullable(),
  last_verified: z.string().nullable(),
  verified_by: z.string().nullable(),
  expires_on: z.string().nullable(),
  days_since: z.number().nullable(),
});
export const regulatorySchema = z.object({
  today: z.string(),
  exchange: z.string(),
  segment: z.string(),
  max_age_days: z.number(),
  blocks_live: z.boolean(),
  problems: z.array(z.string()),
  items: z.array(regulatoryItem),
  can_edit: z.boolean(),
});
export type Regulatory = z.infer<typeof regulatorySchema>;
export type RegulatoryItem = z.infer<typeof regulatoryItem>;

// The signed-in person's own Kite account, read only. `platform_qty` is what the platform bought itself (its own filled orders);
// `outside_qty` is the rest, which the platform never sells.
export const brokerAccountSchema = z.object({
  state: z.enum(["ok", "not_connected", "expired", "unavailable"]),
  message: z.string().nullable(),
  read_at: z.string().nullable(),
  kite_user_id: z.string().nullable(),
  cash: decimal.nullable(),
  holdings: z.array(
    z.object({
      symbol: z.string(),
      instrument_id: z.number().nullable(), // our id, when we know the stock: opens its detail page
      quantity: decimal, // settled plus not yet settled
      unsettled: decimal,
      average_price: decimal,
      last_price: decimal,
      value: decimal,
      pnl: decimal,
      platform_qty: decimal,
      outside_qty: decimal,
    }),
  ),
  positions: z.array(z.object({ symbol: z.string(), instrument_id: z.number().nullable(), product: z.string(), quantity: decimal, average_price: decimal, last_price: decimal, pnl: decimal })),
  totals: z.object({ holdings_value: decimal, holdings_pnl: decimal }),
});
export type BrokerAccount = z.infer<typeof brokerAccountSchema>;


// ---- research intelligence (phases 1 to 5; read-only) ------------------------------------------------------------------
const intelCountsSchema = z.record(z.string(), z.number());
export const intelOverviewSchema = z.object({
  features: z.object({ by_status: intelCountsSchema }),
  alpha: z.object({ tests_ever_run: z.number(), by_status: intelCountsSchema }),
  factory: z.object({ definitions: z.number(), experiments: z.number(), trials: z.number() }),
  notes: z.object({ total: z.number() }),
  health: z.array(z.object({ scope: z.string(), status: z.enum(["PASS", "FAIL"]), detail: z.string(), at: z.string() })),
  allocation: z
    .object({ id: z.number(), method: z.string(), weights: z.record(z.string(), z.number()), cash: z.number(), notes: z.array(z.string()), by: z.string(), at: z.string() })
    .nullable(),
});
export const intelAlphaSchema = z.object({
  hypotheses: z.array(
    z.object({
      id: z.number(),
      batch: z.number(),
      feature: z.string(),
      version: z.string(),
      horizon: z.number(),
      status: z.enum(["CANDIDATE", "REJECTED"]),
      mean_ic: z.number().nullable(),
      icir: z.number().nullable(),
      p_adjusted: z.number().nullable(),
      direction: z.enum(["POSITIVE", "NEGATIVE"]).nullable(),
      sample_days: z.number().nullable(),
      at: z.string(),
    }),
  ),
});
export const intelNotesSchema = z.object({
  notes: z.array(z.object({ id: z.number(), kind: z.enum(["FINDING", "FAILURE", "DECISION", "LESSON"]), subject: z.string(), body: z.string(), tags: z.array(z.string()), by: z.string(), at: z.string() })),
});
export const intelDefinitionsSchema = z.object({
  definitions: z.array(
    z.object({
      strategy_id: z.string(), version: z.number(), description: z.string(), rebalance: z.string(), max_positions: z.number(), entry: z.string(), exit: z.string(),
      plain: z.object({ when: z.string(), summary: z.string(), buy: z.string(), sell: z.string(), size: z.string() }),
      created_by: z.string(), created_at: z.string(), experiment_id: z.number().nullable(), study_name: z.string().nullable(), study: z.enum(["none", "registered", "running", "stopped", "done", "judged"]), trials_done: z.number(), verdict: z.boolean().nullable(), earlier_verdict: z.boolean().nullable(),
    }),
  ),
});
export const intelAllocationsSchema = z.object({
  allocations: z.array(
    z.object({ id: z.number(), method: z.string(), weights: z.record(z.string(), z.number()), cash: z.number(), notes: z.array(z.string()), risk_contribution: z.record(z.string(), z.number()), by: z.string(), at: z.string() }),
  ),
});
export type IntelOverview = z.infer<typeof intelOverviewSchema>;
export type IntelAlpha = z.infer<typeof intelAlphaSchema>;
export type IntelNotes = z.infer<typeof intelNotesSchema>;
export type IntelDefinitions = z.infer<typeof intelDefinitionsSchema>;
export type IntelAllocations = z.infer<typeof intelAllocationsSchema>;

export const intelProgressSchema = z.object({
  jobs: z.array(
    z.object({
      id: z.number(),
      job: z.string(),
      label: z.string(),
      status: z.enum(["RUNNING", "DONE", "FAILED"]),
      done: z.number(),
      total: z.number(),
      phase: z.string(),
      message: z.string(),
      started_at: z.string(),
      updated_at: z.string(),
      elapsed_s: z.number(),
      quiet_s: z.number().nullable(),
      alive: z.boolean().nullable(),
      stalled: z.boolean(),
      estimate: z.enum(["none", "uneven", "waiting", "overrun", "ok"]),
      per_step_s: z.number().nullable(),
      eta_s: z.number().nullable(),
    }),
  ),
});
export type IntelProgress = z.infer<typeof intelProgressSchema>;

export const intelFunnelSchema = z.object({
  stages: z.array(
    z.object({
      key: z.string(),
      title: z.string(),
      unit: z.string(),
      entered: z.number(),
      passed: z.number(),
      connected: z.boolean(),
      note: z.string(),
      dropped: z.array(z.object({ reason: z.string(), count: z.number() })),
    }),
  ),
});
export type IntelFunnel = z.infer<typeof intelFunnelSchema>;

const featureCheckSchema = z.object({ ok: z.boolean(), detail: z.string() });
export const intelFeaturesSchema = z.object({
  features: z.array(
    z.object({
      name: z.string(),
      version: z.string(),
      family: z.string(),
      measures: z.string(),
      unit: z.string(),
      inputs: z.array(z.string()),
      warmup: z.number(),
      status: z.enum(["NOT_REGISTERED", "DRAFT", "USABLE", "BLOCKED"]),
      status_reason: z.string().nullable(),
      validations: z.number(),
      validation: z
        .object({
          passed: z.boolean(),
          reasons: z.array(z.string()),
          at: z.string().nullable(),
          checks: z.object({ coverage: featureCheckSchema, reproducible: featureCheckSchema, stored_match: featureCheckSchema, no_lookahead: featureCheckSchema }),
        })
        .nullable(),
    }),
  ),
});
export type IntelFeatures = z.infer<typeof intelFeaturesSchema>;

export const holdoutSchema = z.object({
  budget: z.number(),
  consumed: z.number(),
  reserved: z.number(),
  left: z.number(),
  previously_tested: z.number(),
  audit_signed: z.boolean(),
  warnings: z.array(z.string()),
  batches: z.array(z.object({ batch_id: z.number(), state: z.string(), candidates: z.number(), frozen_at: z.string().nullable(), first_read: z.boolean(), members: z.array(z.string()) })),
  results: z.array(z.object({ name: z.string(), overall: z.enum(["PASS", "FAIL", "INCOMPLETE"]), checks: z.array(z.object({ gate: z.string(), verdict: z.string(), later: z.boolean() })) })),
  eligible: z.array(z.object({ candidate_id: z.string(), inner: z.object({ passed: z.boolean(), sharpe: z.number().nullable(), index_sharpe: z.number().nullable() }).nullable() })),
  cutoff: z
    .object({
      cutoff_id: z.number(),
      kind: z.string(),
      fired_at: z.string(),
      plan: z
        .object({ members: z.array(z.string()), carry_over: z.array(z.string()), excluded: z.record(z.string(), z.string()), problems: z.array(z.string()), can_freeze: z.boolean() })
        .nullable(),
    })
    .nullable(),
});
export type Holdout = z.infer<typeof holdoutSchema>;
export const holdoutFreezeSchema = z.object({ ok: z.boolean(), batch_id: z.number() });

// ---- NSE smart money: FII/DII flows, most active, delivery, deals, insider, one stock ------------------------------------
const n = z.number().nullable();
export const nseFlowsSchema = z.object({ rows: z.array(z.object({ date: z.string(), fii_buy: n, fii_sell: n, fii_net: n, dii_buy: n, dii_sell: n, dii_net: n })) });
export const nseActiveSchema = z.object({ day: z.string().nullable(), rows: z.array(z.object({ id: n, symbol: z.string(), close: z.number(), volume: z.number(), traded_value: z.number() })) });
export const nseDeliverySchema = z.object({ day: z.string().nullable(), rows: z.array(z.object({ id: n, symbol: z.string(), close: z.number(), volume: z.number(), delivery_qty: z.number(), delivery_pct: z.number() })) });
const dealRow = z.object({ date: z.string(), kind: z.string(), client: z.string(), side: z.string(), quantity: z.number(), price: z.number(), value_cr: z.number(), remarks: z.string().nullable() });
export const nseDealsSchema = z.object({ rows: z.array(dealRow.extend({ id: n, symbol: z.string() })) });
const insiderRow = z.object({ id: n.optional(), did: z.string(), symbol: z.string(), person: z.string(), category: z.string().nullable(), type: z.string().nullable(), mode: z.string().nullable(), quantity: n, value: n, pct_after: n, from_date: z.string().nullable(), intimation_date: z.string().nullable(), broadcast_at: z.string().nullable() });
export const nseInsiderSchema = z.object({ rows: z.array(insiderRow) });
export const nseInstrumentSchema = z.object({
  symbol: z.string(),
  delivery: z.array(z.object({ date: z.string(), close: z.number(), volume: z.number(), delivery_qty: z.number(), delivery_pct: n })),
  holdings: z.array(z.object({ period_end: z.string(), promoter: n, fii: n, dii: n, mf: n, insurance: n, retail: n, public: n, filed_at: z.string().nullable(), revised: z.boolean() })),
  insider: z.array(insiderRow),
  deals: z.array(dealRow),
});
export type NseFlows = z.infer<typeof nseFlowsSchema>;
export type NseInstrument = z.infer<typeof nseInstrumentSchema>;

// ---- Strategy pipeline: every strategy, how far it got and what it returned --------------------------------------------
const stageFigures = z.object({
  passed: z.boolean(),
  failed: z.array(z.string()),
  cagr: z.number().nullable(),
  total_return: z.number().nullable(),
  sharpe: z.number().nullable(),
  max_drawdown: z.number().nullable(),
  benchmark_sharpe: z.number().nullable(),
  window: z.array(z.string()).nullable(),
});
export const pipelineSchema = z.object({
  outer_visible: z.boolean(),
  code_dirty: z.boolean(),
  rows: z.array(
    z.object({
      experiment_id: z.number(),
      name: z.string(),
      family: z.string().nullable(),
      stage: z.enum(["development", "inner", "outer", "paper"]),
      outcome: z.enum(["ready", "stopped", "waiting", "running"]),
      why: z.string(),
      paper: z.string().nullable(),
      development: stageFigures.extend({ oos_sharpe: z.number().nullable() }).nullable(),
      inner: stageFigures.nullable(),
      outer: z.object({ overall: z.enum(["PASS", "FAIL", "INCOMPLETE"]), checks: z.array(z.object({ gate: z.string(), verdict: z.string(), later: z.boolean() })) }).nullable(),
    }),
  ),
});
export type Pipeline = z.infer<typeof pipelineSchema>;
export const pipelineUnrunSchema = z.object({ families: z.array(z.object({ family_id: z.number(), name: z.string(), studies: z.array(z.object({ experiment_id: z.number(), name: z.string(), strategy_id: z.string() })) })) });
