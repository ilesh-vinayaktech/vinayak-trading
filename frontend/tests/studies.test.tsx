import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import StudiesPage from "@/app/research/studies/page";
import NewStudyPage from "@/app/research/studies/new/page";
import StudyPage from "@/app/research/studies/[id]/page";
import { holdoutFor, holdoutShare, trialCount } from "@/lib/studies";

const nav = vi.hoisted(() => ({ replace: vi.fn(), id: "7" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useParams: () => ({ id: nav.id }),
  usePathname: () => "/research/studies",
  useSearchParams: () => new URLSearchParams(""),
}));

const THRESHOLDS = { min_oos_sharpe: "0.8", min_dsr: "0.95", max_pbo: "0.2", max_drawdown_vs_benchmark: "1.25", owner_max_drawdown: "0.25", plateau_tolerance: "0.3", max_top3_concentration: "0.5", min_sharpe_over_benchmark: "0.2", min_oos_days: "252", min_regimes: "2", max_window_share: "0.5", min_benchmark_drawdown: "0.02" };
const OPTIONS = {
  strategies: [{ id: "trend_pullback", params: [
    { name: "trend_sma", choices: [100, 200], default: 200 }, { name: "entry_rsi", choices: [20, 25, 30], default: 25 },
    { name: "exit_rsi", choices: [55, 60, 65], default: 60 }, { name: "max_positions", choices: [5, 10, 20], default: 10 },
  ] }],
  segments: ["large", "mid", "small", "micro"], timeframes: ["1D"], brokers: [{ broker: "zerodha", product: "DELIVERY" }],
  frozen_through: "2026-11-11", survivorship_safe_from: "2019-10-01", segment_lists_from: "2018-08-01", max_trials: 64, holdout_share: [0.05, 0.5], thresholds: THRESHOLDS,
};
const SPEC = { name: "Pullback, large and mid caps", hypothesis: "Buying a 5-day RSI dip inside a 200-day uptrend beats buy-and-hold.", strategy_id: "trend_pullback",
  grid: { entry_rsi: [20, 25, 30], exit_rsi: [60, 65], max_positions: [10], trend_sma: [100, 200] }, universe: { segments: ["large", "mid"], before_segment_lists: "traded_value_rank", min_history_sessions: 252 },
  timeframe: "1D", start: "2019-10-01", end: "2026-11-06", holdout_start: "2024-05-01", capital: "1000000", capacity_multiple: "3", broker: "zerodha", product: "DELIVERY", slippage: { base_bps: "5", participation_bps_per_pct: "5", volatility_fraction: "0" }, thresholds: THRESHOLDS, accept_survivorship_bias: false };
const STUDY = { experiment_id: 7, name: SPEC.name, strategy_id: "trend_pullback", hypothesis: SPEC.hypothesis, registered_at: "2026-11-12T06:00:00+00:00", holdout_opened_at: null, spec: SPEC,
  combinations: Array.from({ length: 12 }, () => ({ entry_rsi: 20 })), data_freeze: { id: "f", through: "2026-11-11" },
  cost_schedules: [{ schedule_id: "a", version: "1", broker: "zerodha", product: "DELIVERY", status: "extracted_unverified", valid_from: "2026-03-01", valid_until: null }],
  trials_planned: 12, trials_run: 0, sha256: "abcdef0123456789abcdef", owner_user_id: "u1" };
const NO_RUN = { run: null, trials: [], universe_coverage: [] };
const RUN = { run_id: 3, experiment_id: 7, status: "RUNNING", total: 12, done: 4, current: "entry_rsi 25, exit_rsi 60", error: null, requested_by: "u1", created_at: "2026-11-12T06:00:00+00:00", started_at: "2026-11-12T06:00:05+00:00", finished_at: null };
const TRIAL = (id: number, rsi: number, sharpe: number | null, status = "DONE") => ({ trial_id: id, params: { entry_rsi: rsi, trend_sma: 200 }, status, metrics: sharpe === null ? null : { sharpe, cagr: 0.123, max_drawdown: -0.0912, trades: 1437, costs: 52000.4 }, error: status === "FAILED" ? "DataNotReady: x" : null, seconds: 164.6, finished_at: "2026-11-12T06:10:00+00:00" });
const COVERAGE = [{ list: "2023-12-31", from: "2024-02-01", until: "2024-07-31", in_segments: 250, matched: 244, usable: 238 }];
const who = (perms: string[]) => ({ user: { id: "u1", email: "j@example.com", name: "Jane", role: "TRADER", permissions: perms, mfa_enabled: true, enrolment_required: false, must_change_password: false } });
const SAVED = { label: "UNVALIDATED", options: { universes: [], timeframes: [], params: { trend_sma: [], entry_rsi: [], exit_rsi: [], max_positions: [] } },
  strategies: [{ config_id: "c1", name: "My paper strategy", strategy_id: "trend_pullback", universe: "nifty200", max_instruments: null, timeframe: "1D", params: { trend_sma: 200, entry_rsi: 25, exit_rsi: 60, max_positions: 5 }, in_use: true, created_at: "2026-11-11T10:00:00+00:00" }] };

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
const mount = (ui: React.ReactNode) => render(<Providers>{ui}</Providers>);
const posted = () => calls.filter((c) => c.method === "POST");

beforeEach(() => {
  document.cookie = "csrf=tok";
  nav.replace.mockClear();
});
afterEach(() => vi.unstubAllGlobals());

describe("the form's arithmetic", () => {
  it("counts every combination as a trial", () => {
    expect(trialCount({})).toBe(0);
    expect(trialCount({ a: [1, 2], b: [1, 2, 3] })).toBe(6);
  });
  it("works out the holdout's share and the date that leaves a given share untouched", () => {
    expect(holdoutShare("2020-01-01", "2020-12-31", "2020-10-01")).toBeCloseTo(91 / 365);
    expect(holdoutShare("2020-01-01", "2020-01-01", "2020-01-01")).toBeNull();
    expect(holdoutShare("", "2020-01-01", "2020-01-01")).toBeNull();
    expect(holdoutFor("2020-01-01", "2020-12-31", 25)).toBe("2020-10-01");
  });
});

describe("the list of studies", () => {
  it("shows each study's stocks, period, holdout and trials, and lets a trader start a new one", async () => {
    backend({ "GET /api/auth/me": who(["research:read", "strategy:own"]), "GET /api/studies": { studies: [STUDY] } });
    mount(<StudiesPage />);
    const row = (await screen.findByRole("link", { name: SPEC.name })).closest("tr") as HTMLElement;
    expect(within(row).getByText("0 of 12")).toBeInTheDocument();
    expect(within(row).getByText("large, mid")).toBeInTheDocument();
    expect(within(row).getByText("2024-05-01")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: SPEC.name })).toHaveAttribute("href", "/research/studies/7");
    await waitFor(() => expect(screen.getByRole("link", { name: "New study" })).toHaveAttribute("href", "/research/studies/new"));
  });
  it("invites the first study, and does not offer one to someone who cannot run strategies", async () => {
    backend({ "GET /api/auth/me": who(["research:read"]), "GET /api/studies": { studies: [] } });
    mount(<StudiesPage />);
    expect(await screen.findByText("No studies yet")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "New study" })).not.toBeInTheDocument();
  });
  it("says so when the list cannot be loaded", async () => {
    backend({ "GET /api/auth/me": who(["research:read"]) });
    mount(<StudiesPage />);
    expect(await screen.findByText("Could not load the studies")).toBeInTheDocument();
  });
});

describe("a new study", () => {
  const open = async (extra: Record<string, unknown> = {}) => {
    backend({ "GET /api/auth/me": who(["research:read", "strategy:own"]), "GET /api/studies/options": OPTIONS, "GET /api/strategies": SAVED, ...extra });
    mount(<NewStudyPage />);
    await screen.findByLabelText("Name");
  };
  const fillIdea = () => {
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "  My study  " } });
    fireEvent.change(screen.getByLabelText("Hypothesis"), { target: { value: "Dips inside an uptrend recover within days." } });
  };
  const register = () => screen.getByRole("button", { name: "Register study" });

  it("starts from each setting's default, the last frozen day, the safe start and a 25% holdout", async () => {
    await open();
    expect(screen.getByText(/1 trial \(at most 64\)/)).toBeInTheDocument();
    expect(screen.getByLabelText("From")).toHaveValue("2019-10-01");
    expect(screen.getByLabelText("To")).toHaveValue("2026-11-11");
    expect(screen.getByText(/keeps the last 25% untouched/)).toBeInTheDocument();
    expect(screen.getByLabelText("entry_rsi 25")).toBeChecked();
    expect(screen.getByLabelText("Worst drawdown you accept (0.25 = 25%)")).toHaveValue("0.25");
  });

  it("will not register until the idea is written down, and shows what is missing", async () => {
    await open();
    expect(register()).toBeDisabled();
    expect(screen.getByText("Give the study a name.")).toBeInTheDocument();
    fillIdea();
    expect(register()).toBeEnabled();
  });

  it("asks before locking, then registers exactly what was chosen and opens the study", async () => {
    await open({ "POST /api/studies": { experiment_id: 7 } });
    fillIdea();
    fireEvent.click(screen.getByLabelText("entry_rsi 20"));
    fireEvent.click(screen.getByLabelText("trend_sma 100"));
    expect(screen.getByText(/4 trials/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Small cap (251-500)"));
    fireEvent.click(screen.getByRole("button", { name: "Last 30%" }));
    fireEvent.change(screen.getByLabelText("Out-of-sample Sharpe, at least"), { target: { value: "1.0" } });
    fireEvent.change(screen.getByLabelText("Slippage: fixed (bps)"), { target: { value: "8" } });
    fireEvent.click(register());
    expect(posted()).toHaveLength(0); // not yet: the dialog asks first
    fireEvent.click(await screen.findByRole("button", { name: "Register and lock" }));
    await waitFor(() => expect(posted()).toHaveLength(1));
    const b = posted()[0]?.body as Record<string, unknown>;
    expect(b).toMatchObject({
      name: "My study", strategy_id: "trend_pullback", timeframe: "1D", start: "2019-10-01", end: "2026-11-11", capital: "1000000", capacity_multiple: "3",
      broker: "zerodha", product: "DELIVERY", accept_survivorship_bias: false,
      slippage: { base_bps: "8", participation_bps_per_pct: "5", volatility_fraction: "0" },
      grid: { trend_sma: [100, 200], entry_rsi: [20, 25], exit_rsi: [60], max_positions: [10] },
      universe: { segments: ["large", "mid", "small"], before_segment_lists: "traded_value_rank", min_history_sessions: 252 },
    });
    expect((b.thresholds as Record<string, string>).min_oos_sharpe).toBe("1.0");
    expect(b.holdout_start).toBe(holdoutFor("2019-10-01", "2026-11-11", 30));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/research/studies/7"));
  });

  it("an early start needs the survivorship bias accepted, and asks how to size stocks before AMFI's first list", async () => {
    await open();
    fillIdea();
    fireEvent.change(screen.getByLabelText("From"), { target: { value: "2016-01-01" } });
    expect(screen.getByText("Survivorship bias")).toBeInTheDocument();
    expect(register()).toBeDisabled();
    fireEvent.click(screen.getByLabelText("I accept this bias for this study"));
    fireEvent.click(screen.getByRole("button", { name: "Last 25%" }));
    expect(screen.getByLabelText("Before 2018-08-01 (no AMFI list yet)")).toHaveValue("traded_value_rank");
    expect(register()).toBeEnabled();
  });

  it("refuses a grid larger than the trial cap, a holdout out of bounds and an end past the frozen history", async () => {
    await open({ "GET /api/studies/options": { ...OPTIONS, max_trials: 2 } });
    fillIdea();
    fireEvent.click(screen.getByLabelText("entry_rsi 20"));
    fireEvent.click(screen.getByLabelText("entry_rsi 30"));
    expect(screen.getByText(/3 trials is more than 2/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Holdout starts"), { target: { value: "2026-11-01" } });
    expect(screen.getByText(/Keep the holdout between 5% and 50%/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-11-20" } });
    expect(screen.getByText(/must end by 2026-11-11/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Large cap (ranks 1-100)"));
    fireEvent.click(screen.getByText("Mid cap (101-250)"));
    expect(screen.getByText("Pick at least one market-cap segment.")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("entry_rsi 20"));
    fireEvent.click(screen.getByLabelText("entry_rsi 25"));
    fireEvent.click(screen.getByLabelText("entry_rsi 30"));
    expect(screen.getByText("Pick at least one value for every parameter.")).toBeInTheDocument();
  });

  it("fills the settings from a saved strategy", async () => {
    await open();
    await waitFor(() => expect(screen.getByLabelText("Start from a saved strategy")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Start from a saved strategy"), { target: { value: "c1" } });
    expect(screen.getByLabelText("max_positions 5")).toBeChecked();
    expect(screen.getByLabelText("max_positions 10")).not.toBeChecked();
  });

  it("shows the server's reason when registering is refused", async () => {
    await open({ "POST /api/studies": [400, { detail: "there is already a study called 'My study'" }] });
    fillIdea();
    fireEvent.click(register());
    fireEvent.click(await screen.findByRole("button", { name: "Register and lock" }));
    expect(await screen.findByText("there is already a study called 'My study'")).toBeInTheDocument();
  });

  it("warns when there is no frozen history to pin the study to", async () => {
    backend({ "GET /api/auth/me": who(["research:read", "strategy:own"]), "GET /api/studies/options": { ...OPTIONS, frozen_through: null }, "GET /api/strategies": SAVED });
    mount(<NewStudyPage />);
    expect(await screen.findByText("No frozen price history")).toBeInTheDocument();
  });
});

describe("a registered study", () => {
  it("shows every locked setting, the pass bar in words, and that the holdout is untouched", async () => {
    backend({ "GET /api/auth/me": who(["research:read"]), "GET /api/studies/7": STUDY, "GET /api/studies/7/results": NO_RUN });
    mount(<StudyPage />);
    expect(await screen.findByText("Locked")).toBeInTheDocument();
    expect(screen.getByText("0 of 12 trials run")).toBeInTheDocument();
    expect(screen.getByText("Holdout untouched")).toBeInTheDocument();
    expect(screen.getByText(/entry_rsi: 20, 25, 30/)).toBeInTheDocument();
    expect(screen.getByText(/large, mid; at least 252 sessions/)).toBeInTheDocument();
    expect(screen.getByText("Worst drawdown you accept (0.25 = 25%)")).toBeInTheDocument();
    expect(screen.getByText(/frozen through 2026-11-11/)).toBeInTheDocument();
  });
  it("says when the holdout has been opened and when the owner accepted the survivorship bias", async () => {
    const opened = { ...STUDY, holdout_opened_at: "2026-11-20T06:00:00+00:00", spec: { ...SPEC, start: "2016-01-01", accept_survivorship_bias: true } };
    backend({ "GET /api/auth/me": who(["research:read"]), "GET /api/studies/7": opened, "GET /api/studies/7/results": NO_RUN });
    mount(<StudyPage />);
    expect(await screen.findByText("Holdout opened")).toBeInTheDocument();
    expect(screen.getByText(/bias accepted by the owner/)).toBeInTheDocument();
  });
  it("says so when the study cannot be loaded", async () => {
    backend({ "GET /api/auth/me": who(["research:read"]) });
    mount(<StudyPage />);
    expect(await screen.findByText("Could not load the study")).toBeInTheDocument();
  });
});

describe("running a study", () => {
  const open = (results: unknown, perms = ["research:read", "strategy:own"], extra: Record<string, unknown> = {}) => {
    backend({ "GET /api/auth/me": who(perms), "GET /api/studies/7": STUDY, "GET /api/studies/7/results": results, ...extra });
    mount(<StudyPage />);
  };
  it("offers to start the first run to someone who may, and queues it", async () => {
    open(NO_RUN, undefined, { "POST /api/studies/7/runs": { run_id: 3 } });
    expect(await screen.findByText("No trials run yet")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Run the trials" }));
    await waitFor(() => expect(posted()[0]?.path).toBe("/api/studies/7/runs"));
    expect(await screen.findByText("Run queued.")).toBeInTheDocument();
  });
  it("does not offer a run to someone who cannot run strategies", async () => {
    open(NO_RUN, ["research:read"]);
    expect(await screen.findByText("No trials run yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run the trials" })).not.toBeInTheDocument();
  });
  it("shows progress while running, each finished combination's numbers, and the universe coverage", async () => {
    open({ run: RUN, trials: [TRIAL(1, 20, 1.234), TRIAL(2, 25, null, "FAILED")], universe_coverage: COVERAGE });
    expect(await screen.findByText("Running")).toBeInTheDocument();
    expect(screen.getByText("4 of 12 combinations")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Progress" })).toHaveAttribute("aria-valuenow", "33");
    expect(screen.getByText(/now: entry_rsi 25/)).toBeInTheDocument();
    const row = screen.getByText("entry_rsi 20 · trend_sma 200").closest("tr") as HTMLElement;
    expect(within(row).getByText("1.23")).toBeInTheDocument();
    expect(within(row).getByText("12.3%")).toBeInTheDocument();
    expect(within(row).getByText("-9.1%")).toBeInTheDocument();
    expect(within(row).getByText("1437")).toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByText("2023-12-31")).toBeInTheDocument();
    expect(screen.getByText("238")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run again" })).not.toBeInTheDocument(); // one at a time
  });
  it("lets a queued run be cancelled", async () => {
    open({ run: { ...RUN, status: "QUEUED", done: 0, total: 0, current: null, started_at: null }, trials: [], universe_coverage: [] }, undefined, { "POST /api/studies/runs/3/cancel": { ok: true } });
    expect(await screen.findByText("Waiting for a worker")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(posted()[0]?.path).toBe("/api/studies/runs/3/cancel"));
  });
  it("shows why a run stopped and offers to run again", async () => {
    open({ run: { ...RUN, status: "FAILED", current: null, error: "no stocks to trade: the chosen segments hold none", finished_at: "2026-11-12T07:00:00+00:00" }, trials: [], universe_coverage: [] });
    expect(await screen.findByText("The run stopped")).toBeInTheDocument();
    expect(screen.getByText(/no stocks to trade/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run again" })).toBeInTheDocument();
  });
  it("shows a finished run without a progress bar, and the server's reason when starting is refused", async () => {
    open({ run: { ...RUN, status: "DONE", done: 12, current: null, finished_at: "2026-11-12T08:00:00+00:00" }, trials: [TRIAL(1, 20, 0.5)], universe_coverage: [] }, undefined, { "POST /api/studies/7/runs": [400, { detail: "this study already has a run queued or running" }] });
    expect(await screen.findByText("Finished")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Run again" }));
    expect(await screen.findByText("this study already has a run queued or running")).toBeInTheDocument();
  });
  it("says so when the results cannot be loaded", async () => {
    backend({ "GET /api/auth/me": who(["research:read"]), "GET /api/studies/7": STUDY });
    mount(<StudyPage />);
    expect(await screen.findByText("Could not load the results.")).toBeInTheDocument();
  });
});
