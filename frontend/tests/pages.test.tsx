import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import BacktestsPage from "@/app/research/backtests/page";
import DashboardPage from "@/app/dashboard/page";
import { createSeriesMarkers } from "lightweight-charts";
import { AuthProvider } from "@/lib/auth";
import InstrumentsPage from "@/app/data/instruments/page";
import { shiftDays, todayIST } from "@/lib/timeframes";
import SystemPage from "@/app/system/page";
import { benchmarkDetail, dashboard, route } from "./fixtures";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
  usePathname: () => "/dashboard",
}));
const scale = vi.hoisted(() => ({ range: { from: 0, to: 100 } as { from: number; to: number } | null, set: vi.fn(), fit: vi.fn(), update: vi.fn() }));
vi.mock("lightweight-charts", () => {
  const series = () => ({ setData: vi.fn(), update: scale.update, createPriceLine: vi.fn(() => ({})), removePriceLine: vi.fn(), coordinateToPrice: vi.fn(() => 100), priceToCoordinate: vi.fn(() => 50) });
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
      timeScale: () => ({ fitContent: scale.fit, getVisibleLogicalRange: () => scale.range, setVisibleLogicalRange: scale.set, getVisibleRange: () => null, setVisibleRange: vi.fn(), subscribeVisibleLogicalRangeChange: vi.fn(), unsubscribeVisibleLogicalRangeChange: vi.fn(), timeToCoordinate: vi.fn(() => 10), width: vi.fn(() => 800), height: vi.fn(() => 28), coordinateToLogical: vi.fn(() => 0) }),
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
    const platform = (screen.getByText("Platform status").closest("section") as HTMLElement);
    expect(within(platform).getByText("attention")).toBeInTheDocument();
    expect(within(platform).getByText(/No Kite data feed is connected/)).toBeInTheDocument();
    expect(within(platform).getByText(/11 scheduled jobs have never run/)).toBeInTheDocument();
    expect(screen.getByText("redis not configured")).toBeInTheDocument();
    const fresh = screen.getByTestId("freshness");
    expect(fresh).toHaveTextContent("data current");
    expect(fresh).toHaveTextContent("Fri, 6 Nov 2026"); // the latest session, not a day-count
    expect(fresh).toHaveTextContent("Mon, 9 Nov 2026");
    expect(screen.getByTestId("pending-review")).toHaveTextContent("529");
    expect(screen.getByTestId("provisional")).toHaveTextContent("10");
    expect(screen.getByText("quarantined: 0")).toBeInTheDocument();
    expect(screen.getByText("holiday / no file: 100")).toBeInTheDocument(); // days the exchange published nothing
    const syncs = screen.getByRole("table", { name: "Scheduled syncs" });
    const ok = within(syncs).getByText("bhavcopy-daily").closest("tr") as HTMLElement;
    expect(within(ok).getByText("ok")).toBeInTheDocument();
    expect(within(ok).getByText("Mon..Fri 18:30 IST")).toBeInTheDocument();
    expect(within(ok).getAllByText(/18:15 IST/).length).toBeGreaterThan(0); // 12:45 UTC, in exchange time
    const bad = within(syncs).getByText("kite-reconcile").closest("tr") as HTMLElement;
    expect(within(bad).getByText("failed")).toBeInTheDocument();
    expect(within(bad).getByText(/reconcile_kite_prices.py exited 3/)).toBeInTheDocument();
    expect(within(bad).getByText(/12 Nov.*20:01 IST/)).toBeInTheDocument(); // the last success (the day before), kept apart from the failed last run
    const never = within(syncs).getByText("fundamentals-daily").closest("tr") as HTMLElement;
    expect(within(never).getByText("never run")).toBeInTheDocument();
    expect(screen.queryByText(/not published/)).not.toBeInTheDocument();
  });

  it("says everything is fine when there is nothing to report, and DOWN loudly when the data is gone", async () => {
    vi.stubGlobal("fetch", route({ "/api/dashboard": { ...dashboard, platform: { status: "OK", reasons: [] } } }));
    const { unmount } = wrap(<DashboardPage />);
    const ok = within((await screen.findByText("Platform status")).closest("section") as HTMLElement);
    expect(ok.getByText("ok")).toBeInTheDocument();
    expect(ok.getByText("Everything is current and every scheduled job is on time.")).toBeInTheDocument();
    unmount();
    vi.stubGlobal("fetch", route({ "/api/dashboard": { ...dashboard, platform: { status: "DOWN", reasons: [{ level: "down", text: "No price data is loaded yet." }] } } }));
    wrap(<DashboardPage />);
    const down = within((await screen.findByText("Platform status")).closest("section") as HTMLElement);
    expect(down.getByText("down")).toBeInTheDocument();
    expect(down.getByText("No price data is loaded yet.")).toBeInTheDocument();
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

describe("Backtests", () => {
  const run = (id: number, metrics: Record<string, unknown>) => ({ run_id: id, strategy_id: "trend_pullback", strategy_version: "1", reader_mode: "research", created_at: "2026-11-12T06:00:00+00:00", metrics, accounting_complete: true, ledger_reconciled: true, result_hash: "abc", label: null, study: null });
  it("says so when there are no runs, and does not offer a run it cannot make", async () => {
    vi.stubGlobal("fetch", route({ "/api/backtests": { items: [], total: 0, limit: 50, offset: 0 } }));
    wrap(<BacktestsPage />);
    expect(await screen.findByText("No runs yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run backtest/i })).not.toBeInTheDocument();
  });
  it("names the study a run belongs to and labels the verdict's stress runs so they are not mistaken for trials", async () => {
    vi.stubGlobal("fetch", route({ "/api/backtests": { items: [{ ...run(5, {}), label: "verdict: 2x costs", study: { experiment_id: 7, name: "My study" } }], total: 1, limit: 50, offset: 0 } }));
    wrap(<BacktestsPage />);
    expect(await screen.findByText("verdict: 2x costs")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "My study" })).toHaveAttribute("href", "/research/studies/7");
  });
  it("lists each run with its return and a link to the full report", async () => {
    vi.stubGlobal("fetch", route({ "/api/backtests": { items: [run(2, { total_return: 1.1553, cagr: 0.14, max_drawdown: -0.27 }), run(3, { total_return: -0.05 })], total: 2, limit: 50, offset: 0 } }));
    wrap(<BacktestsPage />);
    const link = await screen.findByRole("link", { name: "#2 · view report" });
    expect(link).toHaveAttribute("href", "/research/backtests/2");
    const row = link.closest("tr") as HTMLElement;
    expect(within(row).getByText("115.5%")).toBeInTheDocument();
    expect(within(row).getByText("-27.0%")).toBeInTheDocument();
    expect(within(screen.getByRole("link", { name: "#3 · view report" }).closest("tr") as HTMLElement).getByText("-5.0%")).toBeInTheDocument();
  });
});

describe("System Activity", () => {
  const row = (id: number, status: string) => ({ id, source: "nse", dataset: "bhav", partition: `2022-08-0${id}`, status, at: "2026-11-07T10:00:00+00:00" });
  const activity = (offset: number, items: ReturnType<typeof row>[]) => ({
    ingestion: { items, total: 30, limit: 25, offset },
    validations: [{ benchmark_id: 1, name: "Nifty 200 TRI", latest: null }],
    backtests: [],
    jobs: { persisted: false, note: "job runtime and resource use are not recorded" },
  });

  it("calls a day the exchange published no file a holiday / no file, not an alarming status", async () => {
    vi.stubGlobal("fetch", route({ "/api/system/activity": activity(0, [row(1, "not_published")]) }));
    wrap(<SystemPage />);
    expect(await screen.findByText("holiday / no file")).toBeInTheDocument();
    expect(screen.queryByText("not published")).not.toBeInTheDocument();
  });

  it("flags a quarantined partition as a problem and lists each date only once", async () => {
    vi.stubGlobal("fetch", route({ "/api/system/activity": activity(0, [row(3, "quarantined"), row(1, "loaded")]) }));
    wrap(<SystemPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("1 partition(s) on this page are currently quarantined: 2022-08-03");
    expect(screen.queryByText(/superseded/)).not.toBeInTheDocument();
    expect(screen.getByText("Nifty 200 TRI")).toBeInTheDocument();
    expect(screen.getByText("never validated")).toBeInTheDocument();
    expect(screen.getByText("job runtime and resource use are not recorded")).toBeInTheDocument();
    expect(screen.getByText("1-2 of 30 events")).toBeInTheDocument();
  });

  it("pages through the log", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
      const url = new URL(String(input));
      calls.push(url.searchParams.get("offset") ?? "");
      return new Response(JSON.stringify(activity(Number(url.searchParams.get("offset")), [row(1, "loaded")])));
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
  const detail = { ...inst, bars: { first: "2024-01-01", last: "2024-12-31", count: 250 }, actions: [{ ex_date: "2024-06-12", kind: "bonus", status: "review", num: "1", den: "1", amount: null, subject: "Bonus 1:1" }], upcoming: [] as { ex_date: string; kind: string; status: string; num: string | null; den: string | null; amount: string | null; subject: string | null }[] };
  const bars = {
    adjust: "none",
    timeframe: "1d",
    adjustment_version: "a7ca8ba234cb8b8a",
    source: "nse",
    clean: false,
    bars: [{ date: "2024-06-11", open: "100", high: "101", low: "99", close: "100.5", volume: "1000", factor: "1" }],
    unapplied: [{ kind: "demerger", ex_date: "2024-07-01" }],
    provisional: [],
  };

  it("shows announced future actions in their own card, apart from the history, and nothing when none are announced", async () => {
    const soon = { ex_date: "2026-11-24", kind: "dividend", status: "ok", num: null, den: null, amount: "7", subject: "Interim Dividend - Rs 7 Per Share" };
    const withUpcoming = { ...detail, upcoming: [soon] };
    const routes = (d: unknown) => route({ "/api/instruments": [inst], "/api/instruments/7": d, "/api/instruments/7/bars": bars, "/api/instruments/7/fundamentals": { instrument_id: 7, symbol: "XYZ", bases: [], basis: null, periods: [] } });
    vi.stubGlobal("fetch", routes(withUpcoming));
    const { unmount } = wrap(<AuthProvider><InstrumentsPage /></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "xy" } });
    fireEvent.click(await screen.findByRole("button", { name: /XYZ/ }));
    const card = (await screen.findByText("Coming up")).closest("section") as HTMLElement;
    expect(within(card).getByText("2026-11-24")).toBeInTheDocument();
    expect(within(card).getByText(/not applied to prices until the ex-date/)).toBeInTheDocument();
    const history = screen.getByTestId("actions-scroll");
    expect(within(history).queryByText("2026-11-24")).not.toBeInTheDocument(); // it is not history yet
    unmount();
    vi.stubGlobal("fetch", routes(detail));
    wrap(<AuthProvider><InstrumentsPage /></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "xy" } });
    fireEvent.click(await screen.findByRole("button", { name: /XYZ/ }));
    await screen.findByTestId("actions-scroll");
    expect(screen.queryByText("Coming up")).not.toBeInTheDocument();
  });

  it("lists corporate actions newest first in a list whose scrollbar is always visible", async () => {
    const action = (ex_date: string, kind: string) => ({ ex_date, kind, status: "ok", num: null, den: null, amount: "5", subject: `${kind} ${ex_date}` });
    const long = { ...detail, actions: [action("2005-07-11", "dividend"), action("2015-03-02", "dividend"), action("2026-10-14", "dividend")] }; // the API sends oldest first
    vi.stubGlobal("fetch", route({ "/api/instruments": [inst], "/api/instruments/7": long, "/api/instruments/7/bars": bars, "/api/instruments/7/fundamentals": { instrument_id: 7, symbol: "XYZ", bases: [], basis: null, periods: [] } }));
    wrap(<AuthProvider><InstrumentsPage /></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "xy" } });
    fireEvent.click(await screen.findByRole("button", { name: /XYZ/ }));
    const area = await screen.findByTestId("actions-scroll");
    const dates = within(area).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[0]?.textContent);
    expect(dates).toEqual(["2026-10-14", "2015-03-02", "2005-07-11"]);
    expect(area).toHaveClass("overflow-y-auto"); // it scrolls, so the user must be able to see that
    expect(area.className).not.toMatch(/scrollbar-width:none|webkit-scrollbar/); // nothing hides the scrollbar
    expect(area).toHaveAttribute("tabindex", "0"); // and the keyboard can scroll it
    expect(screen.getByText("3 actions, newest first.")).toBeInTheDocument();
  });

  it("labels the price basis, shows the adjustment version and surfaces data-quality warnings", async () => {
    vi.stubGlobal("fetch", route({ "/api/instruments": [inst], "/api/instruments/7": detail, "/api/instruments/7/bars": bars, "/api/instruments/7/fundamentals": { instrument_id: 7, symbol: "XYZ", bases: [], basis: null, periods: [] } }));
    wrap(<AuthProvider><InstrumentsPage /></AuthProvider>);
    fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "xy" } });
    fireEvent.click(await screen.findByRole("button", { name: /XYZ/ }));
    expect(await screen.findByText("basis: Raw (as traded)")).toBeInTheDocument();
    expect(screen.getByText("prices: NSE bhavcopy")).toBeInTheDocument();
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
    vi.stubGlobal("fetch", route({ "/api/instruments": [inst], "/api/instruments/7": detail, "/api/instruments/7/bars": bars, "/api/instruments/7/fundamentals": { instrument_id: 7, symbol: "XYZ", bases: [], basis: null, periods: [] } }));
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
    const respond = route({ "/api/instruments": [inst], "/api/instruments/7": detail, "/api/instruments/7/bars": bars, "/api/instruments/7/fundamentals": { instrument_id: 7, symbol: "XYZ", bases: [], basis: null, periods: [] } });
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
    const end = todayIST(); // intraday ranges reach today: today's minutes come from the live feed
    await waitFor(() => expect(urls.some((u) => u.includes("timeframe=5m") && u.includes(`start=${shiftDays(end, -30)}`) && u.includes(`end=${end}`))).toBe(true));
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

  describe("moving the chart", () => {
    const long = { ...detail, bars: { first: "2020-01-01", last: "2024-12-31", count: 1200 } };
    const open = async (d: typeof detail, urls: string[] = []) => {
      const respond = route({ "/api/instruments": [inst], "/api/instruments/7": d, "/api/instruments/7/bars": bars });
      vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
        urls.push(String(input));
        return respond(input);
      });
      wrap(<AuthProvider><InstrumentsPage /></AuthProvider>);
      fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "xy" } });
      fireEvent.click(await screen.findByRole("button", { name: /XYZ/ }));
      await screen.findByText("basis: Raw (as traded)");
      scale.set.mockClear();
      scale.fit.mockClear();
    };

    it("zooms in to half the width around the middle and zooms out to twice the width", async () => {
      scale.range = { from: 20, to: 80 };
      await open(detail);
      fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
      expect(scale.set).toHaveBeenLastCalledWith({ from: 35, to: 65 });
      fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
      expect(scale.set).toHaveBeenLastCalledWith({ from: -10, to: 110 }); // twice the 60 bars in view
    });

    it("stops zooming in once only a handful of bars are in view", async () => {
      scale.range = { from: 40, to: 48 };
      await open(detail);
      fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
      expect(scale.set).not.toHaveBeenCalled();
    });

    it("moves a quarter of the view left and right, and fits everything", async () => {
      scale.range = { from: 20, to: 120 };
      await open(detail);
      fireEvent.click(screen.getByRole("button", { name: "Move right" }));
      expect(scale.set).toHaveBeenLastCalledWith({ from: 45, to: 145 });
      fireEvent.click(screen.getByRole("button", { name: "Move left" }));
      expect(scale.set).toHaveBeenLastCalledWith({ from: -5, to: 95 });
      fireEvent.click(screen.getByRole("button", { name: "Fit all" }));
      expect(scale.fit).toHaveBeenCalledTimes(1);
    });

    it("asks for earlier history when moving left or zooming out from the first loaded bar", async () => {
      scale.range = { from: 0, to: 100 };
      const urls: string[] = [];
      await open(long, urls);
      const before = urls.filter((u) => u.includes("/bars")).length;
      fireEvent.click(screen.getByRole("button", { name: "Move left" }));
      await waitFor(() => expect(urls.filter((u) => u.includes("/bars")).length).toBeGreaterThan(before));
      expect(urls.filter((u) => u.includes("/bars")).at(-1)).toMatch(/start=2022-12-3[01]/); // the year before, ending where it ended
      expect(urls.filter((u) => u.includes("/bars")).at(-1)).toContain("end=2024-12-31");
    });

    it("never goes back past the instrument's first bar", async () => {
      scale.range = { from: 0, to: 100 };
      const urls: string[] = [];
      await open(detail, urls); // the chart already starts on the first bar, 2024-01-01
      const before = urls.length;
      fireEvent.click(screen.getByRole("button", { name: "Move left" }));
      fireEvent.click(screen.getByRole("button", { name: "Zoom out" }));
      expect(urls.length).toBe(before);
    });

    it("does nothing before the chart has laid out", async () => {
      scale.range = null;
      await open(detail);
      fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
      expect(scale.set).not.toHaveBeenCalled();
      scale.range = { from: 0, to: 100 };
    });
  });

  describe("live price", () => {
    const quote = { ltp: "2875.5", open: "2860", high: "2880", low: "2855", prev_close: "2865", volume: "1234567", updated_at: "2026-11-12T04:30:00+00:00" };
    const dayCandle = { time: "2026-11-12", open: "2860", high: "2880", low: "2855", close: "2875.5", volume: "1234567" };
    const live = (over: Record<string, unknown> = {}) => ({ today: "2026-11-12", candle: dayCandle, live: true, feed: { state: "CONNECTED", last_tick_at: "2026-11-12T04:30:00+00:00" }, session_date: "2026-11-12", quote, ...over });
    const liveCalls = (urls: string[]) => urls.filter((u) => u.includes("/api/live/7"));
    const open = async (liveBody: unknown, urls: string[] = []) => {
      const respond = route({ "/api/instruments": [inst], "/api/instruments/7": detail, "/api/instruments/7/bars": bars, "/api/live/7": liveBody });
      vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
        urls.push(String(input));
        return respond(input);
      });
      wrap(<AuthProvider><InstrumentsPage /></AuthProvider>);
      fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "xy" } });
      fireEvent.click(await screen.findByRole("button", { name: /XYZ/ }));
      await screen.findByText("basis: Raw (as traded)");
      scale.update.mockClear();
    };
    const pick = (name: string) => {
      fireEvent.click(screen.getByRole("button", { name: /^Timeframe:/ }));
      fireEvent.click(within(screen.getByRole("menu", { name: "Timeframes" })).getByRole("menuitemradio", { name }));
    };

    it("moves today's daily candle with the server's live candle and says it is live", async () => {
      const urls: string[] = [];
      await open(live(), urls);
      await waitFor(() => expect(scale.update).toHaveBeenCalledWith({ time: "2026-11-12", open: 2860, high: 2880, low: 2855, close: 2875.5 }));
      expect(scale.update).toHaveBeenCalledWith(expect.objectContaining({ time: "2026-11-12", value: 1234567 })); // the volume bar
      expect(liveCalls(urls)[0]).toContain("timeframe=1d");
      expect(liveCalls(urls)[0]).toContain("adjust=none");
      expect(screen.getByTestId("live-badge")).toHaveTextContent("LIVE");
      expect(screen.getByTestId("ohlc-legend")).toHaveTextContent("C 2875.5");
    });

    it("asks for this week's candle on the weekly chart and draws it on the week's first day", async () => {
      const urls: string[] = [];
      await open(live({ candle: { ...dayCandle, time: "2026-11-09", open: "2800" } }), urls);
      pick("1 week");
      await waitFor(() => expect(liveCalls(urls).some((u) => u.includes("timeframe=1w"))).toBe(true));
      await waitFor(() => expect(scale.update).toHaveBeenCalledWith({ time: "2026-11-09", open: 2800, high: 2880, low: 2855, close: 2875.5 }));
    });

    it("draws the current intraday bar at its own minute, reaching today in the range it asks for", async () => {
      const urls: string[] = [];
      const t = 1794456000; // a UTC minute
      await open(live({ candle: { time: t, open: "2870", high: "2876", low: "2869", close: "2875.5", volume: "900" } }), urls);
      pick("5 minutes");
      await waitFor(() => expect(liveCalls(urls).some((u) => u.includes("timeframe=5m"))).toBe(true));
      await waitFor(() => expect(scale.update).toHaveBeenCalledWith({ time: t + 19800, open: 2870, high: 2876, low: 2869, close: 2875.5 }));
      const asked = urls.filter((u) => u.includes("/bars") && u.includes("timeframe=5m")).at(-1) ?? "";
      expect(asked).toContain(`end=${todayIST()}`); // today's minutes come live, so the range reaches today
    });

    it("still shows the last price after the market closes but does not call it live", async () => {
      await open(live({ live: false, feed: { state: "STOPPED", last_tick_at: "2026-11-12T10:05:00+00:00" } }));
      expect(await screen.findByTestId("live-badge")).toHaveTextContent("last price");
    });

    it("ignores a candle older than the bars the chart already has", async () => {
      await open(live({ candle: { ...dayCandle, time: "2024-06-01" } }));
      await new Promise((r) => setTimeout(r, 100));
      expect(scale.update).not.toHaveBeenCalled();
    });

    it("draws nothing when there is no candle yet", async () => {
      await open(live({ candle: null, quote: null, live: false }));
      await new Promise((r) => setTimeout(r, 100));
      expect(scale.update).not.toHaveBeenCalled();
      expect(screen.queryByTestId("live-badge")).not.toBeInTheDocument();
    });

    it("keeps asking every couple of seconds, and stops once the chart is moved back to an older range", async () => {
      const urls: string[] = [];
      await open(live(), urls);
      await waitFor(() => expect(liveCalls(urls).length).toBeGreaterThanOrEqual(2), { timeout: 4500 });
      fireEvent.click(screen.getByRole("button", { name: "Custom range" }));
      fireEvent.change(screen.getByLabelText("To"), { target: { value: "2024-06-30" } });
      await waitFor(() => expect(urls.some((u) => u.includes("/bars") && u.includes("end=2024-06-30"))).toBe(true));
      const before = liveCalls(urls).length;
      await new Promise((r) => setTimeout(r, 2600));
      expect(liveCalls(urls).length).toBe(before);
    }, 15000);
  });

  describe("strategy on the chart", () => {
    const params = { trend_sma: 200, entry_rsi: 30, exit_rsi: 60, max_positions: 10 };
    const saved = (id: string, name: string) => ({ config_id: id, name, strategy_id: "trend_pullback", universe: "nifty200", max_instruments: null, timeframe: "1D", params, screen: null, in_use: false, created_at: "2026-11-11T10:00:00+00:00", stage: "RESEARCH" });
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

    it("keeps corporate-action arrows off the chart until Events is switched on, then draws them", async () => {
      (table as Record<string, unknown>)["/api/instruments/7"] = { ...detail, actions: [{ ...detail.actions[0], ex_date: "2024-06-11" }] }; // on the one bar there is
      await open();
      const events = await screen.findByRole("button", { name: "Events" });
      const arrows = () => (vi.mocked(createSeriesMarkers).mock.calls.at(-1)?.[1] as { text: string }[] | undefined) ?? [];
      await waitFor(() => expect(vi.mocked(createSeriesMarkers)).toHaveBeenCalled());
      expect(arrows().some((m) => m.text === "bonus")).toBe(false); // the bonus on 2024-06-12 is not drawn by default
      expect(events).toHaveAttribute("aria-pressed", "false");
      fireEvent.click(events);
      await waitFor(() => expect(arrows().some((m) => m.text === "bonus")).toBe(true));
      expect(screen.getByRole("button", { name: "Events" })).toHaveAttribute("aria-pressed", "true");
      fireEvent.click(screen.getByRole("button", { name: "Events" }));
      await waitFor(() => expect(arrows().some((m) => m.text === "bonus")).toBe(false));
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
