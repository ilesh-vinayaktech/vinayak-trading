import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";
import { config, middleware } from "@/middleware";

const req = (path: string, cookie?: string) => new NextRequest(`http://localhost:3000${path}`, { headers: cookie ? { cookie } : {} });

describe("page gate", () => {
  it("sends a browser without a session cookie to sign in, remembering where it was going", () => {
    const res = middleware(req("/data/instruments?x=1"));
    expect(res.status).toBe(307);
    expect(res.headers.get("location")).toBe("http://localhost:3000/login?next=%2Fdata%2Finstruments%3Fx%3D1");
  });

  it("lets through the sign-in page and any browser that holds a session cookie (plain or host-prefixed)", () => {
    for (const r of [req("/login"), req("/forgot-password"), req("/accept-invite?token=x"), req("/reset-password?token=x"), req("/dashboard", "session=abc"), req("/dashboard", "__Host-session=abc")]) {
      expect(middleware(r).headers.get("location")).toBeNull();
    }
  });

  it("leaves the API, framework files and the icon alone", () => {
    const m = new RegExp(`^${config.matcher[0]}$`);
    expect(["/dashboard", "/login", "/account/security"].every((p) => m.test(p))).toBe(true);
    expect(["/api/health", "/_next/static/x.js", "/icon.svg"].some((p) => m.test(p))).toBe(false);
  });
});
