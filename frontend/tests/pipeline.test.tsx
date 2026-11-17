import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PipelinePage from "@/app/research/pipeline/page";
import { Providers } from "@/app/providers";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/research/pipeline",
  useSearchParams: () => new URLSearchParams(""),
}));

const me = { user: { id: "u1", email: "boss@example.com", name: "Boss", role: "ADMIN", permissions: ["research:read", "holdout:read"], mfa_enabled: true, enrolment_required: false, must_change_password: false } };
const fig = (over: Record<string, unknown> = {}) => ({ passed: true, failed: [], cagr: 0.33, total_return: 4.5, sharpe: 1.23, max_drawdown: -0.28, benchmark_sharpe: 0.9, window: null, oos_sharpe: 1.4, ...over });
const row = (over: Record<string, unknown>) => ({ experiment_id: 1, name: "X", family: null, stage: "development", outcome: "stopped", why: "Failed development: oos_sharpe.", paper: null, development: fig({ passed: false, failed: ["oos_sharpe"] }), inner: null, outer: null, ...over });
const rows = [
  row({ experiment_id: 1, name: "FAILED_DEV" }),
  row({ experiment_id: 2, name: "READY_ONE", stage: "paper", outcome: "ready", why: "Passed development and both holdouts. Ready for paper trading.", paper: "ready", development: fig(), inner: fig({ cagr: 0.48 }), outer: { overall: "PASS", checks: [] } }),
  row({ experiment_id: 3, name: "FAILED_OUTER", stage: "outer", outcome: "stopped", why: "Failed the outer holdout (2025-2026): holdout_sharpe.", development: fig(), inner: fig(), outer: { overall: "FAIL", checks: [{ gate: "holdout_sharpe", verdict: "FAIL", later: false }] } }),
];
const calls: { method: string; path: string; body: unknown }[] = [];
const DEF = (id: string, study: string) => ({
  strategy_id: id, version: 1, description: "d", rebalance: "MONTHLY", max_positions: 20, entry: "e", exit: "x",
  plain: { when: "w", summary: `${id} summary`, buy: "b", sell: "s", size: "z" }, created_by: "me", created_at: "2026-11-17T00:00:00Z",
  experiment_id: null, study_name: null, study, trials_done: 0, verdict: null, earlier_verdict: null,
});
const OPTIONS = { strategies: [], segments: [], timeframes: [], brokers: [], benchmarks: [], frozen_through: null, survivorship_safe_from: "2016-01-01", segment_lists_from: "2016-01-01", max_trials: 300, holdout_share: [0.2], thresholds: {}, families: [{ family_id: 1, name: "First family", hypothesis: "h", studies: 19, trials: 200 }, { family_id: 5, name: "Momentum ideas", hypothesis: "h", studies: 0, trials: 0 }] };
function backend(outer_visible: boolean, dirty = false, perms = ["research:read", "holdout:read", "strategy:own"]) {
  calls.length = 0;
  const table: Record<string, unknown> = {
    "GET /api/auth/me": { user: { ...me.user, permissions: perms } },
    "GET /api/pipeline": { rows, outer_visible, code_dirty: dirty },
    "GET /api/intel/definitions": { definitions: [DEF("NEW_ONE", "none"), DEF("NEW_TWO", "none"), DEF("OLD_ONE", "judged")] },
    "GET /api/studies/options": OPTIONS,
    "GET /api/pipeline/unrun": { families: [{ family_id: 4, name: "Technical Screener 2", studies: [{ experiment_id: 20, name: "Golden Cross", strategy_id: "screener" }, { experiment_id: 21, name: "Volume Breakout", strategy_id: "screener" }] }] },
    "POST /api/studies/20/runs": { run_id: 1 },
    "POST /api/studies/21/runs": { run_id: 2 },
    "POST /api/strategies/definitions/NEW_TWO/1/study": { experiment_id: 30, run_id: 40 },
  };
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = new URL(String(input)).pathname;
    const method = init?.method ?? "GET";
    calls.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const hit = table[`${method} ${path}`];
    return new Response(JSON.stringify(hit ?? { detail: "no route" }), { status: hit === undefined ? 404 : 200 });
  });
}
beforeEach(() => {
  document.cookie = "csrf=tok";
});
afterEach(() => vi.unstubAllGlobals());

describe("Strategy pipeline", () => {
  it("counts how many made it through each stage, and puts the ready one first", async () => {
    backend(true);
    render(<Providers><PipelinePage /></Providers>);
    const funnel = await screen.findByTestId("funnel");
    expect(funnel).toHaveTextContent("3Tested");
    expect(funnel).toHaveTextContent("2Passed development");
    expect(funnel).toHaveTextContent("1Passed outer holdout");
    expect(funnel).toHaveTextContent("1Ready for paper");
    const names = screen.getAllByRole("link").map((a) => a.textContent).filter((t) => /_/.test(t ?? ""));
    expect(names).toEqual(["READY_ONE", "FAILED_OUTER", "FAILED_DEV"]);
  });

  it("says where each one stopped and why, with the returns of the stages research may see", async () => {
    backend(true);
    render(<Providers><PipelinePage /></Providers>);
    await screen.findByTestId("funnel");
    expect(screen.getByText("Stopped at development")).toBeInTheDocument();
    expect(screen.getByText("Stopped at the outer holdout")).toBeInTheDocument();
    expect(screen.getByText("Failed development: oos_sharpe.")).toBeInTheDocument();
    const ready = within(screen.getByRole("link", { name: "READY_ONE" }).closest("tr") as HTMLElement);
    expect(ready.getByText("Ready for paper")).toBeInTheDocument();
    expect(ready.getByText(/48% a year, worst fall -28%/)).toBeInTheDocument();
  });

  it("hides the outer holdout column and count from someone who is not the owner", async () => {
    backend(false);
    render(<Providers><PipelinePage /></Providers>);
    await screen.findByTestId("funnel");
    expect(screen.queryByText("Passed outer holdout")).not.toBeInTheDocument();
    expect(screen.queryByText("Outer holdout 2025-2026")).not.toBeInTheDocument();
  });

  it("has one place to run: a popup listing families with studies not run yet, to run a whole family", async () => {
    backend(true, true);
    render(<Providers><PipelinePage /></Providers>);
    await screen.findByTestId("funnel");
    fireEvent.click(await screen.findByRole("button", { name: "Run strategies" }));
    expect(await screen.findByText("Technical Screener 2")).toBeInTheDocument();
    expect(screen.getByText("Golden Cross")).toBeInTheDocument();
    expect(screen.getByText(/uncommitted code/)).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: /^Run\s+strategies$/ }); // the page's, then the popup's
    expect(buttons[buttons.length - 1]).toBeDisabled(); // nothing chosen yet
    fireEvent.click(screen.getByLabelText(/Technical Screener 2/)); // the whole family
    fireEvent.click(screen.getByRole("button", { name: "Run 2 strategies" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual(["/api/studies/20/runs", "/api/studies/21/runs"]));
    expect(calls.filter((c) => c.method === "POST").every((c) => (c.body as { chain: boolean }).chain)).toBe(true);
  });

  it("can run a single study of a family, and definitions with no study in a chosen family", async () => {
    backend(true);
    render(<Providers><PipelinePage /></Providers>);
    fireEvent.click(await screen.findByRole("button", { name: "Run strategies" }));
    fireEvent.click(await screen.findByLabelText(/Volume Breakout/));
    fireEvent.change(await screen.findByLabelText("Research family for these"), { target: { value: "5" } });
    fireEvent.click(screen.getByLabelText(/NEW_TWO/));
    fireEvent.click(screen.getByRole("button", { name: "Run 2 strategies" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "POST")).toHaveLength(2));
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts[0]).toMatchObject({ path: "/api/studies/21/runs", body: { chain: true } });
    expect(posts[1]).toMatchObject({ path: "/api/strategies/definitions/NEW_TWO/1/study", body: { family_id: 5, chain: true } });
  });

  it("offers no Run button to someone who may not run strategies", async () => {
    backend(false, false, ["research:read"]);
    render(<Providers><PipelinePage /></Providers>);
    await screen.findByTestId("funnel");
    expect(screen.queryByRole("button", { name: "Run strategies" })).not.toBeInTheDocument();
  });
});
