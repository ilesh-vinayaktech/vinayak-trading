import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import IntelligencePage from "@/app/research/intelligence/page";
import { Providers } from "@/app/providers";
import allocationsFixture from "./contract/intel_allocations.json";
import alphaFixture from "./contract/intel_alpha.json";
import notesFixture from "./contract/intel_notes.json";
import overview from "./contract/intel_overview.json";
import featuresFixture from "./contract/intel_features.json";
import funnel from "./contract/intel_funnel.json";
import progressFixture from "./contract/intel_progress.json";

const numbered = <T extends { id: number }>(rows: T[]) => rows.map((r, i) => ({ ...r, id: i + 1 }));
const alpha = { hypotheses: numbered(alphaFixture.hypotheses) };
const notes = { notes: numbered(notesFixture.notes) };
const allocations = { allocations: numbered(allocationsFixture.allocations) };
const progress = { jobs: progressFixture.jobs.map((j, i) => ({ ...j, id: i + 1 })) }; // the fixture scrubs every id to 0; real ids are unique

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/research/intelligence",
  useSearchParams: () => new URLSearchParams(""),
}));

const who = { user: { id: "u1", email: "jane@example.com", name: "Jane", role: "TRADER", permissions: ["research:read"], mfa_enabled: true, enrolment_required: false, must_change_password: false } };
const empty = {
  overview: { features: { by_status: {} }, alpha: { tests_ever_run: 0, by_status: {} }, factory: { definitions: 0, experiments: 0, trials: 0 }, notes: { total: 0 }, health: [], allocation: null },
  alpha: { hypotheses: [] },
  notes: { notes: [] },
};
const seen: string[] = [];
function backend(table: { overview: unknown; alpha: unknown; notes: unknown; progress?: unknown; funnel?: unknown; features?: unknown }) {
  seen.length = 0;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    seen.push(url.pathname + url.search);
    const body = { "/api/auth/me": who, "/api/intel/overview": table.overview, "/api/intel/alpha": table.alpha, "/api/intel/notes": table.notes, "/api/intel/allocations": allocations, "/api/intel/progress": table.progress ?? { jobs: [] }, "/api/intel/funnel": table.funnel ?? funnel, "/api/intel/features": table.features ?? featuresFixture }[url.pathname];
    if (body === undefined) return new Response(JSON.stringify({ detail: "no route" }), { status: 404 });
    return new Response(JSON.stringify(body), { status: 200 });
  });
}
const mount = () => render(<Providers><IntelligencePage /></Providers>);
afterEach(() => vi.unstubAllGlobals());

describe("Research intelligence", () => {
  it("shows what has been recorded: counts, health, allocation advice, alpha tests and notes", async () => {
    backend({ overview, alpha, notes });
    mount();
    expect(await screen.findByText("Where the research stands")).toBeTruthy();
    expect(screen.getByText("34 draft, 1 usable")).toBeTruthy();
    expect(screen.getByText("Alpha tests ever run")).toBeTruthy();
    expect(screen.getByText("Degraded")).toBeTruthy();
    expect(screen.getByText(/DEGRADED: mean return/)).toBeTruthy();
    expect(screen.getByText(/Advice only, nothing was changed/)).toBeTruthy();
    const tests = within(await screen.findByRole("table", { name: "Alpha hypotheses" }));
    expect(tests.getByText("ret_5d v1")).toBeTruthy();
    expect(tests.getByText("Worth validating")).toBeTruthy();
    expect(tests.getByText("Rejected")).toBeTruthy();
    const memory = within(await screen.findByRole("table", { name: "Research notes" }));
    expect(memory.getByText("capital")).toBeTruthy();
  });

  it("says plainly that nothing has been recorded yet instead of showing zeros as results", async () => {
    backend(empty);
    mount();
    expect(await screen.findByText("No health check has run yet")).toBeTruthy();
    expect(screen.getByText("No allocation advice yet")).toBeTruthy();
    expect(screen.getByText("No alpha test has been recorded")).toBeTruthy();
    expect(screen.getByText("No notes match")).toBeTruthy();
    expect(screen.getByText("None yet")).toBeTruthy();
  });

  it("shows a running job's steps, its current action and a progress bar, and a finished one as finished", async () => {
    backend({ overview, alpha, notes, progress });
    mount();
    const running = within(await screen.findByTestId("job-feature_validation"));
    expect(running.getByText("Running")).toBeTruthy();
    expect(running.getByText("3 of 12 done")).toBeTruthy();
    expect(running.getByText(/checking ret_20d: look-ahead test 2 of 5/)).toBeTruthy();
    const bar = running.getByRole("progressbar");
    expect(bar.getAttribute("aria-valuenow")).toBe("3");
    expect(bar.getAttribute("aria-valuemax")).toBe("12");
    const done = within(screen.getByTestId("job-alpha_discovery"));
    expect(done.getByText("Finished")).toBeTruthy();
    expect(done.getByText("4 of 4 done")).toBeTruthy();
  });

  it("warns when a running job has gone quiet or its process is gone, and does not for a healthy one", async () => {
    const job = (over: object) => ({ ...progress.jobs[0], ...over });
    backend({ overview, alpha, notes, progress: { jobs: [job({ id: 1, job: "quiet", status: "RUNNING", stalled: true, alive: true, quiet_s: 700 }), job({ id: 2, job: "gone", status: "RUNNING", stalled: true, alive: false, quiet_s: 30 }), job({ id: 3, job: "fine", stalled: false, quiet_s: 5 })] } });
    mount();
    expect(within(await screen.findByTestId("job-quiet")).getByText(/No update for 11m 40s/)).toBeTruthy();
    expect(within(screen.getByTestId("job-gone")).getByText(/process running this job is gone/)).toBeTruthy();
    expect(within(screen.getByTestId("job-fine")).queryByText(/No update for/)).toBeNull();
    expect(within(screen.getByTestId("job-quiet")).getByText("May be stuck")).toBeTruthy();
  });

  it("draws the funnel: what went in, what moved on, what dropped and why, and which stages are not linked yet", async () => {
    backend({
      overview, alpha, notes,
      funnel: {
        stages: [
          { key: "features", title: "Features", unit: "features", entered: 12, passed: 3, connected: true, note: "n", dropped: [{ reason: "Failed validation", count: 2 }, { reason: "Waiting to be validated", count: 7 }] },
          { key: "alpha", title: "Alpha tests", unit: "tests", entered: 40, passed: 4, connected: true, note: "n", dropped: [{ reason: "Effect too small to matter", count: 30 }] },
          { key: "trials", title: "Experiment trials", unit: "trials", entered: 0, passed: 0, connected: true, note: "n", dropped: [] },
          { key: "validation", title: "Validation gates", unit: "strategies", entered: 0, passed: 0, connected: false, note: "Not yet linked to candidates.", dropped: [] },
        ],
      },
    });
    mount();
    const features = within(await screen.findByTestId("stage-features"));
    expect(features.getByText("12")).toBeTruthy();
    expect(features.getByText("3 moved on (25%)")).toBeTruthy();
    expect(features.getByText("9 dropped (75%)")).toBeTruthy();
    expect(features.getByText("Failed validation")).toBeTruthy();
    expect(features.getByRole("img").getAttribute("aria-label")).toBe("3 of 12 moved on, 9 dropped");
    const alphaStage = within(screen.getByTestId("stage-alpha"));
    expect(alphaStage.getByText("4 moved on (10%)")).toBeTruthy();
    expect(alphaStage.getByText("Effect too small to matter")).toBeTruthy();
    expect(within(screen.getByTestId("stage-trials")).getByText("Nothing has reached this stage yet.")).toBeTruthy();
    const unlinked = within(screen.getByTestId("stage-validation"));
    expect(unlinked.getByText("Not linked yet")).toBeTruthy();
    expect(unlinked.queryByText(/moved on/)).toBeNull();
  });

  it("lights up the pipeline step that is running now and marks the finished, idle and not-automated ones", async () => {
    const job = (over: object) => ({ ...progress.jobs[0], ...over });
    backend({ overview, alpha, notes, progress: { jobs: [job({ id: 1, job: "feature_validation", status: "RUNNING", done: 3, total: 12, stalled: false }), job({ id: 2, job: "alpha_discovery", status: "DONE", done: 4, total: 4 })] } });
    mount();
    const validate = await screen.findByTestId("step-0");
    await waitFor(() => expect(validate.getAttribute("data-state")).toBe("running"));
    expect(within(validate).getByText("running · 3 of 12")).toBeTruthy();
    expect(screen.getByTestId("step-1").getAttribute("data-state")).toBe("idle");
    expect(screen.getByTestId("step-2").getAttribute("data-state")).toBe("done");
    expect(screen.getByTestId("step-3").getAttribute("data-state")).toBe("manual");
    expect(within(screen.getByTestId("step-6")).getByText("not automated yet")).toBeTruthy();
  });

  it("flags a stuck or failed step in the strip", async () => {
    const job = (over: object) => ({ ...progress.jobs[0], ...over });
    backend({ overview, alpha, notes, progress: { jobs: [job({ id: 1, job: "feature_validation", status: "RUNNING", stalled: true }), job({ id: 2, job: "feature_computation", status: "FAILED" })] } });
    mount();
    await waitFor(() => expect(screen.getByTestId("step-0").getAttribute("data-state")).toBe("stuck"));
    expect(screen.getByTestId("step-1").getAttribute("data-state")).toBe("failed");
  });

  it("gives a time estimate when it has one, and says why when it does not", async () => {
    const job = (over: object) => ({ ...progress.jobs[0], status: "RUNNING", stalled: false, alive: true, ...over });
    backend({
      overview, alpha, notes,
      progress: {
        jobs: [
          job({ id: 1, job: "feature_validation", estimate: "ok", per_step_s: 600, eta_s: 4320 }),
          job({ id: 2, job: "feature_computation", estimate: "waiting" }),
          job({ id: 3, job: "alpha_discovery", estimate: "uneven" }),
          job({ id: 4, job: "other", estimate: "overrun", per_step_s: 240 }),
        ],
      },
    });
    mount();
    const ok = within(await screen.findByTestId("job-feature_validation"));
    expect(ok.getByTestId("estimate").textContent).toMatch(/About 1h 12m left, around \d.*Based on 10m 00s per finished step; later steps may differ\./);
    expect(within(screen.getByTestId("job-feature_computation")).getByText(/Estimating: needs two finished steps/)).toBeTruthy();
    expect(within(screen.getByTestId("job-alpha_discovery")).getByText(/No estimate: this job's steps are very different in size/)).toBeTruthy();
    expect(within(screen.getByTestId("job-other")).getByText(/Taking longer than the average step \(4m 00s\)/)).toBeTruthy();
  });

  it("shows no estimate line for a finished job", async () => {
    backend({ overview, alpha, notes, progress });
    mount();
    const done = within(await screen.findByTestId("job-alpha_discovery"));
    expect(done.queryByTestId("estimate")).toBeNull();
  });

  it("lists every feature with what it measures, and why the last validation passed or failed", async () => {
    backend({ overview, alpha, notes });
    mount();
    const list = within(await screen.findByRole("list", { name: "Features" }));
    expect(list.getAllByTestId(/^feature-/).length).toBe(35);
    const good = within(list.getByTestId("feature-ret_5d"));
    expect(good.getByText("Usable")).toBeTruthy();
    expect(good.getByTestId("family").textContent).toBe("price");
    expect(within(list.getByTestId("feature-fund_roe")).getByTestId("family").textContent).toBe("fundamental");
    expect(within(list.getByTestId("feature-rsi_14d")).getByTestId("family").textContent).toBe("technical");
    expect(good.getByText(/close\[t\] \/ close\[t-n\] - 1/)).toBeTruthy();
    expect(good.getAllByText(/^✓/).length).toBe(4);
    expect(good.getByText(/98.97% of eligible days have a value/)).toBeTruthy();
    const bad = within(list.getByTestId("feature-vol_20d"));
    expect(bad.getByText("Failed")).toBeTruthy();
    expect(bad.getByText(/look-ahead: 3 value\(s\) changed when later data was removed/)).toBeTruthy();
    expect(bad.getByText(/^✗ No look-ahead/)).toBeTruthy();
    expect(bad.getAllByText(/^✓/).length).toBe(3);
    const fresh = within(list.getByTestId("feature-ret_20d"));
    expect(fresh.getByText("Not validated yet")).toBeTruthy();
    expect(fresh.getByText(/never validated/)).toBeTruthy();
    expect(screen.getByText(/A new feature is a code change, not a setting on this page/)).toBeTruthy();
  });

  it("marks the feature being validated right now and shows its current step", async () => {
    const job = { ...progress.jobs[0], id: 1, job: "feature_validation", status: "RUNNING", phase: "checking ret_20d", message: "look-ahead test 2 of 5 (cut at 2023-01-02)", stalled: false, alive: true };
    backend({ overview, alpha, notes, progress: { jobs: [job] } });
    mount();
    const row = await screen.findByTestId("feature-ret_20d");
    await waitFor(() => expect(row.getAttribute("data-state")).toBe("checking"));
    expect(within(row).getByText("Checking now")).toBeTruthy();
    expect(within(row).getByText(/Being checked now: look-ahead test 2 of 5/)).toBeTruthy();
    expect(screen.getByTestId("feature-ret_60d").getAttribute("data-state")).toBe("unchecked");
    expect(screen.getByTestId("feature-ret_5d").getAttribute("data-state")).toBe("passed");
    expect(screen.getByText(/validation running · updates every 4 seconds/)).toBeTruthy();
  });

  it("says so when no job has reported yet", async () => {
    backend(empty);
    mount();
    expect(await screen.findByText("No job has reported progress yet")).toBeTruthy();
  });

  it("asks the API for only the chosen verdict and for the searched notes", async () => {
    backend({ overview, alpha, notes });
    mount();
    await screen.findByText("Where the research stands");
    fireEvent.change(screen.getByLabelText("Verdict filter"), { target: { value: "CANDIDATE" } });
    await waitFor(() => expect(seen).toContain("/api/intel/alpha?status=CANDIDATE"));
    fireEvent.change(screen.getByLabelText("Search notes"), { target: { value: "capital" } });
    await waitFor(() => expect(seen).toContain("/api/intel/notes?q=capital"));
  });

  it("explains a failed load instead of showing a blank page", async () => {
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => (new URL(String(input)).pathname === "/api/auth/me" ? new Response(JSON.stringify(who)) : new Response(JSON.stringify({ detail: "not allowed" }), { status: 403 })));
    mount();
    expect(await screen.findByText(/Could not load the research overview/)).toBeTruthy();
  });
});
