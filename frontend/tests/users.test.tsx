import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AcceptInvite from "@/app/accept-invite/page";
import AuditPage from "@/app/audit/page";
import ForgotPassword from "@/app/forgot-password/page";
import ResetPassword from "@/app/reset-password/page";
import UserProfile from "@/app/users/[id]/page";
import UsersPage from "@/app/users/page";
import { Providers } from "@/app/providers";
import { Shell } from "@/components/layout/Shell";
import { actionLabel } from "@/components/users/format";
import { isPublicPath } from "@/lib/publicPaths";

const nav = vi.hoisted(() => ({ replace: vi.fn(), path: "/users", search: "", id: "u2" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  usePathname: () => nav.path,
  useSearchParams: () => new URLSearchParams(nav.search),
  useParams: () => ({ id: nav.id }),
}));

type Call = { method: string; path: string; search: URLSearchParams; headers: Record<string, string>; body: unknown };
type Reply = unknown | ((call: Call) => unknown);
const me = (over: Record<string, unknown> = {}) => ({
  user: { id: "u1", email: "boss@example.com", name: "The Boss", role: "ADMIN", permissions: ["research:read", "users:read", "users:write", "roles:write", "audit:read", "ops:read"], mfa_enabled: true, enrolment_required: false, must_change_password: false, ...over },
});
const row = (over: Record<string, unknown> = {}) => ({ id: "u2", email: "jane@example.com", name: "Jane Roe", role: "TRADER", status: "ACTIVE", mfa_enabled: false, last_login_at: "2026-11-10T09:30:00Z", created_at: "2026-11-01T08:00:00Z", ...over });
const detail = (over: Record<string, unknown> = {}) => ({ ...row(), must_change_password: false, password_changed_at: "2026-11-01T08:00:00Z", created_by: "The Boss", recovery_codes_left: 0, active_sessions: 2, ...over });
const event = (id: number, action: string, actor = "The Boss") => ({ id, at: "2026-11-11T10:00:00Z", actor_user_id: "u1", actor, action, target_type: "user", target_id: "u2", detail: {}, ip: "203.0.113.7" });

function backend(table: Record<string, Reply>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const call: Call = { method: init?.method ?? "GET", path: url.pathname, search: url.searchParams, headers: (init?.headers ?? {}) as Record<string, string>, body: init?.body ? JSON.parse(String(init.body)) : undefined };
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
  nav.path = "/users";
  nav.search = "";
  nav.id = "u2";
  document.cookie = "csrf=tok";
  Object.assign(navigator, { clipboard: { writeText: vi.fn(async () => undefined) } });
});
afterEach(() => vi.unstubAllGlobals());

describe("helpers", () => {
  it("knows the signed-out pages and words an audit action for people", () => {
    for (const p of ["/login", "/forgot-password", "/accept-invite", "/reset-password"]) expect(isPublicPath(p)).toBe(true);
    for (const p of ["/users", "/dashboard", "/login/x"]) expect(isPublicPath(p)).toBe(false);
    expect(actionLabel("user.role_changed")).toBe("Role changed");
    expect(actionLabel("auth.login")).toBe("Login");
    expect(actionLabel("plain")).toBe("Plain");
  });
});

describe("user directory", () => {
  const list = (items = [row(), row({ id: "u3", name: "Bob Viewer", email: "bob@example.com", role: "VIEWER", status: "INVITED", last_login_at: null })]) => ({ total: items.length, items });

  it("lists people with role, status, two-factor and last sign-in, linking to each profile", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/users": list() });
    mount(<UsersPage />);
    expect(await screen.findByText("Jane Roe")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Jane Roe" })).toHaveAttribute("href", "/users/u2");
    expect(within(screen.getByRole("table")).getByText("INVITED")).toBeInTheDocument();
    expect(screen.getByText("Never")).toBeInTheDocument();
    expect(screen.getByText("1–2 of 2")).toBeInTheDocument();
  });

  it("searches (after a short pause) and filters, always from the first page", async () => {
    const calls = backend({ "GET /api/auth/me": me(), "GET /api/users": list() });
    mount(<UsersPage />);
    await screen.findByText("Jane Roe");
    fireEvent.change(screen.getByLabelText("Search users"), { target: { value: "jane" } });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "TRADER" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "ACTIVE" } });
    await waitFor(() => expect(calls.some((c) => c.path === "/api/users" && c.search.get("q") === "jane" && c.search.get("role") === "TRADER" && c.search.get("status") === "ACTIVE")).toBe(true));
  });

  it("pages through a long list and says so when nothing matches", async () => {
    const many = { total: 60, items: [row()] };
    const calls = backend({ "GET /api/auth/me": me(), "GET /api/users": (c: Call) => (c.search.get("q") === "zzz" ? { total: 0, items: [] } : many) });
    mount(<UsersPage />);
    await screen.findByText("1–25 of 60");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("26–50 of 60");
    expect(calls.some((c) => c.search.get("offset") === "25")).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    await screen.findByText("1–25 of 60");
    fireEvent.change(screen.getByLabelText("Search users"), { target: { value: "zzz" } });
    expect(await screen.findByText("No user matches.")).toBeInTheDocument();
  });

  it("invites someone and shows the one-time link to copy", async () => {
    const calls = backend({ "GET /api/auth/me": me(), "GET /api/users": list(), "POST /api/users": { id: "u9", invite_url: "https://portal.example/accept-invite?token=abc" } });
    mount(<UsersPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Invite user" }));
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.com" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "New Hire" } });
    fireEvent.change(screen.getByLabelText("Role", { selector: "#inv-role" }), { target: { value: "OPERATOR" } });
    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
    expect((await screen.findByTestId("one-time-link")).textContent).toBe("https://portal.example/accept-invite?token=abc");
    expect(calls.find((c) => c.method === "POST" && c.path === "/api/users")?.body).toEqual({ email: "new@example.com", name: "New Hire", role: "OPERATOR" });
    expect(calls.find((c) => c.method === "POST")?.headers["X-CSRF-Token"]).toBe("tok");
    fireEvent.click(screen.getByRole("button", { name: "Copy link" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("https://portal.example/accept-invite?token=abc");
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByTestId("one-time-link")).not.toBeInTheDocument();
  });

  it("shows why an invitation was refused and lets the form be cancelled", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/users": list(), "POST /api/users": [409, { detail: "an account with this email already exists" }] });
    mount(<UsersPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Invite user" }));
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "jane@example.com" } });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Jane" } });
    fireEvent.click(screen.getByRole("button", { name: "Send invitation" }));
    expect((await screen.findByRole("alert")).textContent).toBe("an account with this email already exists");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Name")).not.toBeInTheDocument();
  });

  it("shows an error when the directory cannot be loaded", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/users": [403, { detail: "Not permitted" }] });
    mount(<UsersPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("Not permitted");
  });
});

describe("user profile", () => {
  const events = { events: [event(2, "user.role_changed"), event(1, "user.create", "system")] };

  it("shows security state, who created the account and its activity", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/users/u2": detail({ mfa_enabled: true, recovery_codes_left: 7 }), "GET /api/audit": events });
    mount(<UserProfile />);
    expect(await screen.findByRole("heading", { name: "Jane Roe" })).toBeInTheDocument();
    expect(screen.getByText("7 recovery codes left")).toBeInTheDocument();
    expect(screen.getAllByText("by The Boss").length).toBeGreaterThan(0);
    expect(await screen.findByText("Role changed")).toBeInTheDocument();
  });

  it("says when nothing is recorded", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/users/u2": detail({ created_by: null, last_login_at: null, password_changed_at: null }), "GET /api/audit": { events: [] } });
    mount(<UserProfile />);
    expect(await screen.findByText("Nothing recorded yet.")).toBeInTheDocument();
    expect(screen.getByText("by the system")).toBeInTheDocument();
    expect(screen.getByText("Not set")).toBeInTheDocument();
  });

  it("reports an unknown user", async () => {
    nav.id = "nope";
    backend({ "GET /api/auth/me": me(), "GET /api/users/nope": [404, { detail: "no such user" }], "GET /api/audit": { events: [] } });
    mount(<UserProfile />);
    expect((await screen.findByRole("alert")).textContent).toContain("no such user");
  });

  it("suspends only after a confirmation, then shows the result", async () => {
    let status = "ACTIVE";
    const calls = backend({
      "GET /api/auth/me": me(),
      "GET /api/users/u2": () => detail({ status }),
      "GET /api/audit": events,
      "POST /api/users/u2/status": (c: Call) => {
        status = (c.body as { status: string }).status;
        return { ok: true };
      },
    });
    mount(<UserProfile />);
    fireEvent.click(await screen.findByRole("button", { name: "Suspend" }));
    expect(calls.some((c) => c.path === "/api/users/u2/status")).toBe(false); // nothing yet: it asked first
    fireEvent.click(within(screen.getByRole("group", { name: "Suspend Jane Roe?" })).getByRole("button", { name: "Suspend" }));
    expect((await screen.findByRole("status")).textContent).toBe("Suspended and signed out.");
    expect(calls.find((c) => c.path === "/api/users/u2/status")?.body).toEqual({ status: "SUSPENDED" });
    expect(await screen.findByRole("button", { name: "Reactivate" })).toBeInTheDocument();
  });

  it("lets the question be dismissed without acting", async () => {
    const calls = backend({ "GET /api/auth/me": me(), "GET /api/users/u2": detail(), "GET /api/audit": events });
    mount(<UserProfile />);
    fireEvent.click(await screen.findByRole("button", { name: "Disable" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("button", { name: "Disable" })).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("changes the role and the name", async () => {
    const calls = backend({ "GET /api/auth/me": me(), "GET /api/users/u2": detail(), "GET /api/audit": events, "POST /api/users/u2/role": { ok: true }, "POST /api/users/u2/name": { ok: true } });
    mount(<UserProfile />);
    fireEvent.change(await screen.findByLabelText("Role"), { target: { value: "OPERATOR" } });
    expect((await screen.findByRole("status")).textContent).toContain("Role changed");
    expect(calls.find((c) => c.path === "/api/users/u2/role")?.body).toEqual({ role: "OPERATOR" });
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Jane Q. Roe" } });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/users/u2/name")?.body).toEqual({ name: "Jane Q. Roe" }));
  });

  it("sends a reset link and shows it, and shows the server's refusal when an action fails", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/users/u2": detail(), "GET /api/audit": events, "POST /api/users/u2/reset-password": { reset_url: "https://portal.example/reset-password?token=r1" }, "POST /api/users/u2/end-sessions": [409, { detail: "boom" }] });
    mount(<UserProfile />);
    fireEvent.click(await screen.findByRole("button", { name: "Send password reset" }));
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect((await screen.findByTestId("one-time-link")).textContent).toContain("reset-password?token=r1");
    fireEvent.click(screen.getByRole("button", { name: "End all sessions" }));
    fireEvent.click(screen.getByRole("button", { name: "End sessions" }));
    expect((await screen.findByRole("alert")).textContent).toBe("boom");
  });

  it("resends a pending invitation and offers no password reset for it", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/users/u2": detail({ status: "INVITED", active_sessions: 0 }), "GET /api/audit": events, "POST /api/users/u2/resend-invite": { invite_url: "https://portal.example/accept-invite?token=i2" } });
    mount(<UserProfile />);
    expect(await screen.findByRole("button", { name: "Resend invitation" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send password reset" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resend invitation" }));
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect((await screen.findByTestId("one-time-link")).textContent).toContain("accept-invite?token=i2");
  });

  it("resets two-factor and ends sessions", async () => {
    const calls = backend({ "GET /api/auth/me": me(), "GET /api/users/u2": detail({ mfa_enabled: true }), "GET /api/audit": events, "POST /api/users/u2/reset-mfa": { ok: true }, "POST /api/users/u2/end-sessions": { ended: 2 } });
    mount(<UserProfile />);
    fireEvent.click(await screen.findByRole("button", { name: "Reset two-factor" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset 2FA" }));
    expect((await screen.findByRole("status")).textContent).toContain("Two-factor removed");
    fireEvent.click(screen.getByRole("button", { name: "End all sessions" }));
    fireEvent.click(screen.getByRole("button", { name: "End sessions" }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("2 session(s) ended."));
    expect(calls.some((c) => c.path === "/api/users/u2/reset-mfa")).toBe(true);
  });

  it("explains that your own account is changed by someone else and disables those actions", async () => {
    nav.id = "u1";
    backend({ "GET /api/auth/me": me(), "GET /api/users/u1": detail({ id: "u1", name: "The Boss", role: "ADMIN", mfa_enabled: true }), "GET /api/audit": events });
    mount(<UserProfile />);
    expect(await screen.findByText(/This is your own account/)).toBeInTheDocument();
    expect(screen.getByLabelText("Role")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Suspend" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reset two-factor" })).toBeDisabled();
  });

  it("hides the management panel from someone who may only read", async () => {
    backend({ "GET /api/auth/me": me({ permissions: ["research:read", "users:read"] }), "GET /api/users/u2": detail(), "GET /api/audit": events });
    mount(<UserProfile />);
    await screen.findByRole("heading", { name: "Jane Roe" });
    expect(screen.queryByText("Manage access")).not.toBeInTheDocument();
  });

  it("shows when the activity cannot be loaded", async () => {
    backend({ "GET /api/auth/me": me({ permissions: ["research:read", "users:read"] }), "GET /api/users/u2": detail(), "GET /api/audit": [403, { detail: "Not permitted" }] });
    mount(<UserProfile />);
    expect((await screen.findByRole("alert")).textContent).toBe("Not permitted");
  });

  it("does not offer a role change to someone without roles:write", async () => {
    backend({ "GET /api/auth/me": me({ permissions: ["research:read", "users:read", "users:write"] }), "GET /api/users/u2": detail({ status: "DISABLED", active_sessions: 0 }), "GET /api/audit": events });
    mount(<UserProfile />);
    await screen.findByText("Manage access");
    expect(screen.queryByLabelText("Role")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reactivate" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();
  });
});

describe("audit log", () => {
  it("lists events and narrows them by kind", async () => {
    const calls = backend({ "GET /api/auth/me": me(), "GET /api/audit": { events: [event(3, "auth.login"), event(2, "user.status_changed")] } });
    mount(<AuditPage />);
    expect(await screen.findByText("auth.login")).toBeInTheDocument();
    expect(screen.getAllByText("The Boss")).toHaveLength(2);
    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "user." } });
    await waitFor(() => expect(calls.some((c) => c.path === "/api/audit" && c.search.get("action") === "user.")).toBe(true));
  });

  it("handles an empty log", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/audit": { events: [] } });
    mount(<AuditPage />);
    expect(await screen.findByText("No events.")).toBeInTheDocument();
  });

  it("shows a refusal", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/audit": [403, { detail: "Not permitted" }] });
    mount(<AuditPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("Not permitted");
  });
});

describe("signed-out pages", () => {
  it("answers 'forgot password' the same way whoever asks", async () => {
    const calls = backend({ "POST /api/auth/forgot": { ok: true } });
    mount(<ForgotPassword />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ghost@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    expect((await screen.findByRole("status")).textContent).toContain("If that address has an account");
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ email: "ghost@example.com" });
  });

  it("reports a network failure on 'forgot password'", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("down");
    });
    mount(<ForgotPassword />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "a@example.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reset link" }));
    expect((await screen.findByRole("alert")).textContent).toContain("Could not reach the server");
  });

  it("activates an invited account with a chosen password", async () => {
    nav.search = "token=abc123";
    const calls = backend({ "POST /api/auth/accept-invite": { ok: true } });
    mount(<AcceptInvite />);
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "violet-harbor-lantern-42" } });
    fireEvent.change(screen.getByLabelText("Repeat password"), { target: { value: "different" } });
    expect(screen.getByText("The passwords differ.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Activate account" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Repeat password"), { target: { value: "violet-harbor-lantern-42" } });
    fireEvent.click(screen.getByRole("button", { name: "Activate account" }));
    expect((await screen.findByRole("status")).textContent).toContain("Your account is active");
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ token: "abc123", password: "violet-harbor-lantern-42" });
  });

  it("shows the server's reason when a link is no longer valid", async () => {
    nav.search = "token=old";
    backend({ "POST /api/auth/reset-password": [422, { detail: "this reset link is not valid any more" }] });
    mount(<ResetPassword />);
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "amber-meadow-kettle-77" } });
    fireEvent.change(screen.getByLabelText("Repeat password"), { target: { value: "amber-meadow-kettle-77" } });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect((await screen.findByRole("alert")).textContent).toBe("this reset link is not valid any more");
  });

  it("explains a link that has lost its token", async () => {
    mount(<ResetPassword />);
    expect((await screen.findByRole("alert")).textContent).toContain("missing its token");
  });

  it("completes a reset", async () => {
    nav.search = "token=good";
    backend({ "POST /api/auth/reset-password": { ok: true } });
    mount(<ResetPassword />);
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "amber-meadow-kettle-77" } });
    fireEvent.change(screen.getByLabelText("Repeat password"), { target: { value: "amber-meadow-kettle-77" } });
    fireEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect((await screen.findByRole("status")).textContent).toContain("password was changed");
  });
});

describe("navigation", () => {
  it("shows Users and the Audit log to an administrator", async () => {
    nav.path = "/dashboard";
    backend({ "GET /api/auth/me": me(), "GET /api/health": { api: "ok", database: "ok", redis: "x" } });
    mount(<Shell>x</Shell>);
    const main = within(await screen.findByRole("navigation", { name: "Main" }));
    expect(main.getByText("Users")).toBeInTheDocument();
    expect(main.getByText("Audit log")).toBeInTheDocument();
  });

  it("hides them from a trader", async () => {
    nav.path = "/dashboard";
    backend({ "GET /api/auth/me": me({ role: "TRADER", permissions: ["research:read"] }), "GET /api/health": { api: "ok", database: "ok", redis: "x" } });
    mount(<Shell>y</Shell>);
    const main = within(await screen.findByRole("navigation", { name: "Main" }));
    expect(main.queryByText("Users")).not.toBeInTheDocument();
    expect(main.queryByText("Audit log")).not.toBeInTheDocument();
  });

  it("renders the signed-out pages without the app chrome", () => {
    nav.path = "/accept-invite";
    backend({ "GET /api/auth/me": [401, {}] });
    mount(<Shell>bare page</Shell>);
    expect(screen.getByText("bare page")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });
});
