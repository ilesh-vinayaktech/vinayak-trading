import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RegulatoryPage from "@/app/regulatory/page";
import { Providers } from "@/app/providers";
import fixture from "./contract/regulatory.json";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/regulatory",
  useSearchParams: () => new URLSearchParams(""),
}));

const who = { user: { id: "u1", email: "ops@example.com", name: "Olive Ops", role: "OPERATOR", permissions: ["research:read", "ops:write"], mfa_enabled: true, enrolment_required: false, must_change_password: false } };
const calls: { method: string; path: string; body: unknown }[] = [];
function backend(state: unknown, extra: Record<string, unknown> = {}) {
  calls.length = 0;
  const table: Record<string, unknown> = { "GET /api/auth/me": who, "GET /api/regulatory": state, ...extra };
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
const mount = () => render(<Providers><RegulatoryPage /></Providers>);
const writes = () => calls.filter((c) => c.method === "POST" && c.path.startsWith("/api/regulatory"));
const card = (name: string) => within(screen.getByRole("heading", { name }).closest("section") as HTMLElement);

beforeEach(() => {
  document.cookie = "csrf=tok";
});
afterEach(() => vi.unstubAllGlobals());

describe("Regulatory rules", () => {
  it("shows each rule's state and says why live trading is blocked", async () => {
    backend(fixture);
    mount();
    expect(await screen.findByText("Live trading is blocked")).toBeTruthy();
    expect(card("Order-rate limit").getByText("recorded")).toBeTruthy();
    expect(card("Order-rate limit").getByText("circular A")).toBeTruthy();
    expect(card("Algo tagging").getByText("needs a re-check")).toBeTruthy();
    expect(card("Static IP").getByText("not recorded")).toBeTruthy();
    expect(screen.getByText(/order_types is not recorded for NSE CM/)).toBeTruthy();
  });

  it("says everything is fine when nothing blocks live", async () => {
    backend({ ...fixture, blocks_live: false, problems: [], items: fixture.items.map((i) => ({ ...i, status: "ok" })) });
    mount();
    expect(await screen.findByText("Every rule is recorded and recent")).toBeTruthy();
    expect(screen.queryByText("Live trading is blocked")).toBeNull();
  });

  it("will not record until the value is valid JSON, a source is given and the date is not in the future", async () => {
    backend(fixture, { "POST /api/regulatory": { topic: "static_ip" } });
    mount();
    const ip = await screen.findByRole("heading", { name: "Static IP" });
    const c = within(ip.closest("section") as HTMLElement);
    fireEvent.click(c.getByText("Record this rule"));
    const button = c.getByRole("button", { name: "Record rule" }) as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    fireEvent.change(c.getByLabelText(/What the rule says/), { target: { value: "{not json" } });
    expect(c.getByText(/Not valid JSON/)).toBeTruthy();
    fireEvent.change(c.getByLabelText(/What the rule says/), { target: { value: '{"ip": "203.0.113.5"}' } });
    fireEvent.change(c.getByLabelText("Where you read it"), { target: { value: "circular C" } });
    fireEvent.change(c.getByLabelText("In force since"), { target: { value: "2026-11-18" } });
    expect(c.getByText("That date has not come yet.")).toBeTruthy();
    expect(button.disabled).toBe(true);
    fireEvent.change(c.getByLabelText("In force since"), { target: { value: "2026-04-01" } });
    expect(button.disabled).toBe(false);
    fireEvent.click(button);
    await waitFor(() => expect(writes()).toEqual([{ method: "POST", path: "/api/regulatory", body: { topic: "static_ip", value: { ip: "203.0.113.5" }, source: "circular C", effective_from: "2026-04-01" } }]));
  });

  it("re-checks a recorded rule after a confirmation, with no body", async () => {
    backend(fixture, { "POST /api/regulatory/tagging/verify": { topic: "tagging" } });
    mount();
    await screen.findByText("Live trading is blocked");
    const c = card("Algo tagging");
    fireEvent.click(c.getByRole("button", { name: "Re-check: nothing changed" }));
    expect(writes()).toEqual([]); // asked first
    fireEvent.click(await screen.findByRole("button", { name: "Yes, unchanged" }));
    await waitFor(() => expect(writes()).toEqual([{ method: "POST", path: "/api/regulatory/tagging/verify", body: undefined }]));
  });

  it("has no buttons for someone who cannot edit", async () => {
    backend({ ...fixture, can_edit: false });
    mount();
    expect(await screen.findByText(/Recording or re-checking one needs an operator/)).toBeTruthy();
    expect(screen.queryByText("Record this rule")).toBeNull();
    expect(screen.queryByRole("button", { name: "Re-check: nothing changed" })).toBeNull();
  });
});
