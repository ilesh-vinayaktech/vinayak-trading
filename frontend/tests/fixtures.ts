// Typed fixtures shaped exactly like the API responses (copied from a real response).

export const dashboard = {
  platform: { status: "ATTENTION", reasons: [
    { level: "attention", text: "No Kite data feed is connected: the loaders and the live feed cannot run." },
    { level: "attention", text: "11 scheduled jobs have never run: kite-login-reminder, gap-nightly, gap-weekly and 8 more." },
  ] },
  data: {
    bars: 3188251,
    instruments_with_bars: 2648,
    first_date: "2019-10-01",
    last_date: "2026-11-06",
    bars_on_last_date: 1710,
    bars_on_previous_date: 1705,
    partitions: { loaded: 1763, not_published: 100 },
    quarantined_partitions: [],
    instruments: { active: 2630, delisted: 18 },
    freshness: { latest_bar_session: "2026-11-06", expected_latest_session: "2026-11-06", next_session: "2026-11-09", sessions_behind: 0, status: "CURRENT", basis: "sessions are weekdays minus learned holidays" },
  },
  benchmarks: {
    release: "1.1",
    gate: "disabled",
    series: [
      { id: 1, name: "Nifty 200 Total Return Index (gross)", return_type: "TOTAL_RETURN", ingested: true, technically_validated: true, research_eligible_daily: true, research_eligible_intraday: false, benchmark_gate_eligible: false, eligibility_state: "RESEARCH_ELIGIBLE" },
      { id: 3, name: "Nifty 50 Net Total Return Index", return_type: "NET_TOTAL_RETURN", ingested: true, technically_validated: false, research_eligible_daily: true, research_eligible_intraday: false, benchmark_gate_eligible: false, eligibility_state: "RESEARCH_ELIGIBLE" },
    ],
  },
  corporate_actions: {
    actions_by_status: { ok: 4294, review: 529 },
    resolutions_by_status: { provisional: 10, no_adjustment_verified: 24, ignored_with_reason: 2 },
    total_events: 4823,
    verified: 4294,
    pending_review: 529,
    review_without_any_resolution: 493,
    provisional_adjustments: 10,
    no_adjustment_verified: 24,
    ignored_with_reason: 2,
  },
  research: { backtests: 0, experiments: 0, validation_reports: 0, validation_reports_passed: 0, latest_run: null },
  strategies: { persisted: false, note: "strategy lifecycle states are not stored yet" },
  jobs: [
    { name: "bhavcopy-daily", description: "Load the daily bhavcopy", calendar: "Mon..Fri *-*-* 18:30 Asia/Kolkata",
      last_run: { started_at: "2026-11-13T12:45:00+00:00", finished_at: "2026-11-13T12:45:30+00:00", status: "ok", attempts: 1, detail: "" }, last_success_at: "2026-11-13T12:45:30+00:00" },
    { name: "kite-reconcile", description: "Compare Kite daily candles with bhavcopy", calendar: "Mon..Fri *-*-* 20:00 Asia/Kolkata",
      last_run: { started_at: "2026-11-13T14:30:00+00:00", finished_at: "2026-11-13T14:31:00+00:00", status: "failed", attempts: 3, detail: "reconcile_kite_prices.py exited 3" }, last_success_at: "2026-11-12T14:31:00+00:00" },
    { name: "fundamentals-daily", description: "Latest results", calendar: "Mon..Fri *-*-* 21:00 Asia/Kolkata", last_run: null, last_success_at: null },
  ],
  system: { database: "ok", redis: "not configured", api: "ok", recent_ingestion: [{ id: 1, source: "nse", dataset: "bhav", partition: "2026-11-06", status: "loaded", at: "2026-11-06T18:09:57+00:00" }] },
};

export const benchmarkDetail = {
  id: 3,
  name: "Nifty 50 Net Total Return Index",
  index_symbol: "NIFTY 50",
  return_type: "NET_TOTAL_RETURN",
  methodology_version: "Sep 2026",
  first: "2000-01-03",
  last: "2026-11-06",
  observations: 6676,
  dataset_hash: "d2b9cf96ffd915df4c71d5541d112f9671ebb354ffb2bf030178486d54462819",
  eligibility: {
    series: "B3_NIFTY50_NET_TRI",
    state: "RESEARCH_ELIGIBLE",
    uses: {
      DAILY_RESEARCH: { eligible: true, blockers: [] },
      INTRADAY_RESEARCH: { eligible: false, blockers: ["U02: Historical session hours are not verified"] },
      BENCHMARK_GATE: { eligible: false, blockers: ["technical validation did not pass"] },
    },
  },
  release: "1.1",
  gate: "disabled",
  findings: [
    { id: "U02", title: "Historical session hours are not verified", severity: "HIGH", status: "UNRESOLVED", category: "session-hours", detail: "hours are assumed", blocks: ["INTRADAY_RESEARCH"] },
    { id: "U01", title: "2022-08-08 recovered", severity: "INFO", status: "RESOLVED", category: "session-evidence", detail: "resolved", blocks: [] },
  ],
  validations: [
    { validation_id: 3, created_at: "2026-11-07T09:00:00+00:00", passed: true, covers_current_dataset: true, report_version: "legacy (pass/fail only, pre-states)", technical_validation_passed: true, check_states: null, owner_accepted_findings: [], unresolved: [] },
    { validation_id: 4, created_at: "2026-11-07T10:00:00+00:00", passed: false, covers_current_dataset: true, report_version: "2", technical_validation_passed: false, check_states: { net_never_gains_on_gross: "UNRESOLVED" }, owner_accepted_findings: [{ check: "net_never_gains_on_gross", state: "UNRESOLVED", label: "UNRESOLVED_DIVIDEND_ASSOCIATED_ANOMALY" }], unresolved: [] },
  ],
  session_calendar: {
    calendar_version: { sessions_file_sha256: "abc" },
    evidence: ["2019-10-01", "2026-11-06"],
    all_series: [
      { code: "CONFIRMED_SPECIAL", count: 32, label: "session existence confirmed by an exchange file; kind not confirmed", existence: "CONFIRMED", kind: "UNCONFIRMED", hours: "UNKNOWN" },
    ],
    this_series: {
      series: "B3_NIFTY50_NET_TRI",
      observed: [
        { code: "CONFIRMED_SPECIAL", count: 30, label: "session existence confirmed by an exchange file; kind not confirmed", existence: "CONFIRMED", kind: "UNCONFIRMED", hours: "UNKNOWN" },
        { code: "WEEKDAY_RULE_PROVISIONAL", count: 4500, label: "weekday by calendar rule only; no exchange evidence", existence: "PROVISIONAL", kind: "REGULAR_BY_RULE", hours: "ASSUMED_CURRENT_SCHEDULE" },
      ],
      missing: [{ code: "EXPECTED_CLOSED_INFERRED", count: 259, label: "no value; exchange files either side chain over the day", existence: null, kind: null, hours: null }],
    },
    listed_special_sessions: { listed_sessions: 32, kind: { UNCONFIRMED: 32 }, opening_time: { UNKNOWN: 32 }, closing_time: { UNKNOWN: 32 } },
    historical_session_hours: "no historical session hours are held as evidence",
  },
  instrument_level_blocked_dates: [],
};

export function route(table: Record<string, unknown>) {
  return async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    const hit = table[url.pathname];
    if (hit === undefined) return new Response(JSON.stringify({ detail: `no route ${url.pathname}` }), { status: 404 });
    return new Response(JSON.stringify(hit), { status: 200, headers: { "content-type": "application/json" } });
  };
}
