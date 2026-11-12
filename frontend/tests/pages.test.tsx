import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import BacktestsPage from "@/app/research/backtests/page";
import DashboardPage from "@/app/dashboard/page";
import { createSeriesMarkers } from "lightweight-charts";
import { AuthProvider } from "@/lib/auth";
import InstrumentsPage from "@/app/data/instruments/page";
import SystemPage from "@/app/system/page";
import { benchmarkDetail, dashboard, route } from "./fixtures";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
  usePathname: () => "/dashboard",
}));
vi.mock("lightweight-charts", () => {
  const series = () => ({ setData: vi.fn(), createPriceLine: vi.fn(() => ({})), removePriceLine: vi.fn(), coordinateToPrice: vi.fn(() => 100), priceToCoordinate: vi.fn(() => 50) });
  return {
    ColorType: { Solid: "solid" },
    CrosshairMode: { Normal: 0 },
    LineStyle: { Dashed: 2 },
    PriceScaleMode: { Normal: 0, Logarithmic: 1 },
    CandlestickSeries: "Candlestick",
    LineSeries: "Line",
    AreaSeries: "Area",
    HistogramSeries: "Histogram",
    createSeriesMarkers: vi.fn(),
    createChart: () => ({
      addSeries: series,
      removeSeries: vi.fn(),
      panes: () => [{ getHeight: () => 400, setHeight: vi.fn(), getHTMLElement: () => document.createElement("div") }],
      takeScreenshot: vi.fn(),
      priceScale: () => ({ applyOptions: vi.fn() }),
      timeScale: () => ({ fitContent: vi.fn(), subscribeVisibleLogicalRangeChange: vi.fn(), unsubscribeVisibleLogicalRangeChange: vi.fn(), timeToCoordinate: vi.fn(() => 10), width: vi.fn(() => 800), height: vi.fn(() => 28), coordinateToLogical: vi.fn(() => 0) }),
      applyOptions: vi.fn(),
      subscribeCrosshairMove: vi.fn(),
      unsubscribeCrosshairMove: vi.fn(),
      subscribeClick: vi.fn(),
      unsubscribeClick: vi.fn(),
      remove: vi.fn(),
    }),
  };
});

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState({}, "", "/");
});

describe("Dashboard", () => {
  it("shows ingested, validated, eligible and gate states separately for each series", async () => {
    vi.stubGlobal("fetch", route({ "/api/dashboard": dashboard }));
    wrap(<DashboardPage />);
    const net = (await screen.findByText("Nifty 50 Net Total Return Index")).closest("tr") as HTMLElement;
    expect(within(net).getByText("no (see findings)")).toBeInTheDocument(); // not technically validated
    expect(within(net).getAllByText("eligible").length).toBe(1); // daily research only
    expect(within(net).getByText("not eligible")).toBeInTheDocument(); // gate
    expect(within(net).getByText("blocked")).toBeInTheDocument(); // intraday
    expect(screen.getByText(/Benchmark gate: disabled/)).toBeInTheDocument();
    expect(screen.getByText("not persisted yet")).toBeInTheDocument();
    expect(screen.getByText("unknown", { selector: "[data-state=UNKNOWN]" })).toBeInTheDocument();
    expect(screen.getByText("redis not configured")).toBeInTheDocument();
    const fresh = screen.getByTestId("freshness");
    expect(fresh).toHaveTextContent("data current");
    expect(fresh).toHaveTextContent("Fri, 6 Nov 2026"); // the latest session, not a day-count
    expect(fresh).toHaveTextContent("Mon, 9 Nov 2026");
    expect(screen.getByTestId("pending-review")).toHaveTextContent("529");
    expect(screen.getByTestId("provisional")).toHaveTextContent("10");
    expect(screen.getByText("quarantined: 0")).toBeInTheDocument();
  });

  it("says plainly when the API cannot be reached", async () => {
    vi.stubGlobal("fetch", route({}));
    wrap(<DashboardPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the dashboard");
  });
});

describe("Benchmark detail", () => {
  it("does not let an unresolved benchmark read as fully validated", async () => {
    window.history.pushState({}, "", "/data/benchmarks?id=3");
    vi.stubGlobal("fetch", route({ "/api/benchmarks/3": benchmarkDetail, "/api/benchmarks/3/levels": { levels: [{ date: "2000-01-03", level: "1688.44" }, { date: "2026-11-06", level: "33034.81" }], total_observations: 6676, returned: 2, downsampled: true, method: "min-max per bucket (extremes preserved)" } }));
    const { default: BenchmarksPage } = await import("@/app/data/benchmarks/page");
    wrap(<BenchmarksPage />);
    expect(await screen.findByText(/1 unresolved finding apply/)).toBeInTheDocument();
    expect(screen.getByText("Active findings (1)")).toBeInTheDocument();
    expect(screen.getByText("Resolved findings (1)")).toBeInTheDocument();
    expect(screen.getByText("technical not passed")).toBeInTheDocument();
    expect(screen.getByText("U02")).toBeInTheDocument();
    expect(screen.getAllByText(/Historical session hours are not verified/).length).toBeGreaterThan(0); // blocker and finding
    expect(screen.getByText(/no historical session hours are held as evidence/)).toBeInTheDocument();
    expect(screen.getByText("gate disabled")).toBeInTheDocument();
    // per-series dependencies, not just the all-series totals
    expect(screen.getByText("weekday by calendar rule only; no exchange evidence")).toBeInTheDocument();
    expect(screen.getByText("no value; exchange files either side chain over the day")).toBeInTheDocument();
    expect(screen.getByText(/All four series together/)).toBeInTheDocument();
    // existence, kind and hours are separate facts and the UI never calls a session "special"
    const props = screen.getByText(/listed special sessions: what is established/).parentElement as HTMLElement;
    expect(within(props).getByText("Session existence").closest("tr")).toHaveTextContent("confirmed");
    expect(within(props).getByText("Session kind").closest("tr")).toHaveTextContent("unconfirmed: 32");
    expect(within(props).getByText("Opening time").closest("tr")).toHaveTextContent("unknown: 32");
    expect(within(props).getByText("Closing time").closest("tr")).toHaveTextContent("unknown: 32");
    expect(screen.queryByText(/confirmed special/i)).not.toBeInTheDocument();
    // chart controls and the down-sampling disclosure
    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByTestId("sampling-note")).toHaveTextContent("Showing 2 of 6,676 observations: down-sampled, every peak and trough kept");
    expect(await screen.findByTestId("level-legend")).toHaveTextContent("2026-11-06 level 33034.81");
    expect(screen.getByText("legacy report format")).toBeInTheDocument();
  });
});

describe("Backtest Explorer", () => {
  it("keeps every run control disabled instead of faking a run", async () => {
    vi.stubGlobal("fetch", route({ "/api/backtests": { items: [], total: 0, limit: 50, offset: 0 } }));
    wrap(<BacktestsPage />);
    expect(await screen.findByText("No backtests have been stored yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run backtest" })).toBeDisabled();
    for (const label of ["Strategy", "Cost schedule", "Initial capital"]) expect(screen.getByLabelText(label)).toBeDisabled();
  });
});

describe("System Activity", () => {
  const row = (id: number, status: string, superseded: boolean, current: string) => ({ id, source: "nse", dataset: "bhav", partition: `2022-08-0${id}`, status, at: "2026-11-07T10:00:00+00:00", current_status: current, superseded });
  const activity = (offset: number, items: ReturnType<typeof row>[]) => ({
    ingestion: { items, total: 30, limit: 25, offset },
    validations: [{ benchmark_id: 1, name: "Nifty 200 TRI", latest: null }],
    backtests: [],
    jobs: { persisted: false, note: "job runtime and resource use are not recorded" },
  });

  it("shows a resolved quarantine as superseded history and a live one as a problem", async () => {
    vi.stubGlobal("fetch", route({ "/api/system/activity": activity(0, [row(3, "quarantined", false, "quarantined"), row(2, "quarantined", true, "loaded"), row(1, "loaded", false, "loaded")]) }));
    wrap(<SystemPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("1 partition(s) on this page are currently quarantined: 2022-08-03");
    expect(screen.getByText("superseded: partition is now loaded")).toBeInTheDocument();
    expect(screen.getByText("Nifty 200 TRI")).toBeInTheDocument();
    expect(screen.getByText("never validated")).toBeInTheDocument();
    expect(screen.getByText("job runtime and resource use are not recorded")).toBeInTheDocument();
    expect(screen.getByText("1-3 of 30 events")).toBeInTheDocument();
  });

  it("pages through the log", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(String(input));
      calls.push(url.searchParams.get("offset") ?? "");
      return new Response(JSON.stringify(activity(Number(url.searchParams.get("offset")), [row(1, "loaded", false, "loaded")])));
    });
    wrap(<SystemPage />);
    expect(await screen.findByRole("button", { name: "Newer" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Older" }));
    await waitFor(() => expect(calls).toContain("25"));
    expect(await screen.findByText("26-26 of 30 events")).toBeInTheDocument();
  });
});

describe("Data Explorer", () => {
  const inst = { id: 7, symbol: "XYZ", isin: "INE000A01010", name: "Xyz Ltd", status: "active", listed_on: null, delisted_on: null };
  const detail = { ...inst, bars: { first: "2024-01-01", last: "2024-12-31", count: 250 }, actions: [{ ex_date: "2024-06-12", kind: "bonus", status: "review", num: "1", den: "1", amount: null, subject: "Bonus 1:1" }] };
  const bars = {
    adjust: "none",
    timeframe: "1d",
    adjustment_version: "a7ca8ba234cb8b8a",
    clean: false,
    bars: [{ date: "2024-06-11", open: "100", high: "101", low: "99", close: "100.5", volume: "1000", factor: "1" }],
    unapplied: [{ kind: "demerger", ex_date: "2024-07-01" }],
    provisional: [],
  };

  it("labels the price basis, shows the adjustment version and surfaces data-quality warnings", async () => {
    vi.stubGlobal("fetch", route({ "/api/instruments": [inst], "/api/instruments/7": detail, "/api/instruments/7/bars": bars }));
    wrap(<AuthProvider><InstrumentsPage /></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "xy" } });
    fireEvent.click(await screen.findByRole("button", { name: /XYZ/ }));
    expect(await screen.findByText("basis: Raw (as traded)")).toBeInTheDocument();
    expect(screen.getByText("adjustment version a7ca8ba234cb8b8a")).toBeInTheDocument();
    expect(screen.getByText("data-quality warnings")).toBeInTheDocument();
    expect(screen.getByTestId("ohlc-legend")).toHaveTextContent("C 100.5");
    expect(screen.getByTestId("ohlc-legend")).toHaveTextContent("factor 1");
    expect(screen.getByText("1:1 (shares after : before)")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("demerger 2024-07-01");
    expect(screen.getByTestId("price-chart")).toBeInTheDocument();
    // the rail: tools by group with flyouts, undo/redo in the top bar, and a strategy loader that is honestly disabled
    expect(screen.getByRole("button", { name: "Cursor" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Lines tools" }));
    const menu = within(screen.getByRole("menu", { name: "Lines" }));
    for (const tool of ["Trend line", "Ray", "Extended line", "Horizontal line", "Horizontal ray", "Vertical line", "Cross line", "Arrow"]) expect(menu.getByRole("menuitem", { name: new RegExp(tool) })).toBeInTheDocument();
    expect(menu.getByRole("menuitem", { name: /Trend line/ })).toHaveTextContent("Alt+T");
    fireEvent.click(menu.getByRole("menuitem", { name: /^Trend line/ }));
    expect(screen.getByTestId("tool-hint")).toHaveTextContent("Trend line: click two points");
    for (const group of ["Channels", "Shapes", "Fibonacci", "Measure", "Forecast", "Annotation"]) expect(screen.getByRole("button", { name: `${group} tools` })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Magnet" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Undo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Redo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Objects \(0\)/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Screenshot" })).toBeEnabled();
    expect(screen.getByRole("group", { name: "Chart type" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "1Y" })).toBeInTheDocument();
    expect(screen.getByLabelText("Strategy")).toBeDisabled(); // no saved strategy to choose
    expect(screen.getByText("Bonus 1:1")).toBeInTheDocument();
    expect(screen.getByText("review")).toBeInTheDocument(); // an unverified action is not shown as verified
    fireEvent.change(screen.getByLabelText("Price basis"), { target: { value: "split" } });
    await waitFor(() => expect(screen.getAllByText("Split/bonus adjusted").length).toBeGreaterThan(0));
  });

  it("closes the suggestion list once an instrument is chosen and reopens it when typing again", async () => {
    vi.stubGlobal("fetch", route({ "/api/instruments": [inst], "/api/instruments/7": detail, "/api/instruments/7/bars": bars }));
    wrap(<AuthProvider><InstrumentsPage /></AuthProvider>);
    const box = screen.getByLabelText("Symbol, ISIN or name");
    fireEvent.change(box, { target: { value: "xy" } });
    fireEvent.click(await screen.findByRole("button", { name: /XYZ/ }));
    await screen.findByText("basis: Raw (as traded)");
    expect(screen.queryByRole("list", { name: "Matches" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Symbol, ISIN or name")).not.toBeInTheDocument(); // the popover closed
    fireEvent.click(screen.getByRole("button", { name: /XYZ/ })); // the chosen symbol is now the toolbar's button
    fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "XY" } });
    expect(await screen.findByRole("list", { name: "Matches" })).toBeInTheDocument();
  });

  it("offers intraday timeframes: asks the API for them, narrows the ranges and turns indicators off", async () => {
    const urls: string[] = [];
    const respond = route({ "/api/instruments": [inst], "/api/instruments/7": detail, "/api/instruments/7/bars": bars });
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      urls.push(String(input));
      return respond(input);
    });
    wrap(<AuthProvider><InstrumentsPage /></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "xy" } });
    fireEvent.click(await screen.findByRole("button", { name: /XYZ/ }));
    await screen.findByText("basis: Raw (as traded)");
    fireEvent.click(screen.getByRole("button", { name: "Timeframe: 1D" }));
    const menu = within(screen.getByRole("menu", { name: "Timeframes" }));
    expect(screen.getAllByRole("group").map((g) => g.getAttribute("aria-label"))).toEqual(expect.arrayContaining(["MINUTES", "HOURS", "DAYS"]));
    expect(menu.getAllByRole("menuitemradio").map((b) => b.textContent?.replace("✓", ""))).toEqual([
      "1 minute", "3 minutes", "5 minutes", "10 minutes", "15 minutes", "30 minutes", "45 minutes", "1 hour", "2 hours", "3 hours", "4 hours", "1 day", "1 week", "1 month",
    ]);
    expect(menu.getByRole("menuitemradio", { name: /1 day/ })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(menu.getByRole("menuitemradio", { name: "5 minutes" }));
    expect(screen.queryByRole("menu", { name: "Timeframes" })).not.toBeInTheDocument(); // closes on pick
    await waitFor(() => expect(urls.some((u) => u.includes("timeframe=5m") && u.includes("start=2024-12-01") && u.includes("end=2024-12-31"))).toBe(true));
    expect(screen.getByRole("button", { name: "Indicators" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Timeframe: 5m" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "2Y" })).not.toBeInTheDocument(); // 5m is served up to 124 days
    expect(screen.getByRole("button", { name: "3M" })).toBeInTheDocument();
  });

  it("explains an empty search instead of showing nothing", async () => {
    vi.stubGlobal("fetch", route({ "/api/instruments": [] }));
    wrap(<AuthProvider><InstrumentsPage /></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "zzz" } });
    expect(await screen.findByText("No instrument matches.")).toBeInTheDocument();
  });

  describe("strategy on the chart", () => {
    const params = { trend_sma: 200, entry_rsi: 30, exit_rsi: 60, max_positions: 10 };
    const saved = (id: string, name: string) => ({ config_id: id, name, strategy_id: "trend_pullback", universe: "nifty200", max_instruments: null, timeframe: "1D", params, in_use: false, created_at: "2026-11-11T10:00:00+00:00" });
    const me = { user: { id: "u1", email: "j@example.com", name: "Jane", role: "TRADER", permissions: ["strategy:own"], mfa_enabled: true, enrolment_required: false, must_change_password: false } };
    const day = (d: string, over: Record<string, unknown> = {}) => ({ day: d, close: "100", sma: "90", rsi: "20", ready: true, action: null, reason: null, holding_after: false, fill_day: null, fill_price: null, ...over });
    const signals = {
      label: "UNVALIDATED",
      strategy: "Cautious",
      params,
      notes: [],
      summary: { buys: 1, sells: 1 },
      days: [day("2024-06-10", { action: "BUY", reason: "oversold in an uptrend" }), day("2024-06-11", { action: "SELL", reason: "rsi_above_exit" })],
    };
    const table = {
      "/api/auth/me": me,
      "/api/instruments": [inst],
      "/api/instruments/7": detail,
      "/api/instruments/7/bars": bars,
      "/api/strategies": { label: "UNVALIDATED", options: { universes: [], timeframes: [], params: { trend_sma: [], entry_rsi: [], exit_rsi: [], max_positions: [] } }, strategies: [saved("c1", "Cautious"), saved("c2", "Bolder")] },
      "/api/strategies/c1/signals": signals,
    };
    const open = async (urls: string[] = []) => {
      const respond = route(table);
      vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
        urls.push(String(input));
        return respond(input);
      });
      wrap(<AuthProvider><InstrumentsPage /></AuthProvider>);
      fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "xy" } });
      fireEvent.click(await screen.findByRole("button", { name: /XYZ/ }));
      await screen.findByText("basis: Raw (as traded)");
    };

    it("lists the saved strategies in the toolbar and draws nothing until one is chosen", async () => {
      await open();
      const pick = await screen.findByLabelText("Strategy");
      await waitFor(() => expect(within(pick).getAllByRole("option").map((o) => o.textContent)).toEqual(["No strategy", "Cautious", "Bolder"]));
      expect(pick).toBeEnabled();
      expect(screen.queryByTestId("strategy-status")).not.toBeInTheDocument();
    });

    it("runs the chosen strategy over the chart's range and draws its buy and sell signals on the chart", async () => {
      const urls: string[] = [];
      await open(urls);
      const pick = await screen.findByLabelText("Strategy");
      await waitFor(() => expect(within(pick).getAllByRole("option")).toHaveLength(3));
      vi.mocked(createSeriesMarkers).mockClear();
      fireEvent.change(pick, { target: { value: "c1" } });
      await waitFor(() => expect(screen.getByTestId("strategy-status")).toHaveTextContent("1 buy, 1 sell"));
      const asked = urls.find((u) => u.includes("/api/strategies/c1/signals")) ?? "";
      expect(asked).toContain("instrument_id=7");
      expect(asked).toContain("start=2024-01-01");
      expect(asked).toContain("end=2024-12-31");
      expect(asked).toContain("holding=false");
      await waitFor(() => {
        const drawn = vi.mocked(createSeriesMarkers).mock.calls.at(-1)?.[1] as { text: string; position: string; time: string }[];
        expect(drawn.filter((m) => m.text === "BUY" || m.text === "SELL").map((m) => [m.text, m.position])).toEqual([["BUY", "belowBar"], ["SELL", "aboveBar"]]);
      });
      fireEvent.change(pick, { target: { value: "" } }); // choosing none takes them off again
      await waitFor(() => expect(screen.queryByTestId("strategy-status")).not.toBeInTheDocument());
      await waitFor(() => expect((vi.mocked(createSeriesMarkers).mock.calls.at(-1)?.[1] as { text: string }[]).some((m) => m.text === "BUY")).toBe(false));
    });

    it("is switched off on timeframes other than daily, because the decisions are daily", async () => {
      await open();
      const pick = await screen.findByLabelText("Strategy");
      await waitFor(() => expect(pick).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: "Timeframe: 1D" }));
      fireEvent.click(within(screen.getByRole("menu", { name: "Timeframes" })).getByRole("menuitemradio", { name: "5 minutes" }));
      await waitFor(() => expect(screen.getByLabelText("Strategy")).toBeDisabled());
    });

    it("says so when the strategy cannot be run", async () => {
      table["/api/strategies/c1/signals"] = undefined as unknown as typeof signals;
      await open();
      const pick = await screen.findByLabelText("Strategy");
      await waitFor(() => expect(within(pick).getAllByRole("option")).toHaveLength(3));
      fireEvent.change(pick, { target: { value: "c1" } });
      await waitFor(() => expect(screen.getByTestId("strategy-status")).toHaveTextContent("Could not run"));
      table["/api/strategies/c1/signals"] = signals;
    });
  });
});
