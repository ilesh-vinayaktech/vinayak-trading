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
  budget: 30, consumed: 0, reserved: 0, left: 30, previously_tested: 0, audit_signed: false, warnings, batches: [], cutoff: null, results: [],
  eligible: [
    { candidate_id: "A@1", inner: { passed: true, sharpe: 1.86, index_sharpe: 1.49 } },
    { candidate_id: "B@1", inner: { passed: false, sharpe: 1.62, index_sharpe: 1.49 } },
    { candidate_id: "C@1", inner: null },
  ],
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
  it("shows the slots, both warnings and the batches with their strategies, with no verdicts", async () => {
    backend({ "GET /api/auth/me": me, "GET /api/holdout": overview({ consumed: 4, left: 26, previously_tested: 4, batches: [{ batch_id: 1, state: "CONSUMED", candidates: 4, frozen_at: "2026-11-18T05:00:00+00:00", first_read: true, members: ["X", "Y"] }] }) });
    mount();
    expect(await screen.findByTestId("slots")).toHaveTextContent("4 used, 0 reserved, 26 left of 30");
    expect(screen.getByTestId("slots")).toHaveTextContent("Previously tested strategies: 4");
    expect(screen.getByText(/not an untouched holdout/)).toBeInTheDocument();
    expect(screen.getByText(/not proven here/)).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("X, Y")).toBeInTheDocument();
  });

  it("shows each evaluated strategy's checks, marks the ones completed later, and never a figure", async () => {
    const results = [
      { name: "M12", overall: "PASS", checks: [{ gate: "holdout_sharpe", verdict: "PASS", later: false }, { gate: "holdout_drawdown", verdict: "PASS", later: true }] },
      { name: "LV", overall: "INCOMPLETE", checks: [{ gate: "holdout_beats_benchmark", verdict: "INSUFFICIENT_EVIDENCE", later: false }] },
    ];
    backend({ "GET /api/auth/me": me, "GET /api/holdout": overview({ results }) });
    mount();
    const box = await screen.findByTestId("results");
    expect(box).toHaveTextContent("M12PASSSharpe: PASSDrawdown vs index: PASS (completed later)");
    expect(box).toHaveTextContent("LVNOT COMPLETEBeats the index: no evidence");
    expect(box).toHaveTextContent("information only");
  });

  it("lists what can be submitted with its inner holdout outcome, and submits only after a confirmation", async () => {
    backend({ "GET /api/auth/me": me, "GET /api/holdout": overview(), "POST /api/holdout/submit": { ok: true, batch_id: 1 } });
    mount();
    expect(await screen.findByTestId("eligible")).toHaveTextContent("A@1inner holdout passedSharpe 1.86 vs index 1.49");
    expect(screen.getByTestId("eligible")).toHaveTextContent("inner holdout not passed");
    expect(screen.getByTestId("eligible")).toHaveTextContent("inner holdout (2023-2024) not run");
    expect(screen.getByRole("button", { name: /Submit/ })).toBeDisabled(); // nothing picked, no declaration
    fireEvent.click(screen.getByLabelText(/A@1/));
    fireEvent.click(screen.getByLabelText(/B@1/));
    expect(screen.getByRole("button", { name: /Submit 2/ })).toBeDisabled(); // still no declaration
    fireEvent.change(screen.getByLabelText(/not built from 2025-2026/), { target: { value: "from 2016-2022 only" } });
    fireEvent.click(screen.getByRole("button", { name: /Submit 2/ }));
    expect(calls.some((c) => c.method === "POST")).toBe(false);
    expect(screen.getByRole("group")).toHaveTextContent("reserves 2 of 30 slots and commits the seeds");
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(calls.find((c) => c.method === "POST")?.body).toEqual({ candidates: ["A@1", "B@1"], declaration: "from 2016-2022 only", confirm: true }));
  });

  it("says what is wrong when the submit is refused", async () => {
    backend({ "GET /api/auth/me": me, "GET /api/holdout": overview(), "POST /api/holdout/submit": [409, { detail: "A@1: no study registered from a clean commit has passed development yet" }] });
    mount();
    fireEvent.click(await screen.findByLabelText(/A@1/));
    fireEvent.change(screen.getByLabelText(/not built from 2025-2026/), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: /Submit 1/ }));
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    expect(await screen.findByText(/no study registered from a clean commit/)).toBeInTheDocument();
  });

  it("says nothing is waiting, and points at the terminal for a frozen batch", async () => {
    backend({ "GET /api/auth/me": me, "GET /api/holdout": overview({ eligible: [], batches: [{ batch_id: 1, state: "FROZEN", candidates: 1, frozen_at: null, first_read: false, members: [] }] }) });
    mount();
    expect(await screen.findByText(/No strategy is waiting/)).toBeInTheDocument();
    expect(screen.getByText(/research_holdout.py evaluate/)).toBeInTheDocument();
  });
});
