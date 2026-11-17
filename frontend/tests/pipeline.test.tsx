import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PipelinePage from "@/app/research/pipeline/page";
import { Providers } from "@/app/providers";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/research/pipeline",
  useSearchParams: () => new URLSearchParams(""),
}));

const me = { user: { id: "u1", email: "boss@example.com", name: "Boss", role: "ADMIN", permissions: ["research:read", "holdout:read"], mfa_enabled: true, must_enrol: false, must_change_password: false } };
const fig = (over: Record<string, unknown> = {}) => ({ passed: true, failed: [], cagr: 0.33, total_return: 4.5, sharpe: 1.23, max_drawdown: -0.28, benchmark_sharpe: 0.9, window: null, oos_sharpe: 1.4, ...over });
const row = (over: Record<string, unknown>) => ({ experiment_id: 1, name: "X", stage: "development", outcome: "stopped", why: "Failed development: oos_sharpe.", paper: null, development: fig({ passed: false, failed: ["oos_sharpe"] }), inner: null, outer: null, ...over });
const rows = [
  row({ experiment_id: 1, name: "FAILED_DEV" }),
  row({ experiment_id: 2, name: "READY_ONE", stage: "paper", outcome: "ready", why: "Passed development and both holdouts. Ready for paper trading.", paper: "ready", development: fig(), inner: fig({ cagr: 0.48 }), outer: { overall: "PASS", checks: [] } }),
  row({ experiment_id: 3, name: "FAILED_OUTER", stage: "outer", outcome: "stopped", why: "Failed the outer holdout (2025-2026): holdout_sharpe.", development: fig(), inner: fig(), outer: { overall: "FAIL", checks: [{ gate: "holdout_sharpe", verdict: "FAIL", later: false }] } }),
];
function backend(outer_visible: boolean) {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const path = new URL(String(input)).pathname;
    const body = path === "/api/auth/me" ? me : path === "/api/pipeline" ? { rows, outer_visible } : { detail: "no route" };
    return new Response(JSON.stringify(body), { status: path === "/api/auth/me" || path === "/api/pipeline" ? 200 : 404 });
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
});
