import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SupportPage from "@/app/support/page";
import TicketPage from "@/app/support/[id]/page";
import TasksPage from "@/app/tasks/page";
import UserProfile from "@/app/users/[id]/page";
import UsersPage from "@/app/users/page";
import { Providers } from "@/app/providers";
import { Shell } from "@/components/layout/Shell";

const nav = vi.hoisted(() => ({ replace: vi.fn(), path: "/users", id: "u2" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  usePathname: () => nav.path,
  useSearchParams: () => new URLSearchParams(""),
  useParams: () => ({ id: nav.id }),
}));

type Call = { method: string; path: string; search: URLSearchParams; body: unknown };
type Reply = unknown | ((call: Call) => unknown);
const STAFF_PERMS = ["research:read", "users:read", "users:write", "roles:write", "audit:read", "crm:read", "crm:write", "tickets:own", "tickets:manage", "ops:read"];
const me = (perms: string[] = STAFF_PERMS) => ({ user: { id: "u1", email: "ops@example.com", name: "Olive Ops", role: "OPERATOR", permissions: perms, mfa_enabled: true, enrolment_required: false, must_change_password: false } });
const row = (over: Record<string, unknown> = {}) => ({ id: "u2", email: "jane@example.com", name: "Jane Roe", role: "TRADER", status: "ACTIVE", mfa_enabled: false, last_login_at: null, created_at: "2026-11-01T08:00:00Z", tags: [], ...over });
const detail = (over: Record<string, unknown> = {}) => ({ ...row(), must_change_password: false, password_changed_at: null, created_by: null, recovery_codes_left: 0, active_sessions: 0, ...over });
const task = (over: Record<string, unknown> = {}) => ({ id: "k1", title: "Call Jane", detail: "", due_date: "2026-01-02", status: "OPEN", created_at: "2026-11-01T08:00:00Z", completed_at: null, owner: "Olive Ops", owner_id: "u1", about: "Jane Roe", about_id: "u2", ...over });
const ticketRow = (over: Record<string, unknown> = {}) => ({ id: "t1", number: 7, subject: "Cannot connect Kite", status: "OPEN", priority: "NORMAL", requester: "Jane Roe", requester_id: "u2", assignee: null, assignee_id: null, created_at: "2026-11-11T09:00:00Z", updated_at: "2026-11-11T09:30:00Z", ...over });
const msg = (id: string, body: string, over: Record<string, unknown> = {}) => ({ id, body, internal: false, created_at: "2026-11-11T09:00:00Z", author: "Jane Roe", mine: false, ...over });

function backend(table: Record<string, Reply>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const call: Call = { method: init?.method ?? "GET", path: url.pathname, search: url.searchParams, body: init?.body ? JSON.parse(String(init.body)) : undefined };
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
  nav.id = "u2";
  document.cookie = "csrf=tok";
});
afterEach(() => vi.unstubAllGlobals());

const profileBase = (extra: Record<string, Reply> = {}) => ({
  "GET /api/auth/me": me(),
  "GET /api/users/u2": detail({ tags: ["kyc pending"] }),
  "GET /api/audit": { events: [] },
  "GET /api/users/u2/notes": { notes: [{ id: "n1", body: "Asked about Kite", created_at: "2026-11-10T09:00:00Z", author: "Olive Ops" }] },
  "GET /api/tasks": { tasks: [task()] },
  "GET /api/staff": { staff: [{ id: "u1", name: "Olive Ops", role: "OPERATOR" }, { id: "u3", name: "The Boss", role: "ADMIN" }] },
  ...extra,
});

describe("directory tags", () => {
  it("shows each person's tags and filters by a tag chosen from the list in use", async () => {
    const calls = backend({
      "GET /api/auth/me": me(),
      "GET /api/users": { total: 1, items: [row({ tags: ["kyc pending", "onboarding"] })] },
      "GET /api/tags": { tags: [{ tag: "kyc pending", users: 1 }, { tag: "onboarding", users: 2 }] },
    });
    mount(<UsersPage />);
    const table = within(await screen.findByRole("table"));
    expect(await table.findByText("kyc pending")).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("Tag"), { target: { value: "onboarding" } });
    await waitFor(() => expect(calls.some((c) => c.path === "/api/users" && c.search.get("tag") === "onboarding")).toBe(true));
  });
});

const openCrm = async () => fireEvent.click(await screen.findByRole("tab", { name: /Notes & tasks/ }));

describe("profile CRM panels", () => {
  it("shows tags, notes and tasks about the user to staff", async () => {
    backend(profileBase());
    mount(<UserProfile />);
    await openCrm();
    expect(await screen.findByText("Asked about Kite")).toBeInTheDocument();
    expect(screen.getByLabelText("Tags of this user").textContent).toContain("kyc pending");
    expect(await screen.findByText("Call Jane")).toBeInTheDocument();
  });

  it("adds and removes a tag", async () => {
    let tags = ["kyc pending"];
    const calls = backend(profileBase({
      "GET /api/users/u2": () => detail({ tags }),
      "POST /api/users/u2/tags": (c: Call) => {
        tags = [...tags, (c.body as { tag: string }).tag];
        return { tag: (c.body as { tag: string }).tag };
      },
      "POST /api/users/u2/tags/remove": (c: Call) => {
        tags = tags.filter((t) => t !== (c.body as { tag: string }).tag);
        return { ok: true };
      },
    }));
    mount(<UserProfile />);
    await openCrm();
    fireEvent.change(await screen.findByLabelText("New tag"), { target: { value: "onboarding" } });
    fireEvent.click(screen.getByRole("button", { name: "Add tag" }));
    await waitFor(() => expect(screen.getByLabelText("Tags of this user").textContent).toContain("onboarding"));
    fireEvent.click(screen.getByRole("button", { name: "Remove tag kyc pending" }));
    await waitFor(() => expect(screen.getByLabelText("Tags of this user").textContent).not.toContain("kyc pending"));
    expect(calls.find((c) => c.path === "/api/users/u2/tags/remove")?.body).toEqual({ tag: "kyc pending" });
  });

  it("adds a note and clears the box", async () => {
    const calls = backend(profileBase({ "POST /api/users/u2/notes": { id: "n2" } }));
    mount(<UserProfile />);
    await openCrm();
    fireEvent.change(await screen.findByLabelText("New note"), { target: { value: "Called back" } });
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    await waitFor(() => expect(screen.getByLabelText("New note")).toHaveValue(""));
    expect(calls.find((c) => c.path === "/api/users/u2/notes" && c.method === "POST")?.body).toEqual({ body: "Called back" });
  });

  it("creates a task for a chosen owner and marks one done", async () => {
    const calls = backend(profileBase({ "POST /api/tasks": { id: "k2" }, "POST /api/tasks/k1/status": { ok: true } }));
    mount(<UserProfile />);
    await openCrm();
    fireEvent.change(await screen.findByLabelText("Task"), { target: { value: "Send KYC form" } });
    await screen.findByRole("option", { name: "The Boss" });
    fireEvent.change(screen.getByLabelText("Owner"), { target: { value: "u3" } });
    fireEvent.change(screen.getByLabelText("Due"), { target: { value: "2026-12-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/tasks" && c.method === "POST")?.body).toEqual({ title: "Send KYC form", detail: "", owner_id: "u3", user_id: "u2", due_date: "2026-12-01" }));
    fireEvent.click(screen.getByRole("button", { name: "Mark done" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/tasks/k1/status")?.body).toEqual({ status: "DONE" }));
  });

  it("defaults the owner to the first staff member and shows a refusal", async () => {
    const calls = backend(profileBase({ "POST /api/tasks": [422, { detail: "a task can only be assigned to an active administrator or operator" }] }));
    mount(<UserProfile />);
    await openCrm();
    fireEvent.change(await screen.findByLabelText("Task"), { target: { value: "x" } });
    await screen.findByRole("option", { name: "The Boss" });
    fireEvent.click(screen.getByRole("button", { name: "Add task" }));
    expect((await screen.findAllByRole("alert"))[0]?.textContent).toContain("administrator or operator");
    expect((calls.find((c) => c.method === "POST" && c.path === "/api/tasks")?.body as { owner_id: string }).owner_id).toBe("u1");
  });

  it("is read-only for someone who may read the CRM but not write it", async () => {
    backend(profileBase({ "GET /api/auth/me": me(["research:read", "users:read", "crm:read"]) }));
    mount(<UserProfile />);
    await openCrm();
    expect(await screen.findByText("Asked about Kite")).toBeInTheDocument();
    for (const label of ["New tag", "New note", "Task"]) expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Mark done" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Remove tag/ })).not.toBeInTheDocument();
  });

  it("says when there is nothing yet", async () => {
    backend(profileBase({ "GET /api/users/u2": detail(), "GET /api/users/u2/notes": { notes: [] }, "GET /api/tasks": { tasks: [] } }));
    mount(<UserProfile />);
    await openCrm();
    expect(await screen.findByText("No notes yet.")).toBeInTheDocument();
    expect(screen.getByText("No tags.")).toBeInTheDocument();
    expect(screen.getByText("No tasks about this user.")).toBeInTheDocument();
  });

  it("does not show the CRM to someone without crm:read", async () => {
    backend(profileBase({ "GET /api/auth/me": me(["research:read", "users:read"]) }));
    mount(<UserProfile />);
    await screen.findByRole("heading", { name: "Jane Roe" });
    expect(screen.queryByRole("tab", { name: /Notes & tasks/ })).not.toBeInTheDocument();
    expect(screen.queryByText("Internal notes")).not.toBeInTheDocument();
  });
});

describe("tasks page", () => {
  it("lists my open tasks with an overdue flag and a link to the person, and completes one", async () => {
    nav.path = "/tasks";
    const calls = backend({ "GET /api/auth/me": me(), "GET /api/tasks": { tasks: [task(), task({ id: "k2", title: "No date", due_date: null, about: null, about_id: null })] }, "POST /api/tasks/k1/status": { ok: true } });
    mount(<TasksPage />);
    expect(await screen.findByText("Call Jane")).toBeInTheDocument();
    expect(screen.getByText("overdue")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Jane Roe" })).toHaveAttribute("href", "/users/u2");
    expect(calls.find((c) => c.path === "/api/tasks")?.search.get("mine")).toBe("true");
    expect(calls.find((c) => c.path === "/api/tasks")?.search.get("status")).toBe("OPEN");
    fireEvent.click(screen.getAllByRole("button", { name: "Mark done" })[0] as HTMLElement);
    await waitFor(() => expect(calls.some((c) => c.path === "/api/tasks/k1/status")).toBe(true));
  });

  it("switches to everyone's tasks and to done ones, and says when empty", async () => {
    const calls = backend({ "GET /api/auth/me": me(), "GET /api/tasks": { tasks: [] } });
    mount(<TasksPage />);
    expect(await screen.findByText("Nothing here")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Whose tasks"), { target: { value: "all" } });
    fireEvent.click(screen.getByRole("tab", { name: "Done" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/tasks" && c.search.get("mine") === null && c.search.get("status") === "DONE")).toBe(true));
  });

  it("shows a refusal", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/tasks": [403, { detail: "Not permitted" }] });
    mount(<TasksPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("Not permitted");
  });
});

describe("support: list and new ticket", () => {
  it("a requester sees their tickets and raises a new one", async () => {
    nav.path = "/support";
    const calls = backend({ "GET /api/auth/me": me(["research:read", "tickets:own"]), "GET /api/tickets": { total: 1, items: [ticketRow({ priority: "HIGH", assignee: "Olive Ops", assignee_id: "u1" })] }, "POST /api/tickets": { number: 8 } });
    mount(<SupportPage />);
    expect(await screen.findByRole("link", { name: /#7 Cannot connect Kite/ })).toHaveAttribute("href", "/support/t1");
    expect(screen.getByText("High")).toBeInTheDocument();
    expect(screen.queryByText("Assignee")).not.toBeInTheDocument(); // staff-only column
    expect(screen.queryByLabelText(/Only tickets I raised/)).not.toBeInTheDocument(); // staff-only
    fireEvent.click(screen.getByRole("button", { name: "New ticket" }));
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "Need help" } });
    fireEvent.change(screen.getByLabelText("What do you need help with?"), { target: { value: "Details" } });
    fireEvent.change(screen.getByLabelText("Priority"), { target: { value: "HIGH" } });
    fireEvent.click(screen.getByRole("button", { name: "Send ticket" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST" && c.path === "/api/tickets")?.body).toEqual({ subject: "Need help", body: "Details", priority: "HIGH" }));
    await waitFor(() => expect(screen.queryByLabelText("Subject")).not.toBeInTheDocument());
  });

  it("shows why a ticket was refused and lets the form be cancelled", async () => {
    backend({ "GET /api/auth/me": me(["research:read", "tickets:own"]), "GET /api/tickets": { total: 0, items: [] }, "POST /api/tickets": [422, { detail: "a ticket needs a subject" }] });
    mount(<SupportPage />);
    expect(await screen.findByText("No tickets")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: "New ticket" })[0] as HTMLElement);
    fireEvent.change(screen.getByLabelText("Subject"), { target: { value: "x" } });
    fireEvent.change(screen.getByLabelText("What do you need help with?"), { target: { value: "y" } });
    fireEvent.click(screen.getByRole("button", { name: "Send ticket" }));
    expect((await screen.findByRole("alert")).textContent).toBe("a ticket needs a subject");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Subject")).not.toBeInTheDocument();
  });

  it("staff see the whole queue with requester and assignment, filter it and page through it", async () => {
    const calls = backend({ "GET /api/auth/me": me(), "GET /api/tickets": { total: 60, items: [ticketRow()] } });
    mount(<SupportPage />);
    expect(await screen.findByText(/Jane Roe · opened/)).toBeInTheDocument();
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Pending" }));
    fireEvent.click(screen.getByLabelText(/Only tickets I raised/));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/tickets" && c.search.get("status") === "PENDING" && c.search.get("mine") === "true")).toBe(true));
    fireEvent.click(await screen.findByRole("button", { name: "Next" }));
    await waitFor(() => expect(calls.some((c) => c.search.get("offset") === "25")).toBe(true));
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
  });

  it("reports a failure to load", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/tickets": [403, { detail: "Not permitted" }] });
    mount(<SupportPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("Not permitted");
  });
});

describe("support: one ticket", () => {
  const full = (over: Record<string, unknown> = {}) => ({ ...ticketRow(), messages: [msg("m1", "It says invalid token"), msg("m2", "Check expiry", { internal: true, author: "Olive Ops" })], ...over });

  it("a requester sees the conversation, replies, and can close their own ticket after confirming", async () => {
    nav.id = "t1";
    let status = "OPEN";
    const calls = backend({
      "GET /api/auth/me": me(["research:read", "tickets:own"]),
      "GET /api/tickets/t1": () => full({ status, messages: [msg("m1", "It says invalid token", { mine: true })] }),
      "POST /api/tickets/t1/messages": { ok: true },
      "POST /api/tickets/t1/status": (c: Call) => {
        status = (c.body as { status: string }).status;
        return { ok: true };
      },
    });
    mount(<TicketPage />);
    expect(await screen.findByText("It says invalid token")).toBeInTheDocument();
    expect(screen.queryByText("Handle")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Internal note/)).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Your reply"), { target: { value: "Firefox" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/tickets/t1/messages")?.body).toEqual({ body: "Firefox", internal: false }));
    fireEvent.click(screen.getByRole("button", { name: "Close ticket" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(await screen.findByText(/This ticket is closed/)).toBeInTheDocument();
  });

  it("staff see internal notes marked as such, assign the ticket, change its status and add an internal note", async () => {
    nav.id = "t1";
    const calls = backend({
      "GET /api/auth/me": me(),
      "GET /api/tickets/t1": full(),
      "GET /api/staff": { staff: [{ id: "u1", name: "Olive Ops", role: "OPERATOR" }] },
      "POST /api/tickets/t1/assign": { ok: true },
      "POST /api/tickets/t1/status": { ok: true },
      "POST /api/tickets/t1/messages": { ok: true },
    });
    mount(<TicketPage />);
    expect(await screen.findByText("Check expiry")).toBeInTheDocument();
    expect(screen.getByText("Internal note")).toBeInTheDocument();
    await screen.findByRole("option", { name: "Olive Ops" });
    fireEvent.change(screen.getByLabelText("Assigned to"), { target: { value: "u1" } });
    await waitFor(() => expect(calls.find((c) => c.path === "/api/tickets/t1/assign")?.body).toEqual({ assignee_id: "u1" }));
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "RESOLVED" } });
    await waitFor(() => expect(calls.find((c) => c.path === "/api/tickets/t1/status")?.body).toEqual({ status: "RESOLVED" }));
    fireEvent.change(screen.getByLabelText("Your reply"), { target: { value: "Looks like expiry" } });
    fireEvent.click(screen.getByLabelText(/Internal note \(the requester/));
    fireEvent.click(screen.getByRole("button", { name: "Add internal note" }));
    await waitFor(() => expect(calls.find((c) => c.path === "/api/tickets/t1/messages")?.body).toEqual({ body: "Looks like expiry", internal: true }));
    expect(screen.queryByRole("button", { name: "Close ticket" })).not.toBeInTheDocument(); // staff set status above instead
  });

  it("shows the server's refusal when a reply is rejected", async () => {
    nav.id = "t1";
    backend({ "GET /api/auth/me": me(["research:read", "tickets:own"]), "GET /api/tickets/t1": full({ messages: [] }), "POST /api/tickets/t1/messages": [409, { detail: "this ticket is closed: raise a new one" }] });
    mount(<TicketPage />);
    fireEvent.change(await screen.findByLabelText("Your reply"), { target: { value: "more" } });
    fireEvent.click(screen.getByRole("button", { name: "Send reply" }));
    expect((await screen.findByRole("alert")).textContent).toContain("closed");
  });

  it("reports an unknown ticket", async () => {
    nav.id = "gone";
    backend({ "GET /api/auth/me": me(), "GET /api/tickets/gone": [404, { detail: "no such ticket" }] });
    mount(<TicketPage />);
    expect((await screen.findByRole("alert")).textContent).toContain("no such ticket");
  });
});

describe("navigation", () => {
  it("offers Support to everyone and Tasks to staff only", async () => {
    nav.path = "/dashboard";
    backend({ "GET /api/auth/me": me(["research:read", "tickets:own"]), "GET /api/health": { api: "ok", database: "ok", redis: "x" } });
    mount(<Shell>x</Shell>);
    const viewer = within(await screen.findByRole("navigation", { name: "Main" }));
    expect(viewer.getByText("Support")).toBeInTheDocument();
    expect(viewer.queryByText("Tasks")).not.toBeInTheDocument();
  });

  it("shows Tasks to staff", async () => {
    nav.path = "/dashboard";
    backend({ "GET /api/auth/me": me(), "GET /api/health": { api: "ok", database: "ok", redis: "x" } });
    mount(<Shell>x</Shell>);
    expect(within(await screen.findByRole("navigation", { name: "Main" })).getByText("Tasks")).toBeInTheDocument();
  });
});
