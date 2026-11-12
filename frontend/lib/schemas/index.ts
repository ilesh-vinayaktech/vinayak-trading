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

export const TIMEFRAMES = ["1m", "3m", "5m", "10m", "15m", "30m", "45m", "1h", "2h", "3h", "4h", "1d", "1w", "1mo"] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];

export const barsSchema = z.object({
  adjust: z.enum(["none", "split", "total_return"]),
  timeframe: z.enum(TIMEFRAMES),
  adjustment_version: z.string(),
  clean: z.boolean(),
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
      params: paperParamsSchema,
    })
    .nullable(),
});
export const paperSummarySchema = z.object({
  equity: decimal,
  cash: decimal,
  invested: decimal,
  pnl: z.object({ realized: decimal, unrealized: decimal, fees: decimal, net: decimal }),
  positions: z.array(z.object({ instrument_id: z.number(), symbol: z.string(), qty: decimal, avg_cost: decimal, last_price: decimal, value: decimal, unrealized: decimal })),
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
});
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
