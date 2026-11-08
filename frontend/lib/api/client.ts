import { z } from "zod";
import {
  activitySchema,
  backtestPageSchema,
  barsSchema,
  benchmarkDetailSchema,
  benchmarkListSchema,
  dashboardSchema,
  healthSchema,
  instrumentDetailSchema,
  instrumentSchema,
  levelsSchema,
  type Adjust,
} from "@/lib/schemas";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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
  const res = await fetcher(url.toString());
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  const parsed = schema.safeParse(await res.json());
  if (!parsed.success) {
    throw new ApiError(502, `unexpected response shape from ${path}: ${parsed.error.issues[0]?.message ?? "invalid"}`);
  }
  return parsed.data;
}

export const api = {
  health: () => get("/api/health", healthSchema),
  dashboard: () => get("/api/dashboard", dashboardSchema),
  searchInstruments: (q: string) => get("/api/instruments", z.array(instrumentSchema), { q, limit: 15 }),
  instrument: (id: number) => get(`/api/instruments/${id}`, instrumentDetailSchema),
  bars: (id: number, start: string, end: string, adjust: Adjust) =>
    get(`/api/instruments/${id}/bars`, barsSchema, { start, end, adjust }),
  benchmarks: () => get("/api/benchmarks", benchmarkListSchema),
  benchmark: (id: number) => get(`/api/benchmarks/${id}`, benchmarkDetailSchema),
  benchmarkLevels: (id: number, start?: string, maxPoints = 1500) =>
    get(`/api/benchmarks/${id}/levels`, levelsSchema, { start, max_points: maxPoints }),
  backtests: (limit = 50, offset = 0) => get("/api/backtests", backtestPageSchema, { limit, offset }),
  activity: (limit = 25, offset = 0) => get("/api/system/activity", activitySchema, { limit, offset }),
};
