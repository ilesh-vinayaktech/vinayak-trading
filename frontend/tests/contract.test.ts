import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { z } from "zod";
import {
  activitySchema,
  backtestPageSchema,
  barsSchema,
  benchmarkDetailSchema,
  benchmarkListSchema,
  dashboardSchema,
  healthSchema,
  indicatorCatalogSchema,
  indicatorSeriesSchema,
  instrumentDetailSchema,
  instrumentSchema,
  auditSchema,
  inviteLinkSchema,
  inviteResultSchema,
  kiteConnectionSchema,
  kiteLoginSchema,
  kiteSystemSchema,
  kiteUserSchema,
  idSchema,
  levelsSchema,
  loginSchema,
  noteListSchema,
  staffListSchema,
  tagListSchema,
  taskListSchema,
  ticketCreatedSchema,
  ticketDetailSchema,
  ticketListSchema,
  resetLinkSchema,
  userDetailSchema,
  userListSchema,
  meSchema,
  mfaEnrolSchema,
  recoverySchema,
  sessionListSchema,
} from "@/lib/schemas";

// Fixtures are the API's real responses, written by tests/integration/test_contract.py. If the API
// changes shape that test fails until they are regenerated, and this one fails until the UI schema
// follows - so the UI is checked against what the backend really sends, not against hand-made mocks.
const dir = join(__dirname, "contract");
const load = (name: string): unknown => JSON.parse(readFileSync(join(dir, `${name}.json`), "utf8"));

const CASES: [string, z.ZodTypeAny][] = [
  ["health", healthSchema],
  ["dashboard", dashboardSchema],
  ["instrument_search", z.array(instrumentSchema)],
  ["instrument_detail", instrumentDetailSchema],
  ["bars_none", barsSchema],
  ["bars_split", barsSchema],
  ["bars_5m", barsSchema],
  ["auth_login", loginSchema],
  ["auth_mfa_required", loginSchema],
  ["auth_me", meSchema],
  ["auth_sessions", sessionListSchema],
  ["auth_mfa_enrol", mfaEnrolSchema],
  ["auth_mfa_confirm", recoverySchema],
  ["users_list", userListSchema],
  ["user_detail", userDetailSchema],
  ["user_invite", inviteResultSchema],
  ["user_invite_link", inviteLinkSchema],
  ["user_reset_link", resetLinkSchema],
  ["audit", auditSchema],
  ["notes", noteListSchema],
  ["tags", tagListSchema],
  ["staff", staffListSchema],
  ["tasks", taskListSchema],
  ["task_created", idSchema],
  ["tickets", ticketListSchema],
  ["ticket_created", ticketCreatedSchema],
  ["ticket_requester_view", ticketDetailSchema],
  ["ticket_staff_view", ticketDetailSchema],
  ["kite_connection_empty", kiteConnectionSchema],
  ["kite_connection", kiteConnectionSchema],
  ["kite_login", kiteLoginSchema],
  ["kite_complete", kiteUserSchema],
  ["kite_system", kiteSystemSchema],
  ["benchmark_list", benchmarkListSchema],
  ["benchmark_detail", benchmarkDetailSchema],
  ["benchmark_levels", levelsSchema],
  ["backtests", backtestPageSchema],
  ["activity", activitySchema],
  ["indicator_catalog", indicatorCatalogSchema],
  ["indicator_series", indicatorSeriesSchema],
];

describe("API contract", () => {
  it.each(CASES)("the real %s response parses with the UI schema", (name, schema) => {
    const r = schema.safeParse(load(name));
    expect(r.success, r.success ? "" : JSON.stringify(r.error.issues[0])).toBe(true);
  });

  it("the schemas are strict about what matters: a mangled response is rejected", () => {
    const bad = load("dashboard") as { benchmarks: { series: { gate?: unknown }[] } };
    delete (bad.benchmarks.series[0] as Record<string, unknown>).technically_validated;
    expect(dashboardSchema.safeParse(bad).success).toBe(false);
    const levels = load("benchmark_levels") as Record<string, unknown>;
    delete levels.downsampled;
    expect(levelsSchema.safeParse(levels).success).toBe(false);
  });

  it("session outcomes keep existence, kind and hours apart and never assert a special kind", () => {
    const d = benchmarkDetailSchema.parse(load("benchmark_detail"));
    const rows = d.session_calendar?.this_series?.observed ?? [];
    expect(rows.length).toBeGreaterThan(0);
    for (const r of rows) expect(Object.keys(r)).toEqual(expect.arrayContaining(["existence", "kind", "hours"]));
    expect(JSON.stringify(rows)).not.toMatch(/confirmed special/i);
  });

  it("freshness is judged by sessions, as the fixture's Sunday clock shows", () => {
    const f = dashboardSchema.parse(load("dashboard")).data.freshness;
    expect(f).not.toBeNull();
    expect(f?.expected_latest_session).toBe("2026-11-06"); // the Friday before the fixture's Sunday
    expect(f?.next_session).toBe("2026-11-09");
  });
});
