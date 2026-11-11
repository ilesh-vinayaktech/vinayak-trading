import { z } from "zod";
import {
  activitySchema,
  backtestPageSchema,
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
  kiteConnectionSchema,
  kiteLoginSchema,
  kiteSystemSchema,
  kiteUserSchema,
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
  reviewListSchema,
  type ReviewDraft,
  type Adjust,
  type Timeframe,
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
  method: "POST" | "DELETE",
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
  users: (p: { q?: string; role?: string; status?: string; limit?: number; offset?: number }) => get("/api/users", userListSchema, p),
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
  kiteConnection: () => get("/api/kite/connection", kiteConnectionSchema),
  kiteSave: (apiKey: string, apiSecret: string) => send("POST", "/api/kite/credentials", { api_key: apiKey, api_secret: apiSecret }, okSchema),
  kiteRemove: () => send("POST", "/api/kite/credentials/remove", undefined, okSchema),
  kiteStart: () => send("POST", "/api/kite/connect/start", undefined, kiteLoginSchema),
  kiteComplete: (requestToken: string, state: string) => send("POST", "/api/kite/connect/complete", { request_token: requestToken, state }, kiteUserSchema),
  kiteDisconnect: () => send("POST", "/api/kite/disconnect", undefined, okSchema),
  kiteSystem: () => get("/api/kite/system", kiteSystemSchema),
  kiteSetSystem: (enabled: boolean) => send("POST", "/api/kite/system", { enabled }, okSchema),
  health: () => get("/api/health", healthSchema),
  dashboard: () => get("/api/dashboard", dashboardSchema),
  searchInstruments: (q: string) => get("/api/instruments", z.array(instrumentSchema), { q, limit: 15 }),
  instrument: (id: number) => get(`/api/instruments/${id}`, instrumentDetailSchema),
  bars: (id: number, start: string, end: string, adjust: Adjust, timeframe: Timeframe = "1d") =>
    get(`/api/instruments/${id}/bars`, barsSchema, { start, end, adjust, ...(timeframe === "1d" ? {} : { timeframe }) }),
  reviews: () => get("/api/reviews", reviewListSchema),
  reviewHistory: (id: string) => get(`/api/reviews/${encodeURIComponent(id)}/history`, reviewHistorySchema),
  decideReview: (id: string, d: ReviewDraft) => post(`/api/reviews/${encodeURIComponent(id)}/decisions`, d),
  indicatorCatalog: () => get("/api/indicators", indicatorCatalogSchema),
  indicatorSeries: (id: number, start: string, end: string, adjust: Adjust, names: string) =>
    get(`/api/instruments/${id}/indicators`, indicatorSeriesSchema, { start, end, adjust, names }),
  benchmarks: () => get("/api/benchmarks", benchmarkListSchema),
  benchmark: (id: number) => get(`/api/benchmarks/${id}`, benchmarkDetailSchema),
  benchmarkLevels: (id: number, start?: string, maxPoints = 1500) =>
    get(`/api/benchmarks/${id}/levels`, levelsSchema, { start, max_points: maxPoints }),
  backtests: (limit = 50, offset = 0) => get("/api/backtests", backtestPageSchema, { limit, offset }),
  activity: (limit = 25, offset = 0) => get("/api/system/activity", activitySchema, { limit, offset }),
};
