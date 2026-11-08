// Typed fixtures shaped exactly like the API responses (copied from a real response).

export const dashboard = {
  platform: { state: "UNKNOWN", reason: "the platform state machine is not persisted" },
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
  },
  benchmarks: {
    release: "1.1",
    gate: "disabled",
    series: [
      { id: 1, name: "Nifty 200 Total Return Index (gross)", return_type: "TOTAL_RETURN", ingested: true, technically_validated: true, research_eligible_daily: true, research_eligible_intraday: false, benchmark_gate_eligible: false, eligibility_state: "RESEARCH_ELIGIBLE" },
      { id: 3, name: "Nifty 50 Net Total Return Index", return_type: "NET_TOTAL_RETURN", ingested: true, technically_validated: false, research_eligible_daily: true, research_eligible_intraday: false, benchmark_gate_eligible: false, eligibility_state: "RESEARCH_ELIGIBLE" },
    ],
  },
  corporate_actions: { actions_by_status: { ok: 4294, review: 529 }, resolutions_by_status: { provisional: 10 } },
  research: { backtests: 0, experiments: 0, validation_reports: 0, validation_reports_passed: 0, latest_run: null },
  strategies: { persisted: false, note: "strategy lifecycle states are not stored yet" },
  system: { database: "ok", redis: "not configured", api: "ok", recent_ingestion: [{ id: 1, source: "nse", dataset: "bhav", partition: "2026-11-06", status: "loaded", at: "2026-11-06T18:09:57+00:00", current_status: "loaded", superseded: false }] },
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
    outcome_counts_all_series: { WEEKDAY_RULE_PROVISIONAL: 4505, CONFIRMED_REGULAR: 2268 },
    this_series: { series: "B3_NIFTY50_NET_TRI", observed_outcomes: { WEEKDAY_RULE_PROVISIONAL: 4500, CONFIRMED_REGULAR: 1753 }, missing_outcomes: { EXPECTED_CLOSED_INFERRED: 259 } },
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
