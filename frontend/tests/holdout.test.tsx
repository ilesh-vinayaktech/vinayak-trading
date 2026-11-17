import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import HoldoutPage from "@/app/holdout/page";
import { Providers } from "@/app/providers";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/holdout",
  useSearchParams: () => new URLSearchParams(""),
}));

const me = { user: { id: "u1", email: "boss@example.com", name: "Boss", role: "ADMIN", permissions: ["research:read", "holdout:read"], mfa_enabled: true, must_enrol: false, must_change_password: false } };
const warnings = ["These dates are a repeatedly accessed validation set, not an untouched holdout.", "A FAIL means not proven here, not no edge."];
const overview = (over: Record<string, unknown> = {}) => ({
  budget: 30, consumed: 0, reserved: 0, left: 30, previously_tested: 0, audit_signed: true, warnings, batches: [],
  cutoff: { cutoff_id: 4, kind: "BATCH1", fired_at: "2026-11-17T06:00:00+00:00", plan: { members: ["A@1", "B@1", "C@1"], carry_over: [], excluded: { "D@1": "chosen by hand" }, problems: [], can_freeze: true } },
  ...over,
});
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
const mount = () => render(<Providers><HoldoutPage /></Providers>);
beforeEach(() => {
  document.cookie = "csrf=tok";
});
afterEach(() => vi.unstubAllGlobals());

describe("Holdout ledger", () => {
  it("shows the slots, both warnings and the plan for the next batch, with no figures", async () => {
    backend({ "GET /api/auth/me": me, "GET /api/holdout": overview({ consumed: 4, left: 26, previously_tested: 4, batches: [{ batch_id: 1, state: "CONSUMED", candidates: 4, frozen_at: "2026-11-18T05:00:00+00:00", first_read: true }] }) });
    mount();
    expect(await screen.findByTestId("slots")).toHaveTextContent("4 used, 0 reserved, 26 left of 30");
    expect(screen.getByTestId("slots")).toHaveTextContent("Previously tested strategies: 4");
    expect(screen.getByText(/not an untouched holdout/)).toBeInTheDocument();
    expect(screen.getByText(/not proven here/)).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByTestId("plan")).toHaveTextContent("A@1, B@1, C@1");
    expect(screen.getByTestId("plan")).toHaveTextContent("D@1 excluded (ineligible): chosen by hand");
  });

  it("freezes only after a confirmation, and says what it commits", async () => {
    backend({ "GET /api/auth/me": me, "GET /api/holdout": overview(), "POST /api/holdout/cutoffs/4/freeze": { ok: true, batch_id: 1 } });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Freeze the batch" }));
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    expect(screen.getByRole("group")).toHaveTextContent("reserves 3 of 30 slots for good and commits the seeds");
    fireEvent.click(screen.getByRole("button", { name: "Freeze the batch" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ confirm: true }));
  });

  it("offers no freeze while the plan does not allow one and says why", async () => {
    backend({ "GET /api/auth/me": me, "GET /api/holdout": overview({ audit_signed: false, cutoff: { cutoff_id: 4, kind: "BATCH1", fired_at: "2026-11-17T06:00:00+00:00", plan: { members: [], carry_over: [], excluded: {}, problems: ["the provenance audit is not signed: the batch stays PENDING"], can_freeze: false } } }) });
    mount();
    expect(await screen.findByText(/audit is not signed/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Freeze the batch" })).toBeDisabled();
  });

  it("says the cutoff has not fired when it has not", async () => {
    backend({ "GET /api/auth/me": me, "GET /api/holdout": overview({ cutoff: null, audit_signed: false }) });
    mount();
    expect(await screen.findByText(/cutoff has not fired yet/)).toBeInTheDocument();
    expect(screen.getByText("No batch yet")).toBeInTheDocument();
  });
});
