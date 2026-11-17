import { z } from "zod";
import {
  activitySchema,
  backtestPageSchema,
  backtestReportSchema,
  barsSchema,
  benchmarkDetailSchema,
  benchmarkListSchema,
  dashboardSchema,
  healthSchema,
  auditSchema,
  endedSchema,
  inviteLinkSchema,
  inviteResultSchema,
  resetLinkSchema,
  userDetailSchema,
  userListSchema,
  costPreviewSchema,
  costSchedulesSchema,
  brokerAccountSchema,
  kiteConnectionSchema,
  marketCalendarSchema,
  screenerMetaSchema,
  screenerRunSchema,
  paperAccountSchema,
  paperDefinitionsSchema,
  paperOrdersSchema,
  paperRunsSchema,
  paperSummarySchema,
  liveSchema,
  studiesSchema,
  studyResultsSchema,
  studyVerdictSchema,
  studyRunCreatedSchema,
  studyCreatedSchema,
  studyOptionsSchema,
  familyCreatedSchema,
  studySchema,
  signalsSchema,
  stageHistorySchema,
  strategiesSchema,
  strategyCreatedSchema,
  marketIdSchema,
  myDashboardSchema,
  opsDashboardSchema,
  intelAllocationsSchema,
  intelAlphaSchema,
  intelFeaturesSchema,
  intelFunnelSchema,
  intelNotesSchema,
  intelDefinitionsSchema,
  intelOverviewSchema,
  intelProgressSchema,
  kiteLoginSchema,
  kiteSystemSchema,
  kiteUserSchema,
  idSchema,
  noteListSchema,
  staffListSchema,
  tagListSchema,
  tagSchema,
  taskListSchema,
  ticketCreatedSchema,
  ticketDetailSchema,
  ticketListSchema,
  fundamentalsSchema,
  ratiosSchema,
  instrumentDetailSchema,
  instrumentSchema,
  indicatorCatalogSchema,
  indicatorSeriesSchema,
  levelsSchema,
  loginSchema,
  meSchema,
  mfaEnrolSchema,
  okSchema,
  recoverySchema,
  sessionListSchema,
  reviewHistorySchema,
  actionWorklistSchema,
  riskStateSchema,
  holdoutSchema,
  holdoutFreezeSchema,
  reviewListSchema,
  type ReviewDraft,
  type ScreenerCondition,
  type Adjust,
  type Timeframe,
  pipelineSchema,
} from "@/lib/schemas";

/** The browser talks to its own origin; Next proxies /api to the backend, so the session cookie never crosses sites. */
export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? (typeof window === "undefined" ? "http://localhost:3000" : window.location.origin);

/** The CSRF token the server set at sign-in (a cookie the page may read); sent back as a header on every write. */
export function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const hit = document.cookie.split("; ").find((c) => c.startsWith("csrf="));
  return hit ? decodeURIComponent(hit.slice(5)) : "";
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** GET a path, check the HTTP status, then validate the body against a schema. A response that does
 * not match is an error, never silently rendered. */
export async function get<T>(
  path: string,
  schema: z.ZodType<T>,
  params?: Record<string, string | number | undefined>,
  fetcher: typeof fetch = fetch,
): Promise<T> {
  const url = new URL(path, API_URL);
  for (const [k, v] of Object.entries(params ?? {})) {
    if (v !== undefined && v !== "") url.searchParams.set(k, String(v));
  }
  const res = await fetcher(url.toString(), { credentials: "same-origin" });
  if (!res.ok) throw await failure(res);
  const parsed = schema.safeParse(await res.json());
  if (!parsed.success) {
    throw new ApiError(502, `unexpected response shape from ${path}: ${parsed.error.issues[0]?.message ?? "invalid"}`);
  }
  return parsed.data;
}

async function failure(res: Response): Promise<ApiError> {
  let detail = res.statusText;
  try {
    const j = (await res.json()) as { detail?: unknown };
    if (typeof j.detail === "string") detail = j.detail;
  } catch {
    /* keep statusText */
  }
  return new ApiError(res.status, detail);
}

/** Send a JSON body with the CSRF header and validate the answer. A refusal's reason is shown as-is. */
export async function send<T>(
  method: "POST" | "PUT" | "DELETE",
  path: string,
  body: unknown,
  schema: z.ZodType<T>,
  fetcher: typeof fetch = fetch,
): Promise<T> {
  const res = await fetcher(new URL(path, API_URL).toString(), {
    method,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() },
    credentials: "same-origin",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw await failure(res);
  const parsed = schema.safeParse(await res.json());
  if (!parsed.success) throw new ApiError(502, `unexpected response shape from ${path}: ${parsed.error.issues[0]?.message ?? "invalid"}`);
  return parsed.data;
}

/** POST whose answer is not used (review decisions). */
export async function post(path: string, body: unknown, fetcher: typeof fetch = fetch): Promise<void> {
  const res = await fetcher(new URL(path, API_URL).toString(), { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken() }, credentials: "same-origin", body: JSON.stringify(body) });
  if (!res.ok) throw await failure(res);
}

export type { StudySpec } from "@/lib/schemas";
import type { StudySpec, SwitchAction } from "@/lib/schemas";
export type StrategyBody = { name: string; universe: string; max_instruments: number | null; timeframe: string; params: Record<string, number>; screen?: { conditions: { field: string; op: string; value?: unknown }[]; match: string; sort: string; descending: boolean; segments: string[] } };

export const api = {
  login: (email: string, password: string, totpCode?: string) => send("POST", "/api/auth/login", { email, password, totp_code: totpCode || undefined }, loginSchema),
  logout: () => send("POST", "/api/auth/logout", undefined, okSchema),
  me: () => get("/api/auth/me", meSchema),
  changePassword: (current: string, next: string) => send("POST", "/api/auth/password", { current, new: next }, okSchema),
  mfaEnrol: () => send("POST", "/api/auth/mfa/enrol", undefined, mfaEnrolSchema),
  mfaConfirm: (code: string) => send("POST", "/api/auth/mfa/confirm", { code }, recoverySchema),
  mySessions: () => get("/api/auth/sessions", sessionListSchema),
  endSession: (id: string) => send("DELETE", `/api/auth/sessions/${encodeURIComponent(id)}`, undefined, okSchema),
  forgotPassword: (email: string) => send("POST", "/api/auth/forgot", { email }, okSchema),
  acceptInvite: (token: string, password: string) => send("POST", "/api/auth/accept-invite", { token, password }, okSchema),
  resetPassword: (token: string, password: string) => send("POST", "/api/auth/reset-password", { token, password }, okSchema),
  users: (p: { q?: string; role?: string; status?: string; tag?: string; limit?: number; offset?: number }) => get("/api/users", userListSchema, p),
  user: (id: string) => get(`/api/users/${encodeURIComponent(id)}`, userDetailSchema),
  inviteUser: (email: string, name: string, role: string) => send("POST", "/api/users", { email, name, role }, inviteResultSchema),
  renameUser: (id: string, name: string) => send("POST", `/api/users/${encodeURIComponent(id)}/name`, { name }, okSchema),
  setUserRole: (id: string, role: string) => send("POST", `/api/users/${encodeURIComponent(id)}/role`, { role }, okSchema),
  setUserStatus: (id: string, status: string) => send("POST", `/api/users/${encodeURIComponent(id)}/status`, { status }, okSchema),
  sendReset: (id: string) => send("POST", `/api/users/${encodeURIComponent(id)}/reset-password`, undefined, resetLinkSchema),
  resendInvite: (id: string) => send("POST", `/api/users/${encodeURIComponent(id)}/resend-invite`, undefined, inviteLinkSchema),
  resetUserMfa: (id: string) => send("POST", `/api/users/${encodeURIComponent(id)}/reset-mfa`, undefined, okSchema),
  endUserSessions: (id: string) => send("POST", `/api/users/${encodeURIComponent(id)}/end-sessions`, undefined, endedSchema),
  audit: (p: { target_type?: string; target_id?: string; action?: string; limit?: number }) => get("/api/audit", auditSchema, p),
  screenerMeta: () => get("/api/screener/meta", screenerMetaSchema),
  runScreener: (b: { preset?: string; conditions: ScreenerCondition[]; match: "all" | "any"; sort?: string; descending?: boolean; limit?: number }) => send("POST", "/api/screener/run", b, screenerRunSchema),
  marketCalendar: () => get("/api/market/calendar", marketCalendarSchema),
  addMarketSession: (b: { day: string; start: string; end: string; note: string }) => send("POST", "/api/market/sessions", b, marketIdSchema),
  removeMarketSession: (id: number) => send("POST", `/api/market/sessions/${id}/remove`, undefined, okSchema),
  costSchedules: () => get("/api/costs/schedules", costSchedulesSchema),
  costPreview: (p: { broker: string; product: string; side: string; qty: string; price: string; day: string }) => get("/api/costs/preview", costPreviewSchema, p),
  verifyCostSchedule: (id: string, version: string, acceptAssumptions = false) => send("POST", `/api/costs/schedules/${encodeURIComponent(id)}/${encodeURIComponent(version)}/verify`, { accept_assumptions: acceptAssumptions }, okSchema),
  backfillCostSchedule: (id: string, version: string, valid_from: string) => send("POST", `/api/costs/schedules/${encodeURIComponent(id)}/${encodeURIComponent(version)}/backfill`, { valid_from }, okSchema),
  newCostVersion: (id: string, version: string, b: { valid_from: string; valid_until: string | null; note: string; changes: { type: string; side: string; rate_pct?: string | null; amount?: string | null }[] }) => send("POST", `/api/costs/schedules/${encodeURIComponent(id)}/${encodeURIComponent(version)}/new-version`, b, okSchema),
  removeCostSchedule: (id: string, version: string) => send("POST", `/api/costs/schedules/${encodeURIComponent(id)}/${encodeURIComponent(version)}/remove`, undefined, okSchema),
  addCostProvider: (b: { name: string; template_broker: string; valid_from: string; note: string }) => send("POST", "/api/costs/providers", b, okSchema),
  paperAccount: () => get("/api/paper/account", paperAccountSchema),
  holdout: () => get("/api/holdout", holdoutSchema),
  freezeHoldoutBatch: (cutoffId: number) => send("POST", `/api/holdout/cutoffs/${cutoffId}/freeze`, { confirm: true }, holdoutFreezeSchema),
  paperDefinitions: () => get("/api/paper/definitions", paperDefinitionsSchema),
  startPaperDefinition: (experimentId: number) => send("POST", `/api/paper/definitions/${experimentId}/start`, undefined, okSchema),
  createPaperAccount: (b: { initial_cash: string; universe: string; max_instruments: number | null; timeframe: string; params: Record<string, number> }) => send("POST", "/api/paper/account", b, okSchema),
  updatePaperSettings: (b: { enabled?: boolean; universe?: string; max_instruments?: number | null; timeframe?: string; params?: Record<string, number> }) => send("POST", "/api/paper/account/settings", b, okSchema),
  paperSummary: () => get("/api/paper/summary", paperSummarySchema),
  paperOrders: (statuses?: string[]) => get("/api/paper/orders", paperOrdersSchema, statuses ? { status: statuses.join(",") } : undefined),
  approvePaperOrder: (id: string, how: { order_type: "MARKET" | "LIMIT"; limit_price?: string } = { order_type: "MARKET" }) => send("POST", `/api/paper/orders/${encodeURIComponent(id)}/approve`, how, okSchema),
  rejectPaperOrder: (id: string) => send("POST", `/api/paper/orders/${encodeURIComponent(id)}/reject`, undefined, okSchema),
  paperRuns: () => get("/api/paper/runs", paperRunsSchema),
  strategies: () => get("/api/strategies", strategiesSchema),
  createStrategy: (b: StrategyBody) => send("POST", "/api/strategies", b, strategyCreatedSchema),
  pipeline: () => get("/api/pipeline", pipelineSchema),
  submitHoldout: (candidates: string[], declaration: string) => send("POST", "/api/holdout/submit", { candidates, declaration, confirm: true }, holdoutFreezeSchema),
  submitHoldout: (candidates: string[], declaration: string) => send("POST", "/api/holdout/submit", { candidates, declaration, confirm: true }, holdoutFreezeSchema),
  changeStrategy: (id: string, b: StrategyBody) => send("POST", `/api/strategies/${encodeURIComponent(id)}`, b, okSchema),
  strategyStage: (id: string) => get(`/api/strategies/${encodeURIComponent(id)}/stage`, stageHistorySchema),
  moveStrategyStage: (id: string, body: { to_stage: string; reason: string; run_id: number | null }) =>
    send("POST", `/api/strategies/${encodeURIComponent(id)}/stage`, body, z.object({ stage: z.string() })),
  useStrategy: (id: string) => send("POST", `/api/strategies/${encodeURIComponent(id)}/use`, undefined, okSchema),
  studyOptions: () => get("/api/studies/options", studyOptionsSchema),
  studies: () => get("/api/studies", studiesSchema),
  study: (id: number) => get(`/api/studies/${id}`, studySchema),
  studyResults: (id: number) => get(`/api/studies/${id}/results`, studyResultsSchema),
  requestStudyRun: (id: number, chain = false) => send("POST", `/api/studies/${id}/runs`, { chain }, studyRunCreatedSchema),
  studyVerdict: (id: number) => get(`/api/studies/${id}/verdict`, studyVerdictSchema),
  requestStudyVerdict: (id: number) => send("POST", `/api/studies/${id}/verdicts`, undefined, studyRunCreatedSchema),
  requestStudyHoldout: (id: number) => send("POST", `/api/studies/${id}/holdout`, undefined, studyRunCreatedSchema),
  cancelStudyRun: (runId: number) => send("POST", `/api/studies/runs/${runId}/cancel`, undefined, okSchema),
  runDefinitionStudy: (strategyId: string, version: number, familyId = 1, chain = true) => send("POST", `/api/strategies/definitions/${encodeURIComponent(strategyId)}/${version}/study`, { family_id: familyId, chain }, studyRunCreatedSchema.extend({ experiment_id: studyCreatedSchema.shape.experiment_id })),
  registerStudy: (b: StudySpec) => send("POST", "/api/studies", b, studyCreatedSchema),
  startFamily: (b: { name: string; hypothesis: string; justification: string }) => send("POST", "/api/families", b, familyCreatedSchema),
  live: (id: number, timeframe: string, adjust: string) => get(`/api/live/${id}`, liveSchema, { timeframe, adjust }),
  strategySignals: (id: string, p: { instrument_id: number; start: string; end: string; holding: boolean }) => get(`/api/strategies/${encodeURIComponent(id)}/signals`, signalsSchema, { ...p, holding: p.holding ? "true" : "false" }),
  definitionSignals: (strategyId: string, version: number, p: { instrument_id: number; start: string; end: string }) => get(`/api/strategies/definitions/${encodeURIComponent(strategyId)}/${version}/signals`, signalsSchema, p),
  deleteStrategy: (id: string) => send("POST", `/api/strategies/${encodeURIComponent(id)}/delete`, undefined, okSchema),
  myDashboard: () => get("/api/dashboard/me", myDashboardSchema),
  opsDashboard: () => get("/api/dashboard/operations", opsDashboardSchema),
  intelOverview: () => get("/api/intel/overview", intelOverviewSchema),
  intelAlpha: (status?: "CANDIDATE" | "REJECTED") => get("/api/intel/alpha", intelAlphaSchema, status ? { status } : undefined),
  intelDefinitions: () => get("/api/intel/definitions", intelDefinitionsSchema),
  intelNotes: (q: string, kind?: string) => get("/api/intel/notes", intelNotesSchema, { ...(q ? { q } : {}), ...(kind ? { kind } : {}) }),
  intelFeatures: () => get("/api/intel/features", intelFeaturesSchema),
  intelFunnel: () => get("/api/intel/funnel", intelFunnelSchema),
  intelProgress: () => get("/api/intel/progress", intelProgressSchema),
  intelAllocations: () => get("/api/intel/allocations", intelAllocationsSchema),
  kiteConnection: () => get("/api/kite/connection", kiteConnectionSchema),
  brokerAccount: () => get("/api/kite/account", brokerAccountSchema),
  kiteSave: (apiKey: string, apiSecret: string) => send("POST", "/api/kite/credentials", { api_key: apiKey, api_secret: apiSecret }, okSchema),
  kiteRemove: () => send("POST", "/api/kite/credentials/remove", undefined, okSchema),
  kiteStart: () => send("POST", "/api/kite/connect/start", undefined, kiteLoginSchema),
  kiteComplete: (requestToken: string, state: string) => send("POST", "/api/kite/connect/complete", { request_token: requestToken, state }, kiteUserSchema),
  kiteDisconnect: () => send("POST", "/api/kite/disconnect", undefined, okSchema),
  kiteSystem: () => get("/api/kite/system", kiteSystemSchema),
  kiteSetSystem: (enabled: boolean) => send("POST", "/api/kite/system", { enabled }, okSchema),
  notes: (userId: string) => get(`/api/users/${encodeURIComponent(userId)}/notes`, noteListSchema),
  addNote: (userId: string, body: string) => send("POST", `/api/users/${encodeURIComponent(userId)}/notes`, { body }, idSchema),
  addTag: (userId: string, tag: string) => send("POST", `/api/users/${encodeURIComponent(userId)}/tags`, { tag }, tagSchema),
  removeTag: (userId: string, tag: string) => send("POST", `/api/users/${encodeURIComponent(userId)}/tags/remove`, { tag }, okSchema),
  tags: () => get("/api/tags", tagListSchema),
  staff: () => get("/api/staff", staffListSchema),
  tasks: (p: { status?: string; mine?: boolean; user_id?: string }) => get("/api/tasks", taskListSchema, { status: p.status, mine: p.mine ? "true" : undefined, user_id: p.user_id }),
  createTask: (t: { title: string; detail: string; owner_id: string; user_id?: string; due_date?: string }) => send("POST", "/api/tasks", t, idSchema),
  setTaskStatus: (id: string, status: string) => send("POST", `/api/tasks/${encodeURIComponent(id)}/status`, { status }, okSchema),
  tickets: (p: { status?: string; mine?: boolean; assignee_id?: string; limit?: number; offset?: number }) => get("/api/tickets", ticketListSchema, { status: p.status, mine: p.mine ? "true" : undefined, assignee_id: p.assignee_id, limit: p.limit, offset: p.offset }),
  ticket: (id: string) => get(`/api/tickets/${encodeURIComponent(id)}`, ticketDetailSchema),
  createTicket: (subject: string, body: string, priority: string) => send("POST", "/api/tickets", { subject, body, priority }, ticketCreatedSchema),
  replyTicket: (id: string, body: string, internal: boolean) => send("POST", `/api/tickets/${encodeURIComponent(id)}/messages`, { body, internal }, okSchema),
  setTicketStatus: (id: string, status: string) => send("POST", `/api/tickets/${encodeURIComponent(id)}/status`, { status }, okSchema),
  assignTicket: (id: string, assigneeId: string | null) => send("POST", `/api/tickets/${encodeURIComponent(id)}/assign`, { assignee_id: assigneeId }, okSchema),
  health: () => get("/api/health", healthSchema),
  dashboard: () => get("/api/dashboard", dashboardSchema),
  searchInstruments: (q: string) => get("/api/instruments", z.array(instrumentSchema), { q, limit: 15 }),
  instrument: (id: number) => get(`/api/instruments/${id}`, instrumentDetailSchema),
  ratios: (id: number, basis?: string) => get(`/api/instruments/${id}/ratios`, ratiosSchema, basis ? { basis } : {}),
  fundamentals: (id: number, basis?: string) => get(`/api/instruments/${id}/fundamentals`, fundamentalsSchema, { quarters: 12, ...(basis ? { basis } : {}) }),
  bars: (id: number, start: string, end: string, adjust: Adjust, timeframe: Timeframe = "1d") =>
    get(`/api/instruments/${id}/bars`, barsSchema, { start, end, adjust, ...(timeframe === "1d" ? {} : { timeframe }) }),
  riskState: () => get("/api/risk", riskStateSchema),
  riskSwitch: (scope: "own" | "global", action: SwitchAction, reason: string, emergencyOverride = false) => send("POST", scope === "global" ? "/api/risk/switch/global" : "/api/risk/switch", { action, reason, emergency_override: emergencyOverride }, z.object({ effective: z.string() })),
  setRiskLimits: (limits: Record<string, unknown>) => send("PUT", "/api/risk/limits", { limits }, z.object({ limits: z.record(z.unknown()) })),
  actionWorklist: (limit: number, kind?: string) => get("/api/corporate-actions/review", actionWorklistSchema, { limit, kind }),
  reviews: () => get("/api/reviews", reviewListSchema),
  reviewHistory: (id: string) => get(`/api/reviews/${encodeURIComponent(id)}/history`, reviewHistorySchema),
  decideReview: (id: string, d: ReviewDraft) => post(`/api/reviews/${encodeURIComponent(id)}/decisions`, d),
  indicatorCatalog: () => get("/api/indicators", indicatorCatalogSchema),
  indicatorSeries: (id: number, start: string, end: string, adjust: Adjust, names: string, timeframe: Timeframe = "1d") =>
    get(`/api/instruments/${id}/indicators`, indicatorSeriesSchema, { start, end, adjust, names, timeframe }),
  benchmarks: () => get("/api/benchmarks", benchmarkListSchema),
  benchmark: (id: number) => get(`/api/benchmarks/${id}`, benchmarkDetailSchema),
  benchmarkLevels: (id: number, start?: string, maxPoints = 1500) =>
    get(`/api/benchmarks/${id}/levels`, levelsSchema, { start, max_points: maxPoints }),
  backtestReport: (id: number) => get(`/api/backtests/${id}/report`, backtestReportSchema),
  backtests: (limit = 50, offset = 0) => get("/api/backtests", backtestPageSchema, { limit, offset }),
  activity: (limit = 25, offset = 0) => get("/api/system/activity", activitySchema, { limit, offset }),
};
