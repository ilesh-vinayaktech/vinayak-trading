import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import BacktestsPage from "@/app/research/backtests/page";
import DashboardPage from "@/app/dashboard/page";
import InstrumentsPage from "@/app/data/instruments/page";
import SystemPage from "@/app/system/page";
import { benchmarkDetail, dashboard, route } from "./fixtures";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
  usePathname: () => "/dashboard",
}));
vi.mock("lightweight-charts", () => ({
  ColorType: { Solid: "solid" },
  createChart: () => ({
    addLineSeries: () => ({ setData: vi.fn() }),
    addCandlestickSeries: () => ({ setData: vi.fn(), setMarkers: vi.fn() }),
    addHistogramSeries: () => ({ setData: vi.fn() }),
    priceScale: () => ({ applyOptions: vi.fn() }),
    timeScale: () => ({ fitContent: vi.fn() }),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  }),
}));

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
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
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
    vi.stubGlobal("fetch", route({ "/api/benchmarks/3": benchmarkDetail, "/api/benchmarks/3/levels": { levels: [{ date: "2000-01-03", level: "1688.44" }] } }));
    const { default: BenchmarksPage } = await import("@/app/data/benchmarks/page");
    wrap(<BenchmarksPage />);
    expect(await screen.findByText(/1 unresolved finding apply/)).toBeInTheDocument();
    expect(screen.getByText("technical not passed")).toBeInTheDocument();
    expect(screen.getByText("U02")).toBeInTheDocument();
    expect(screen.getAllByText(/Historical session hours are not verified/).length).toBeGreaterThan(0); // blocker and finding
    expect(screen.getByText(/no historical session hours are held as evidence/)).toBeInTheDocument();
    expect(screen.getByText("gate disabled")).toBeInTheDocument();
    expect(screen.getByText(/weekday rule provisional: 4,505/)).toBeInTheDocument();
  });
});

describe("Backtest Explorer", () => {
  it("keeps every run control disabled instead of faking a run", async () => {
    vi.stubGlobal("fetch", route({ "/api/backtests": [] }));
    wrap(<BacktestsPage />);
    expect(await screen.findByText("No backtests have been stored yet.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run backtest" })).toBeDisabled();
    for (const label of ["Strategy", "Cost schedule", "Initial capital"]) expect(screen.getByLabelText(label)).toBeDisabled();
  });
});

describe("System Activity", () => {
  it("lists ingestion and states that job metrics are not recorded", async () => {
    vi.stubGlobal(
      "fetch",
      route({
        "/api/system/activity": {
          ingestion: dashboard.system.recent_ingestion,
          validations: [{ benchmark_id: 1, latest: null }],
          backtests: [],
          jobs: { persisted: false, note: "job runtime and resource use are not recorded" },
        },
      }),
    );
    wrap(<SystemPage />);
    expect(await screen.findByText("nse/bhav")).toBeInTheDocument();
    expect(screen.getByText("never validated")).toBeInTheDocument();
    expect(screen.getByText("job runtime and resource use are not recorded")).toBeInTheDocument();
  });
});


describe("Data Explorer", () => {
  const inst = { id: 7, symbol: "XYZ", isin: "INE000A01010", name: "Xyz Ltd", status: "active", listed_on: null, delisted_on: null };
  const detail = { ...inst, bars: { first: "2024-01-01", last: "2024-12-31", count: 250 }, actions: [{ ex_date: "2024-06-12", kind: "bonus", status: "review", num: "1", den: "1", amount: null, subject: "Bonus 1:1" }] };
  const bars = {
    adjust: "none",
    adjustment_version: "a7ca8ba234cb8b8a",
    clean: false,
    bars: [{ date: "2024-06-11", open: "100", high: "101", low: "99", close: "100.5", volume: "1000", factor: "1" }],
    unapplied: [{ kind: "demerger", ex_date: "2024-07-01" }],
    provisional: [],
  };

  it("labels the price basis, shows the adjustment version and surfaces data-quality warnings", async () => {
    vi.stubGlobal("fetch", route({ "/api/instruments": [inst], "/api/instruments/7": detail, "/api/instruments/7/bars": bars }));
    wrap(<InstrumentsPage />);
    fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "xy" } });
    fireEvent.click(await screen.findByRole("button", { name: /XYZ/ }));
    expect(await screen.findByText("basis: Raw (as traded)")).toBeInTheDocument();
    expect(screen.getByText("adjustment version a7ca8ba234cb8b8a")).toBeInTheDocument();
    expect(screen.getByText("data-quality warnings")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("demerger 2024-07-01");
    expect(screen.getByTestId("price-chart")).toBeInTheDocument();
    expect(screen.getByText("Bonus 1:1")).toBeInTheDocument();
    expect(screen.getByText("review")).toBeInTheDocument(); // an unverified action is not shown as verified
    fireEvent.change(screen.getByLabelText("Price basis"), { target: { value: "split" } });
    await waitFor(() => expect(screen.getAllByText("Split/bonus adjusted").length).toBeGreaterThan(0));
  });

  it("explains an empty search instead of showing nothing", async () => {
    vi.stubGlobal("fetch", route({ "/api/instruments": [] }));
    wrap(<InstrumentsPage />);
    fireEvent.change(screen.getByLabelText("Symbol, ISIN or name"), { target: { value: "zzz" } });
    expect(await screen.findByText("No instrument matches.")).toBeInTheDocument();
  });
});
