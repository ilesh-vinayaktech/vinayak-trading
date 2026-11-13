import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import StudiesPage from "@/app/research/studies/page";
import NewStudyPage from "@/app/research/studies/new/page";
import StudyPage from "@/app/research/studies/[id]/page";
import { holdoutFor, holdoutShare, orderSizeWarnings, trialCount } from "@/lib/studies";

const nav = vi.hoisted(() => ({ replace: vi.fn(), id: "7", search: "" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  useParams: () => ({ id: nav.id }),
  usePathname: () => "/research/studies",
  useSearchParams: () => new URLSearchParams(nav.search),
}));

const THRESHOLDS = { min_oos_sharpe: "0.8", min_dsr: "0.95", max_pbo: "0.2", max_drawdown_vs_benchmark: "1.25", owner_max_drawdown: "0.25", plateau_tolerance: "0.3", max_top3_concentration: "0.5", min_sharpe_over_benchmark: "0.2", min_oos_days: "252", min_regimes: "2", max_window_share: "0.5", min_benchmark_drawdown: "0.02" };
const OPTIONS = {
  strategies: [{ id: "trend_pullback", params: [
    { name: "trend_sma", choices: [100, 200], default: 200 }, { name: "entry_rsi", choices: [20, 25, 30], default: 25 },
    { name: "exit_rsi", choices: [55, 60, 65], default: 60 }, { name: "max_positions", choices: [5, 10, 20], default: 10 },
  ] }],
  segments: ["large", "mid", "small", "micro"], timeframes: ["1D"], brokers: [{ broker: "zerodha", product: "DELIVERY" }], benchmarks: [{ name: "Nifty 200 Total Return Index (gross)", usable: true, default: true }, { name: "Nifty 50 Total Return Index (gross)", usable: true, default: false }],
  frozen_through: "2026-11-11", survivorship_safe_from: "2019-10-01", segment_lists_from: "2018-08-01", max_trials: 64, holdout_share: [0.05, 0.5], thresholds: THRESHOLDS,
};
const SPEC = { name: "Pullback, large and mid caps", hypothesis: "Buying a 5-day RSI dip inside a 200-day uptrend beats buy-and-hold.", strategy_id: "trend_pullback",
  grid: { entry_rsi: [20, 25, 30], exit_rsi: [60, 65], max_positions: [10], trend_sma: [100, 200] }, universe: { segments: ["large", "mid"], before_segment_lists: "traded_value_rank", min_history_sessions: 252 },
  timeframe: "1D", start: "2019-10-01", end: "2026-11-06", holdout_start: "2024-05-01", capital: "1000000", capacity_multiple: "3", broker: "zerodha", product: "DELIVERY", slippage: { base_bps: "5", participation_bps_per_pct: "5", volatility_fraction: "0" }, min_order_value: "0", max_order_value: null, benchmark: "Nifty 200 Total Return Index (gross)", thresholds: THRESHOLDS, accept_survivorship_bias: false };
const STUDY = { experiment_id: 7, name: SPEC.name, strategy_id: "trend_pullback", hypothesis: SPEC.hypothesis, registered_at: "2026-11-12T06:00:00+00:00", holdout_opened_at: null, spec: SPEC,
  combinations: Array.from({ length: 12 }, () => ({ entry_rsi: 20 })), data_freeze: { id: "f", through: "2026-11-11" },
  cost_schedules: [{ schedule_id: "a", version: "1", broker: "zerodha", product: "DELIVERY", status: "extracted_unverified", valid_from: "2026-03-01", valid_until: null }],
  trials_planned: 12, trials_run: 0, sha256: "abcdef0123456789abcdef", owner_user_id: "u1" };
const NO_RUN = { run: null, trials: [], universe_coverage: [] };
const RUN = { run_id: 3, experiment_id: 7, kind: "trials", status: "RUNNING", total: 12, done: 4, current: "entry_rsi 25, exit_rsi 60", step_done: 0, step_total: 0, cancel_requested: false, progress: null, error: null, requested_by: "u1", created_at: "2026-11-12T06:00:00+00:00", started_at: "2026-11-12T06:00:05+00:00", finished_at: null };
const TRIAL = (id: number, rsi: number, sharpe: number | null, status = "DONE") => ({ trial_id: id, params: { entry_rsi: rsi, trend_sma: 200 }, status, metrics: sharpe === null ? null : { sharpe, cagr: 0.123, max_drawdown: -0.0912, trades: 1437, costs: 52000.4 }, error: status === "FAILED" ? "DataNotReady: x" : null, seconds: 164.6, finished_at: "2026-11-12T06:10:00+00:00", backtest_run: id === 1 ? 2 : null });
const COVERAGE = [{ list: "2023-12-31", from: "2024-02-01", until: "2024-07-31", in_segments: 250, matched: 244, usable: 238 }];
const who = (perms: string[]) => ({ user: { id: "u1", email: "j@example.com", name: "Jane", role: "TRADER", permissions: perms, mfa_enabled: true, enrolment_required: false, must_change_password: false } });
const SAVED = { label: "UNVALIDATED", options: { universes: [], timeframes: [], params: { trend_sma: [], entry_rsi: [], exit_rsi: [], max_positions: [] } },
  strategies: [{ config_id: "c1", name: "My paper strategy", strategy_id: "trend_pullback", universe: "nifty200", max_instruments: null, timeframe: "1D", params: { trend_sma: 200, entry_rsi: 25, exit_rsi: 60, max_positions: 5 }, screen: null, in_use: true, created_at: "2026-11-11T10:00:00+00:00", stage: "RESEARCH" }] };

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
  nav.search = "";
});
afterEach(() => vi.unstubAllGlobals());

describe("order size advice", () => {
  it("warns when the largest order makes a position take days to build, using the biggest position in the grid", () => {
    const [w] = orderSizeWarnings("1000000", [5, 10], "10000", "15000");
    expect(w).toContain("₹2,00,000 (₹10,00,000 over 5 positions)");
    expect(w).toContain("about 14 days");
    expect(w).toContain("₹66,667 or more"); // a third of a position
  });
  it("is quiet when a position fills in a few days, when there is no limit, or when the inputs are not usable", () => {
    expect(orderSizeWarnings("1000000", [5], "10000", "100000")).toEqual([]); // 2 days
    expect(orderSizeWarnings("1000000", [5], "", "")).toEqual([]);
    expect(orderSizeWarnings("", [5], "", "100")).toEqual([]);
    expect(orderSizeWarnings("1000000", [], "", "100")).toEqual([]);
  });
  it("warns when the smallest order is bigger than the smallest position", () => {
    const [w] = orderSizeWarnings("1000000", [5, 20], "75000", "");
    expect(w).toContain("more than a position can be (₹50,000 with 20 positions)");
    expect(orderSizeWarnings("1000000", [5, 20], "50000", "")).toEqual([]);
  });
});

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

  it("can trade a screener: ready-made screens on prices or filed results are offered (not market-cap classes), and it registers as the strategy", async () => {
    const field = (key: string, label: string, kind: string) => ({ key, label, group: "g", kind, unit: "x" });
    const preset = (id: string, name: string, f: string, sort: string) => ({ id, name, category: "technical", description: "d", sort, descending: true, conditions: [{ field: f, op: "lt", value: 30 }] });
    await open({
      "GET /api/studies/options": { ...OPTIONS, strategies: [...OPTIONS.strategies, { id: "screener", params: [{ name: "max_positions", choices: [5, 10, 20], default: 10 }] }] },
      "GET /api/screener/meta": { fields: [field("rsi_14", "RSI (14)", "technical"), field("chg_6m", "Change, 6 months", "technical"), field("pe", "P/E", "fundamental"), field("segment", "Market-cap class", "profile")], presets: [preset("oversold", "Oversold", "rsi_14", "chg_6m"), preset("cheap", "Cheap", "pe", "pe"), preset("bigcap", "Big caps", "segment", "chg_6m")] },
      "POST /api/studies": { experiment_id: 8 },
    });
    fillIdea();
    fireEvent.click(screen.getByLabelText("A screener"));
    expect(screen.getByText(/Pick a screen to trade/)).toBeInTheDocument();
    const pick = await screen.findByLabelText("Start from a ready-made screen");
    await waitFor(() => expect(within(pick).getByText("Oversold")).toBeInTheDocument());
    expect(within(pick).getByText("Cheap")).toBeInTheDocument(); // filed results are backtestable
    expect(within(pick).queryByText("Big caps")).not.toBeInTheDocument(); // a study picks market-cap classes elsewhere
    fireEvent.change(pick, { target: { value: "oversold" } });
    expect(screen.getByText("RSI (14) < 30")).toBeInTheDocument();
    fireEvent.click(register());
    fireEvent.click(await screen.findByRole("button", { name: "Register and lock" }));
    await waitFor(() => expect(posted()).toHaveLength(1));
    expect(posted()[0]?.body).toMatchObject({ strategy_id: "screener", grid: { max_positions: [10] }, screen: { conditions: [{ field: "rsi_14", op: "lt", value: 30 }], match: "all", sort: "chg_6m", descending: true } });
  });

  it("opens preloaded from a saved screener: its screen, the caps it picks from and the stocks it holds", async () => {
    nav.search = new URLSearchParams({
      screen: JSON.stringify({ conditions: [{ field: "rsi_14", op: "lte", value: "40" }], match: "all", sort: "rsi_14", descending: false }),
      segments: "small,micro,bogus",
      slots: "20",
    }).toString();
    await open({
      "GET /api/studies/options": { ...OPTIONS, strategies: [...OPTIONS.strategies, { id: "screener", params: [{ name: "max_positions", choices: [5, 10, 20], default: 10 }] }] },
      "GET /api/screener/meta": { fields: [{ key: "rsi_14", label: "RSI (14)", group: "g", kind: "technical", unit: "x" }], presets: [] },
      "POST /api/studies": { experiment_id: 8 },
    });
    expect(screen.getByLabelText("A screener")).toBeChecked();
    fillIdea();
    fireEvent.click(register());
    fireEvent.click(await screen.findByRole("button", { name: "Register and lock" }));
    await waitFor(() => expect(posted()).toHaveLength(1));
    expect(posted()[0]?.body).toMatchObject({
      strategy_id: "screener",
      grid: { max_positions: [20] },
      universe: { segments: ["small", "micro"] }, // an unknown class is ignored
      screen: { conditions: [{ field: "rsi_14", op: "lte", value: "40" }], sort: "rsi_14" },
    });
  });

  describe("starting from a saved strategy", () => {
    const SCREENER = { config_id: "c9", name: "Dip buyer", strategy_id: "screener", universe: "segments", max_instruments: null, timeframe: "1D", params: { max_positions: 20 }, in_use: false, created_at: "2026-11-11T10:00:00+00:00", stage: "RESEARCH",
      screen: { screen: { conditions: [{ field: "rsi_14", op: "lte", value: "40" }], match: "all", sort: "rsi_14", descending: false }, segments: ["small"] } };
    const both = { ...SAVED, strategies: [...SAVED.strategies, SCREENER] };
    const withScreener = { ...OPTIONS, strategies: [...OPTIONS.strategies, { id: "screener", params: [{ name: "max_positions", choices: [5, 10, 20], default: 10 }] }] };
    const META = { fields: [{ key: "rsi_14", label: "RSI (14)", group: "g", kind: "technical", unit: "x" }], presets: [] };
    const ready = { "GET /api/studies/options": withScreener, "GET /api/strategies": both, "GET /api/screener/meta": META, "POST /api/studies": { experiment_id: 8 } };

    it("offers only trend strategies to a trend study, so a saved screener cannot be sent as one", async () => {
      await open(ready);
      const pick = await screen.findByLabelText("Start from a saved strategy");
      await waitFor(() => expect(within(pick).getByText("My paper strategy")).toBeInTheDocument());
      expect(within(pick).queryByText("Dip buyer")).not.toBeInTheDocument();
    });

    it("fills a screener study with the saved screen, its market-cap classes and its number of stocks, and registers it as a screener", async () => {
      await open(ready);
      fillIdea();
      fireEvent.click(screen.getByLabelText("A screener"));
      const pick = await screen.findByLabelText("Start from a saved strategy");
      await waitFor(() => expect(within(pick).getByText("Dip buyer")).toBeInTheDocument());
      expect(within(pick).queryByText("My paper strategy")).not.toBeInTheDocument();
      fireEvent.change(pick, { target: { value: "c9" } });
      expect(screen.getByLabelText("max_positions 20")).toBeChecked();
      fireEvent.click(register());
      fireEvent.click(await screen.findByRole("button", { name: "Register and lock" }));
      await waitFor(() => expect(posted()).toHaveLength(1));
      expect(posted()[0]?.body).toMatchObject({
        strategy_id: "screener", grid: { max_positions: [20] },
        screen: { conditions: [{ field: "rsi_14", op: "lte", value: "40" }], match: "all", sort: "rsi_14", descending: false },
        universe: { segments: ["small"] },
      });
    });
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
    fireEvent.change(screen.getByLabelText("Compare with (index)"), { target: { value: "Nifty 50 Total Return Index (gross)" } });
    fireEvent.change(screen.getByLabelText("Smallest order (₹)"), { target: { value: "5000" } });
    fireEvent.change(screen.getByLabelText("Largest order (₹)"), { target: { value: "100000" } });
    fireEvent.click(register());
    expect(posted()).toHaveLength(0); // not yet: the dialog asks first
    fireEvent.click(await screen.findByRole("button", { name: "Register and lock" }));
    await waitFor(() => expect(posted()).toHaveLength(1));
    const b = posted()[0]?.body as Record<string, unknown>;
    expect(b).toMatchObject({
      name: "My study", strategy_id: "trend_pullback", timeframe: "1D", start: "2019-10-01", end: "2026-11-11", capital: "1000000", capacity_multiple: "3",
      broker: "zerodha", product: "DELIVERY", accept_survivorship_bias: false,
      slippage: { base_bps: "8", participation_bps_per_pct: "5", volatility_fraction: "0" },
      min_order_value: "5000", max_order_value: "100000", benchmark: "Nifty 50 Total Return Index (gross)",
      grid: { trend_sma: [100, 200], entry_rsi: [20, 25], exit_rsi: [60], max_positions: [10] },
      universe: { segments: ["large", "mid", "small"], before_segment_lists: "traded_value_rank", min_history_sessions: 252 },
    });
    expect((b.thresholds as Record<string, string>).min_oos_sharpe).toBe("1.0");
    expect(b.holdout_start).toBe(holdoutFor("2019-10-01", "2026-11-11", 30));
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/research/studies/7"));
  });

  it("shows the order-size advice on the form as soon as the limits do not fit", async () => {
    await open();
    fireEvent.change(screen.getByLabelText("Largest order (₹)"), { target: { value: "15000" } });
    expect(await screen.findByText("Check the order sizes")).toBeInTheDocument();
    expect(screen.getByText(/takes about \d+ days/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Largest order (₹)"), { target: { value: "" } });
    expect(screen.queryByText("Check the order sizes")).not.toBeInTheDocument();
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
    expect(screen.getByText(/4 of 12 combinations done/)).toBeInTheDocument();
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
  it("orders the combinations by what matters, with failed ones last", async () => {
    const better = { ...TRIAL(2, 25, 2.5), metrics: { sharpe: 2.5, cagr: 0.2, max_drawdown: -0.3, trades: 10, costs: 1 } };
    const calmer = { ...TRIAL(3, 30, 0.4), metrics: { sharpe: 0.4, cagr: 0.05, max_drawdown: -0.02, trades: 10, costs: 1 } };
    open({ run: { ...RUN, status: "DONE", done: 12, current: null }, trials: [TRIAL(1, 20, 1.0), TRIAL(4, 35, null, "FAILED"), better, calmer], universe_coverage: [] });
    await screen.findByText("entry_rsi 25 · trend_sma 200");
    const order = () => screen.getAllByText(/entry_rsi \d+ · trend_sma/).map((e) => e.textContent?.slice(10, 12));
    expect(order()).toEqual(["20", "35", "25", "30"]); // as registered
    fireEvent.change(screen.getByLabelText("Order by"), { target: { value: "sharpe" } });
    expect(order()).toEqual(["25", "20", "30", "35"]);
    fireEvent.change(screen.getByLabelText("Order by"), { target: { value: "drawdown" } });
    expect(order()[0]).toBe("30"); // the smallest drop first
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

describe("the verdict", () => {
  const GATES = [
    { name: "oos_sharpe", passed: true, detail: "1.10 < required 0.8" },
    { name: "deflated_sharpe", passed: false, detail: "0.612 < required 0.95" },
    { name: "beats_benchmark", passed: false, detail: "evidence missing" },
  ];
  const REPORT = { report_id: 1, run_id: 5, passed: false, thresholds_status: "confirmed", n_trials: 12, created_at: "2026-11-12T08:00:00+00:00",
    evidence: { oos_sharpe: 1.1, dsr: 0.612, benchmark_sharpe: null, max_drawdown: -0.2, oos_days: 252 }, gates: GATES,
    refs: { chosen: { entry_rsi: 20, trend_sma: 200 }, benchmark: "Nifty 200 Total Return Index (gross)", benchmark_note: "has no passing validation for its stored data",
      windows: [{ train_from: "2020-01-02", train_to: "2021-12-31", test_from: "2022-01-10", test_to: "2022-07-01", chosen: { entry_rsi: 20 }, sharpe: 1.4, return: 0.081 }],
      walk_forward: { train: 504, test: 126, embargo: 5 }, cost_2x_run: 6, capital_run: 7, capital_multiple: "3" } };
  const RUNV = { ...RUN, run_id: 9, kind: "verdict", status: "DONE", done: 2, total: 2, current: null, finished_at: "2026-11-12T08:00:00+00:00" };
  const open = (verdict: unknown, perms = ["research:read", "strategy:own"], extra: Record<string, unknown> = {}) => {
    backend({ "GET /api/auth/me": who(perms), "GET /api/studies/7": STUDY, "GET /api/studies/7/results": NO_RUN, "GET /api/studies/7/verdict": verdict, ...extra });
    mount(<StudyPage />);
  };
  it("shows every check with the figure it judged, only explains the failures, and links the runs behind it", async () => {
    open({ holdout: null, holdout_run: null, run: RUNV, report: REPORT, trials_done: 12, trials_planned: 12 });
    expect(await screen.findByText("Failed 2 of 3 checks")).toBeInTheDocument();
    const sharpe = screen.getByText("Out-of-sample Sharpe").closest("tr") as HTMLElement;
    expect(within(sharpe).getByText("Pass")).toBeInTheDocument();
    expect(within(sharpe).getByText("1.10")).toBeInTheDocument();
    expect(within(sharpe).queryByText(/required/)).not.toBeInTheDocument(); // a pass is not explained as a failure
    const dsr = screen.getByText("Deflated Sharpe (allows for luck across all the tries)").closest("tr") as HTMLElement;
    expect(within(dsr).getByText("0.612")).toBeInTheDocument();
    expect(within(dsr).getByText("0.612 < required 0.95")).toBeInTheDocument();
    expect(screen.getByText("no evidence")).toBeInTheDocument();
    expect(screen.getByText(/has no passing validation/)).toBeInTheDocument();
    expect(screen.getByText(/Thresholds confirmed · 12 combinations tried/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open that run" })).toHaveAttribute("href", "/research/backtests/5");
    expect(screen.getByRole("link", { name: "double-cost run" })).toHaveAttribute("href", "/research/backtests/6");
    expect(screen.getByText("2022-01-10 to 2022-07-01")).toBeInTheDocument();
    expect(screen.getByText("8.1%")).toBeInTheDocument();
  });
  it("says passed when every check passed", async () => {
    open({ holdout: null, holdout_run: null, run: RUNV, report: { ...REPORT, passed: true, gates: GATES.slice(0, 1), refs: { ...REPORT.refs, benchmark_note: null } }, trials_done: 12, trials_planned: 12 });
    expect(await screen.findByText("Passed every check")).toBeInTheDocument();
  });
  it("cannot be started until every combination has run, and says how many have", async () => {
    open({ holdout: null, holdout_run: null, run: null, report: null, trials_done: 5, trials_planned: 12 });
    expect(await screen.findByText(/5 of 12 combinations have finished/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Judge the results" })).toBeDisabled();
  });
  it("queues the judging once the trials are done", async () => {
    open({ holdout: null, holdout_run: null, run: null, report: null, trials_done: 12, trials_planned: 12 }, undefined, { "POST /api/studies/7/verdicts": { run_id: 9 } });
    fireEvent.click(await screen.findByRole("button", { name: "Judge the results" }));
    await waitFor(() => expect(posted()[0]?.path).toBe("/api/studies/7/verdicts"));
    expect(await screen.findByText("Judging queued.")).toBeInTheDocument();
  });
  const HOLDOUT = { run_id: 11, passed: false, created_at: "2026-11-13T08:00:00+00:00", evidence: { days: 60, sharpe: 0.4, max_drawdown: -0.1, benchmark_sharpe: null, total_return: 0.03 },
    gates: [{ name: "holdout_sharpe", passed: false, detail: "0.40 < required 0.8" }, { name: "holdout_drawdown", passed: true, detail: "ok" }, { name: "holdout_beats_benchmark", passed: false, detail: "evidence missing" }],
    refs: { chosen: { entry_rsi: 20 }, benchmark: "Nifty 200 Total Return Index (gross)", benchmark_note: "not loaded", window: ["2024-05-01", "2026-11-06"], verdict_report: 1 } };
  const PASSED = { ...REPORT, passed: true, gates: GATES.slice(0, 1), refs: { ...REPORT.refs, benchmark_note: null } };
  it("opens the holdout only after asking, and only once the verdict passed", async () => {
    open({ holdout: null, holdout_run: null, run: RUNV, report: PASSED, trials_done: 12, trials_planned: 12 }, undefined, { "POST /api/studies/7/holdout": { run_id: 11 } });
    fireEvent.click(await screen.findByRole("button", { name: "Open the holdout" }));
    expect(posted()).toHaveLength(0); // it asks first: this can be done once
    fireEvent.click(screen.getByRole("button", { name: "Open it" }));
    await waitFor(() => expect(posted()[0]?.path).toBe("/api/studies/7/holdout"));
  });
  it("keeps the holdout closed, and says why, while the verdict has not passed", async () => {
    open({ holdout: null, holdout_run: null, run: RUNV, report: REPORT, trials_done: 12, trials_planned: 12 });
    expect(await screen.findByText(/stays unopened/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open the holdout" })).not.toBeInTheDocument();
  });
  it("shows the holdout result with each check and the figure it judged", async () => {
    open({ holdout: HOLDOUT, holdout_run: null, run: RUNV, report: PASSED, trials_done: 12, trials_planned: 12 });
    expect(await screen.findByText("Failed the holdout")).toBeInTheDocument();
    const row = screen.getByText("Sharpe on the holdout").closest("tr") as HTMLElement;
    expect(within(row).getByText("0.40")).toBeInTheDocument();
    expect(within(row).getByText("0.40 < required 0.8")).toBeInTheDocument();
    expect(screen.getByText("10.0%")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open the holdout" })).not.toBeInTheDocument(); // opened for good
    expect(screen.getByRole("link", { name: "open the run" })).toHaveAttribute("href", "/research/backtests/11");
  });
  it("shows progress while the holdout runs", async () => {
    open({ holdout: null, holdout_run: { ...RUNV, run_id: 12, kind: "holdout", status: "RUNNING", finished_at: null }, run: RUNV, report: PASSED, trials_done: 12, trials_planned: 12 });
    expect(await screen.findByText("Running the holdout")).toBeInTheDocument();
  });
  it("shows progress while judging and the reason when it stopped", async () => {
    open({ holdout: null, holdout_run: null, run: { ...RUNV, status: "RUNNING", current: "2x costs", finished_at: null }, report: null, trials_done: 12, trials_planned: 12 });
    expect(await screen.findByText("Judging")).toBeInTheDocument();
    expect(screen.getByText(/re-running at 2x costs/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Judge the results" })).not.toBeInTheDocument();
  });
  it("shows why judging stopped, and offers it only to someone who may run strategies", async () => {
    open({ holdout: null, holdout_run: null, run: { ...RUNV, status: "FAILED", error: "1000 sessions is too short for walk-forward: it needs at least 635" }, report: null, trials_done: 12, trials_planned: 12 }, ["research:read"]);
    expect(await screen.findByText("The judging stopped")).toBeInTheDocument();
    expect(screen.getByText(/too short for walk-forward/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Judge the results" })).not.toBeInTheDocument();
  });
});


describe("progress and time left", () => {
  const open = (results: unknown) => {
    backend({ "GET /api/auth/me": who(["research:read", "strategy:own"]), "GET /api/studies/7": STUDY, "GET /api/studies/7/results": results });
    mount(<StudyPage />);
  };
  const PROGRESS = { fraction: 0.375, elapsed_seconds: 2700, eta_seconds: 4500, step_done: 550, step_total: 1100 };
  it("shows the real percentage, the day inside the current combination, the time spent and an estimate of the time left", async () => {
    open({ run: { ...RUN, step_done: 550, step_total: 1100, progress: PROGRESS }, trials: [], universe_coverage: [] });
    expect(await screen.findByText("38%")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Progress" })).toHaveAttribute("aria-valuenow", "38");
    expect(screen.getByText(/day 550 of 1,100/)).toBeInTheDocument();
    expect(screen.getByText(/Running for 45 min/)).toBeInTheDocument();
    expect(screen.getByText("1 h 15 min")).toBeInTheDocument();
    expect(screen.getByText(/an estimate that sharpens as it goes/)).toBeInTheDocument();
  });
  it("says it is still working out the time left until it has enough to judge", async () => {
    open({ run: { ...RUN, done: 0, progress: { ...PROGRESS, fraction: 0.001, eta_seconds: null, step_done: 1, step_total: 1100, elapsed_seconds: 30 } }, trials: [], universe_coverage: [] });
    expect(await screen.findByText(/working out the time left/)).toBeInTheDocument();
  });
  it("tells you to start the worker when a job has waited a while and nothing has picked it up", async () => {
    const waiting = { ...RUN, status: "QUEUED", done: 0, total: 0, current: null, started_at: null, created_at: new Date(Date.now() - 5 * 60_000).toISOString() };
    open({ run: waiting, trials: [], universe_coverage: [] });
    expect(await screen.findByText("Waiting for the worker")).toBeInTheDocument();
    expect(screen.getByText(/start_all\.sh/)).toBeInTheDocument();
  });
  it("lets a running job be stopped after asking, and says it is stopping once asked", async () => {
    backend({ "GET /api/auth/me": who(["research:read", "strategy:own"]), "GET /api/studies/7": STUDY, "GET /api/studies/7/results": { run: RUN, trials: [], universe_coverage: [] }, "POST /api/studies/runs/3/cancel": { ok: true } });
    mount(<StudyPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
    expect(posted()).toHaveLength(0); // it asks first
    fireEvent.click(screen.getByRole("button", { name: "Stop it" }));
    await waitFor(() => expect(posted()[0]?.path).toBe("/api/studies/runs/3/cancel"));
  });
  it("shows Stopping while the stop is being carried out, with no second button", async () => {
    open({ run: { ...RUN, cancel_requested: true }, trials: [], universe_coverage: [] });
    expect(await screen.findByText("Stopping…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
  });
  it("does not offer Stop to someone who may not run strategies", async () => {
    backend({ "GET /api/auth/me": who(["research:read"]), "GET /api/studies/7": STUDY, "GET /api/studies/7/results": { run: RUN, trials: [], universe_coverage: [] } });
    mount(<StudyPage />);
    await screen.findByText(/4 of 12 combinations done/);
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
  });
  it("says nothing alarming about a job that has only just been queued", async () => {
    open({ run: { ...RUN, status: "QUEUED", done: 0, total: 0, current: null, started_at: null, created_at: new Date().toISOString() }, trials: [], universe_coverage: [] });
    expect(await screen.findByText("Waiting for a worker")).toBeInTheDocument();
    expect(screen.queryByText("Waiting for the worker")).not.toBeInTheDocument();
  });
  it("says how long a finished run took", async () => {
    open({ run: { ...RUN, status: "DONE", done: 12, current: null, started_at: "2026-11-12T06:00:00+00:00", finished_at: "2026-11-12T09:12:00+00:00" }, trials: [], universe_coverage: [] });
    expect(await screen.findByText("Took 3 h 12 min.")).toBeInTheDocument();
  });
});
