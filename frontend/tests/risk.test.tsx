import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RiskPage from "@/app/risk/page";
import { Providers } from "@/app/providers";
import paused from "./contract/risk_state_paused.json";
import running from "./contract/risk_state.json";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/risk",
  useSearchParams: () => new URLSearchParams(""),
}));

const who = (perms: string[]) => ({ user: { id: "u1", email: "jane@example.com", name: "Jane", role: "TRADER", permissions: perms, mfa_enabled: true, enrolment_required: false, must_change_password: false } });
const calls: { method: string; path: string; body: unknown }[] = [];
function backend(table: Record<string, unknown>) {
  calls.length = 0;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    calls.push({ method, path: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const hit = table[`${method} ${url.pathname}`];
    if (hit === undefined) return new Response(JSON.stringify({ detail: "no route" }), { status: 404 });
    const [status, body] = Array.isArray(hit) && typeof hit[0] === "number" ? (hit as [number, unknown]) : [200, hit];
    return new Response(JSON.stringify(body), { status });
  });
}
const base = (state: unknown, extra: Record<string, unknown> = {}) => ({ "GET /api/auth/me": who(["research:read", "strategy:own"]), "GET /api/risk": state, ...extra });
const mount = () => render(<Providers><RiskPage /></Providers>);
const writes = () => calls.filter((c) => c.method !== "GET" && c.path.startsWith("/api/risk"));

beforeEach(() => {
  document.cookie = "csrf=tok";
});
afterEach(() => vi.unstubAllGlobals());

describe("Risk and kill switch", () => {
  it("shows what is in force, in words, and who set it and why", async () => {
    backend(base(paused));
    mount();
    expect(await screen.findByText(/No new orders: proposals are skipped/)).toBeTruthy();
    expect(screen.getAllByText("PAUSE").length).toBeGreaterThan(0);
    expect(screen.getByText(/PAUSE by jane@example.com: looking at the data/)).toBeTruthy();
    const history = within(screen.getByRole("table", { name: "Kill switch changes" }));
    expect(history.getByText("looking at the data")).toBeTruthy();
  });

  it("will not pause until a reason is given, then sends it with the action", async () => {
    backend(base(running, { "POST /api/risk/switch": { effective: "PAUSE" } }));
    mount();
    const pause = await screen.findByRole("button", { name: "Pause" });
    expect((pause as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText(/Why \(your strategy\)/), { target: { value: "checking fills" } });
    expect((pause as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(pause);
    await waitFor(() => expect(writes()).toEqual([{ method: "POST", path: "/api/risk/switch", body: { action: "pause", reason: "checking fills", emergency_override: false } }]));
  });

  it("asks before cancelling orders and before an emergency flatten, which carries the override", async () => {
    backend(base(running, { "POST /api/risk/switch": { effective: "FLATTEN" } }));
    mount();
    await screen.findByRole("button", { name: "Pause" });
    fireEvent.change(screen.getByLabelText(/Why \(your strategy\)/), { target: { value: "fire" } });
    fireEvent.click(screen.getByRole("button", { name: "Flatten" }));
    expect(writes()).toEqual([]); // nothing sent before the confirmation
    fireEvent.click(screen.getByRole("button", { name: "Flatten (emergency)" }));
    await waitFor(() => expect(writes()[0]?.body).toEqual({ action: "flatten", reason: "fire", emergency_override: true }));
  });

  it("hides the switch for everyone from people who cannot use it", async () => {
    backend(base(running));
    mount();
    await screen.findByRole("button", { name: "Pause" });
    expect(screen.queryByText("Everyone (operators)")).toBeNull();
  });

  it("gives operators a switch for everyone, sent to its own route", async () => {
    backend(base({ ...running, can_global: true }, { "POST /api/risk/switch/global": { effective: "PAUSE" } }));
    mount();
    expect(await screen.findByText("Everyone (operators)")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Why \(everyone\)/), { target: { value: "exchange problem" } });
    const pauses = screen.getAllByRole("button", { name: "Pause" });
    fireEvent.click(pauses[pauses.length - 1]!);
    await waitFor(() => expect(writes()[0]).toEqual({ method: "POST", path: "/api/risk/switch/global", body: { action: "pause", reason: "exchange problem", emergency_override: false } }));
  });

  it("saves limits as JSON, refuses invalid JSON, and shows the server's reason when a key is unknown", async () => {
    backend(base(paused, { "PUT /api/risk/limits": [422, { detail: "unknown limit(s): max_order_valu" }] }));
    mount();
    const box = (await screen.findByLabelText("Limits (JSON)")) as HTMLTextAreaElement;
    expect(JSON.parse(box.value)).toEqual({ max_order_value: "50000", max_open_orders: 5 });
    const save = screen.getByRole("button", { name: "Save limits" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true); // nothing changed
    fireEvent.change(box, { target: { value: "{nope" } });
    expect(screen.getByText("That is not valid JSON.")).toBeTruthy();
    expect(save.disabled).toBe(true);
    fireEvent.change(box, { target: { value: '{"max_order_valu": 1}' } });
    fireEvent.click(save);
    expect(await screen.findByText(/unknown limit\(s\): max_order_valu/)).toBeTruthy();
    expect(writes()[0]).toEqual({ method: "PUT", path: "/api/risk/limits", body: { limits: { max_order_valu: 1 } } });
  });

  it("without a paper account, hides the controls", async () => {
    backend(base({ ...running, account: null, limits: null }));
    mount();
    expect(await screen.findByText("No trading account yet")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
    expect(screen.queryByLabelText("Limits (JSON)")).toBeNull();
  });

  it("explains what can be limited", async () => {
    backend(base(running));
    mount();
    fireEvent.click(await screen.findByText("What can be limited"));
    expect(screen.getAllByText(/Largest order, in rupees/).length).toBeGreaterThan(0);
  });
});
