import { describe, expect, it } from "vitest";
import { z } from "zod";
import { ApiError, get } from "@/lib/api/client";
import { fmtDateTime, fmtDuration, fmtInt, humanize, plotNumber, shortHash } from "@/lib/formatting";

const schema = z.object({ n: z.string() });
const reply = (body: unknown, status = 200) => async () => new Response(JSON.stringify(body), { status });

describe("get", () => {
  it("returns the validated body and drops empty query parameters", async () => {
    let seen = "";
    const fetcher = (async (u: RequestInfo | URL) => {
      seen = String(u);
      return new Response(JSON.stringify({ n: "1.50" }));
    }) as typeof fetch;
    const out = await get("/api/x", schema, { a: "b", empty: "", skip: undefined, n: 3 }, fetcher);
    expect(out).toEqual({ n: "1.50" });
    expect(new URL(seen).searchParams.toString()).toBe("a=b&n=3");
  });

  it("turns an HTTP error into an ApiError carrying the server's detail", async () => {
    await expect(get("/api/x", schema, {}, reply({ detail: "no instrument 9" }, 404) as typeof fetch)).rejects.toMatchObject({ status: 404, message: "no instrument 9" });
  });

  it("keeps the status text when the error body is not JSON", async () => {
    const f = (async () => new Response("boom", { status: 500, statusText: "Server Error" })) as typeof fetch;
    await expect(get("/api/x", schema, {}, f)).rejects.toMatchObject({ status: 500, message: "Server Error" });
  });

  it("never renders a response that does not match the schema", async () => {
    const err = await get("/api/x", schema, {}, reply({ n: 5 }) as typeof fetch).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(502);
    expect((err as ApiError).message).toContain("unexpected response shape");
  });
});

describe("formatting", () => {
  it("formats display values without recomputing them", () => {
    expect(fmtInt(3188251)).toBe("31,88,251");
    expect(fmtDateTime("2026-11-07T10:00:00+00:00")).toBe("2026-11-07 10:00 UTC");
    expect(fmtDateTime("not a date")).toBe("not a date");
    expect(shortHash("abcdef0123456789", 6)).toBe("abcdef");
    expect(shortHash("abc")).toBe("abc");
    expect(humanize("INTRADAY_RESEARCH")).toBe("intraday research");
    expect(plotNumber("1339.800")).toBe(1339.8);
  });
});

describe("durations", () => {
  it("shows the two most useful units", () => {
    expect([0, 40, 59.6, 60, 750, 3600, 7800, 86400, 98000, 190000].map(fmtDuration)).toEqual([
      "0 s", "40 s", "1 min", "1 min", "13 min", "1 h", "2 h 10 min", "1 d", "1 d 3 h", "2 d 4 h",
    ]);
  });
  it("never goes negative", () => {
    expect(fmtDuration(-5)).toBe("0 s");
  });
});
