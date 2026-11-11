import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { z } from "zod";
import AccountSecurity from "@/app/account/security/page";
import LoginPage from "@/app/login/page";
import { Providers } from "@/app/providers";
import { Shell } from "@/components/layout/Shell";
import { csrfToken, send } from "@/lib/api/client";
import { safeNext } from "@/lib/auth";

const nav = vi.hoisted(() => ({ replace: vi.fn(), path: "/dashboard", search: "" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  usePathname: () => nav.path,
  useSearchParams: () => new URLSearchParams(nav.search),
}));
vi.mock("qrcode", () => ({ default: { toDataURL: vi.fn(async () => "data:image/png;base64,AAAA") } }));

type Call = { method: string; path: string; headers: Record<string, string>; body: unknown };
type Reply = unknown | ((call: Call) => unknown);
const user = (over: Record<string, unknown> = {}) => ({
  id: "u1", email: "jane@example.com", name: "Jane Roe", role: "TRADER",
  permissions: ["research:read", "kite:own", "strategy:own", "tickets:own"],
  mfa_enabled: false, enrolment_required: false, must_change_password: false, ...over,
});

/** A scripted backend: "METHOD /path" -> body, or [status, body], or a function of the request. */
function backend(table: Record<string, Reply>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const call: Call = { method: init?.method ?? "GET", path: url.pathname, headers: (init?.headers ?? {}) as Record<string, string>, body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const hit = table[`${call.method} ${call.path}`];
    if (hit === undefined) return new Response(JSON.stringify({ detail: "no route" }), { status: 404 });
    const out = typeof hit === "function" ? (hit as (c: Call) => unknown)(call) : hit;
    const [status, body] = Array.isArray(out) && typeof out[0] === "number" ? (out as [number, unknown]) : [200, out];
    return new Response(JSON.stringify(body), { status });
  });
  return calls;
}

const mount = (ui: React.ReactElement) => render(<Providers>{ui}</Providers>);

beforeEach(() => {
  nav.replace.mockReset();
  nav.path = "/dashboard";
  nav.search = "";
  document.cookie = "csrf=; max-age=0";
});
afterEach(() => vi.unstubAllGlobals());

describe("CSRF and the client", () => {
  it("reads the token the server set and sends it with every write, and surfaces the server's reason", async () => {
    expect(csrfToken()).toBe("");
    document.cookie = "csrf=tok%2B123";
    expect(csrfToken()).toBe("tok+123");
    const calls = backend({ "POST /api/x": { ok: true }, "DELETE /api/y": [403, { detail: "CSRF check failed" }] });
    await send("POST", "/api/x", { a: 1 }, z.object({ ok: z.boolean() }));
    expect(calls[0]?.headers["X-CSRF-Token"]).toBe("tok+123");
    await expect(send("DELETE", "/api/y", undefined, z.object({}))).rejects.toMatchObject({ status: 403, message: "CSRF check failed" });
    backend({ "POST /api/z": { nope: 1 } });
    await expect(send("POST", "/api/z", {}, z.object({ ok: z.boolean() }))).rejects.toMatchObject({ status: 502 });
  });

  it("only follows same-site paths after sign-in", () => {
    expect(safeNext("/data/instruments")).toBe("/data/instruments");
    for (const bad of [null, "", "https://evil.example", "//evil.example", "/login", "/login?x=1", "javascript:alert(1)"]) expect(safeNext(bad)).toBe("/dashboard");
  });
});

describe("sign-in page", () => {
  const fill = (email = "jane@example.com", password = "violet-harbor-lantern-42") => {
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: email } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: password } });
  };

  it("shows the server's message for bad credentials and stays on the page", async () => {
    backend({ "GET /api/auth/me": [401, { detail: "Not signed in" }], "POST /api/auth/login": [401, { detail: "Invalid email or password." }] });
    mount(<LoginPage />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toBe("Invalid email or password.");
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("shows a lockout and a network failure as readable messages", async () => {
    backend({ "GET /api/auth/me": [401, {}], "POST /api/auth/login": [429, { detail: "Too many attempts. Try again in a few minutes." }] });
    mount(<LoginPage />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Too many attempts");
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("network down");
    });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Could not reach the server"));
  });

  it("asks for the authentication code as a second step, then continues to the page it came for", async () => {
    nav.search = "next=%2Fdata%2Finstruments";
    const calls = backend({
      "GET /api/auth/me": [401, {}],
      "POST /api/auth/login": (c: Call) => ((c.body as { totp_code?: string }).totp_code ? { user: user({ role: "ADMIN", mfa_enabled: true }) } : { mfa_required: true }),
    });
    mount(<LoginPage />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    const code = await screen.findByLabelText("Authentication code");
    expect(screen.getByLabelText("Email")).toHaveAttribute("readonly");
    fireEvent.change(code, { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/data/instruments"));
    const logins = calls.filter((c) => c.path === "/api/auth/login");
    expect(logins[0]?.body).toMatchObject({ email: "jane@example.com" });
    expect(logins[1]?.body).toMatchObject({ totp_code: "123456" });
  });

  it("clears a wrong code so it can be retyped", async () => {
    backend({
      "GET /api/auth/me": [401, {}],
      "POST /api/auth/login": (c: Call) => ((c.body as { totp_code?: string }).totp_code ? [401, { detail: "That code is not valid." }] : { mfa_required: true }),
    });
    mount(<LoginPage />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    fireEvent.change(await screen.findByLabelText("Authentication code"), { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify" }));
    expect((await screen.findByRole("alert")).textContent).toBe("That code is not valid.");
    expect(screen.getByLabelText("Authentication code")).toHaveValue("");
  });

  it("sends an account that must finish setup to the security page, not the dashboard", async () => {
    backend({ "GET /api/auth/me": [401, {}], "POST /api/auth/login": { user: user({ role: "ADMIN", enrolment_required: true }) } });
    mount(<LoginPage />);
    fill();
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/account/security"));
  });
});

describe("app shell", () => {
  it("sends a visitor who is not signed in to the sign-in page and shows none of the app", async () => {
    nav.path = "/data/instruments";
    backend({ "GET /api/auth/me": [401, { detail: "Not signed in" }] });
    mount(<Shell>secret page</Shell>);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login?next=%2Fdata%2Finstruments"));
    expect(screen.queryByText("secret page")).not.toBeInTheDocument();
  });

  it("renders the sign-in page without the app chrome", () => {
    nav.path = "/login";
    backend({ "GET /api/auth/me": [401, {}] });
    mount(<Shell>the form</Shell>);
    expect(screen.getByText("the form")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });

  it("hides what a role would be refused and shows who is signed in", async () => {
    backend({ "GET /api/auth/me": { user: user({ role: "VIEWER", permissions: ["research:read", "tickets:own"] }) }, "GET /api/health": { api: "ok", database: "ok", redis: "x" } });
    mount(<Shell>page body</Shell>);
    const main = within(await screen.findByRole("navigation", { name: "Main" }));
    expect(main.getByText("Data Explorer")).toBeInTheDocument();
    expect(main.queryByText("Reviews")).not.toBeInTheDocument();
    expect(main.queryByText("System Activity")).not.toBeInTheDocument();
    expect(screen.getByTestId("who").textContent).toBe("Jane Roe · VIEWER");
    expect(screen.getByText("page body")).toBeInTheDocument();
  });

  it("shows operations pages to a role that holds ops:read", async () => {
    backend({ "GET /api/auth/me": { user: user({ role: "OPERATOR", permissions: ["research:read", "ops:read"] }) }, "GET /api/health": { api: "ok", database: "ok", redis: "x" } });
    mount(<Shell>x</Shell>);
    const main = within(await screen.findByRole("navigation", { name: "Main" }));
    expect(main.getByText("Reviews")).toBeInTheDocument();
    expect(main.getByText("System Activity")).toBeInTheDocument();
  });

  it("keeps an account that must enrol a second factor on the security page and shows no navigation", async () => {
    nav.path = "/dashboard";
    backend({ "GET /api/auth/me": { user: user({ role: "ADMIN", enrolment_required: true }) } });
    mount(<Shell>dashboard</Shell>);
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/account/security"));
    expect(screen.queryByText("dashboard")).not.toBeInTheDocument();
    nav.path = "/account/security";
    nav.replace.mockReset();
    mount(<Shell>setup</Shell>);
    expect(await screen.findByText("setup")).toBeInTheDocument();
    expect(nav.replace).not.toHaveBeenCalled();
  });

  it("signs out on the server with the CSRF header and forgets the user", async () => {
    document.cookie = "csrf=abc123";
    const calls = backend({ "GET /api/auth/me": { user: user() }, "GET /api/health": { api: "ok", database: "ok", redis: "x" }, "POST /api/auth/logout": { ok: true } });
    mount(<Shell>page</Shell>);
    fireEvent.click(await screen.findByRole("button", { name: "Account menu" }));
    fireEvent.click(screen.getByRole("menuitem", { name: "Sign out" }));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/login?next=%2Fdashboard"));
    expect(calls.find((c) => c.path === "/api/auth/logout")?.headers["X-CSRF-Token"]).toBe("abc123");
  });
});

describe("account security page", () => {
  const session = (id: string, current: boolean) => ({ session_id: id, created_at: "2026-11-11T10:00:00Z", last_seen_at: "2026-11-11T10:05:00Z", expires_at: "2026-11-11T22:00:00Z", ip: "203.0.113.7", user_agent: "Firefox", current });

  it("changes the password, refusing a mismatch before it is sent", async () => {
    document.cookie = "csrf=t";
    const calls = backend({ "GET /api/auth/me": { user: user() }, "GET /api/auth/sessions": { sessions: [] }, "POST /api/auth/password": { ok: true } });
    mount(<AccountSecurity />);
    fireEvent.change(await screen.findByLabelText("Current password"), { target: { value: "violet-harbor-lantern-42" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "amber-meadow-kettle-77" } });
    fireEvent.change(screen.getByLabelText("Repeat new password"), { target: { value: "different" } });
    expect(screen.getByText("The passwords differ.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change password" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Repeat new password"), { target: { value: "amber-meadow-kettle-77" } });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect((await screen.findByRole("status")).textContent).toBe("Password changed.");
    expect(calls.find((c) => c.path === "/api/auth/password")?.body).toEqual({ current: "violet-harbor-lantern-42", new: "amber-meadow-kettle-77" });
  });

  it("shows the server's reason when the password is refused", async () => {
    backend({ "GET /api/auth/me": { user: user() }, "GET /api/auth/sessions": { sessions: [] }, "POST /api/auth/password": [422, { detail: "the current password is not correct" }] });
    mount(<AccountSecurity />);
    fireEvent.change(await screen.findByLabelText("Current password"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "amber-meadow-kettle-77" } });
    fireEvent.change(screen.getByLabelText("Repeat new password"), { target: { value: "amber-meadow-kettle-77" } });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect((await screen.findByRole("alert")).textContent).toBe("the current password is not correct");
  });

  it("sets up two-factor authentication with a QR code and shows the recovery codes once", async () => {
    const codes = Array.from({ length: 10 }, (_, i) => `abcde-fgh${i}k`);
    let enabled = false;
    backend({
      "GET /api/auth/me": () => ({ user: user({ mfa_enabled: enabled }) }),
      "GET /api/auth/sessions": { sessions: [] },
      "POST /api/auth/mfa/enrol": { secret: "JBSWY3DPEHPK3PXP", uri: "otpauth://totp/x?secret=JBSWY3DPEHPK3PXP" },
      "POST /api/auth/mfa/confirm": () => {
        enabled = true;
        return { recovery_codes: codes };
      },
    });
    mount(<AccountSecurity />);
    fireEvent.click(await screen.findByRole("button", { name: "Set up two-factor authentication" }));
    expect(await screen.findByAltText("QR code for your authenticator app")).toHaveAttribute("src", "data:image/png;base64,AAAA");
    expect(screen.getByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Code from the app"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    const list = within(await screen.findByRole("list", { name: "Recovery codes" }));
    expect(list.getAllByRole("listitem")).toHaveLength(10);
  });

  it("reports a wrong confirmation code", async () => {
    backend({
      "GET /api/auth/me": { user: user() },
      "GET /api/auth/sessions": { sessions: [] },
      "POST /api/auth/mfa/enrol": { secret: "S", uri: "otpauth://x" },
      "POST /api/auth/mfa/confirm": [422, { detail: "that code is not right" }],
    });
    mount(<AccountSecurity />);
    fireEvent.click(await screen.findByRole("button", { name: "Set up two-factor authentication" }));
    fireEvent.change(await screen.findByLabelText("Code from the app"), { target: { value: "000000" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect((await screen.findByRole("alert")).textContent).toBe("that code is not right");
  });

  it("shows an enrolled user's status", async () => {
    backend({ "GET /api/auth/me": { user: user({ mfa_enabled: true }) }, "GET /api/auth/sessions": { sessions: [] } });
    mount(<AccountSecurity />);
    expect(await screen.findByText("On")).toBeInTheDocument();
  });

  it("shows a required-setup banner for an account that must enrol", async () => {
    backend({ "GET /api/auth/me": { user: user({ role: "ADMIN", enrolment_required: true }) } });
    mount(<AccountSecurity />);
    expect(await screen.findByText("Set up two-factor authentication to continue.")).toBeInTheDocument();
  });

  it("lists active sessions and ends another one but never offers to end the current one", async () => {
    document.cookie = "csrf=t";
    const calls = backend({
      "GET /api/auth/me": { user: user() },
      "GET /api/auth/sessions": { sessions: [session("s1", true), session("s2", false)] },
      "DELETE /api/auth/sessions/s2": { ok: true },
    });
    mount(<AccountSecurity />);
    expect(await screen.findByText("this session")).toBeInTheDocument();
    const ends = screen.getAllByRole("button", { name: "End session" });
    expect(ends).toHaveLength(1);
    fireEvent.click(ends[0] as HTMLElement);
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.path === "/api/auth/sessions/s2")).toBe(true));
  });
});
