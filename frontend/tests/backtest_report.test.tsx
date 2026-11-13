import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import ReportPage from "@/app/research/backtests/[id]/page";
import real from "./contract/backtest_report.json";

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "1" }), useRouter: () => ({ replace: vi.fn() }), usePathname: () => "/", useSearchParams: () => new URLSearchParams("") }));
// The chart draws on a canvas, which the test environment does not have.
vi.mock("@/components/charts/LineChart", () => ({ LineChart: ({ compare }: { compare?: unknown[] }) => <div data-testid="chart" data-compare={compare ? compare.length : 0} /> }));

const BENCH = { name: "Nifty 200 Total Return Index (gross)", note: null, curve: [{ date: "2025-06-09", level: "10000" }, { date: "2025-06-12", level: "10500" }],
  return: "0.0500", final: "10500", max_drawdown: "-0.0200", sharpe: "1.10", strategy_return: "0.0035", strategy_max_drawdown: "0.0000", strategy_sharpe: "0.90" };

function show(report: unknown) {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(report), { status: 200 }));
  render(<Providers><ReportPage /></Providers>);
}
afterEach(() => vi.unstubAllGlobals());

describe("the backtest report", () => {
  it("shows what was bought and sold, what each trade made, and where the money ended up", async () => {
    show({ ...real, benchmark: BENCH });
    expect((await screen.findAllByText("Ended with")).length).toBeGreaterThan(0);
    const trade = screen.getAllByText("XYZ")[0]?.closest("tr") as HTMLElement;
    expect(within(trade).getByText("2025-06-09 @ 100.00")).toBeInTheDocument();
    expect(within(trade).getByText("2025-06-12 @ 104.00")).toBeInTheDocument();
    expect(within(trade).getByText("36.00")).toBeInTheDocument(); // net profit after charges
  });
  it("sets the run beside the index: the same days, the index drawn on the chart, and who is ahead", async () => {
    show({ ...real, benchmark: BENCH });
    expect(await screen.findByText("Compared with Nifty 200 Total Return Index (gross)")).toBeInTheDocument();
    expect(screen.getByTestId("chart")).toHaveAttribute("data-compare", "2");
    expect(screen.getByText("5.00%")).toBeInTheDocument(); // the index's return
    expect(screen.getByText(/behind the index by 4\.7 percentage points/)).toBeInTheDocument();
  });
  it("says why there is no comparison instead of leaving it out", async () => {
    show({ ...real, benchmark: { ...BENCH, note: "Nifty 200 Total Return Index (gross) is not loaded", curve: [], return: null } });
    expect(await screen.findByText("Not compared with the index")).toBeInTheDocument();
    expect(screen.getByText(/is not loaded/)).toBeInTheDocument();
  });
  it("shows how much of the profit the charges took, the drawdown, and the study's survivorship warning", async () => {
    show({ ...real, benchmark: null, study: { experiment_id: 7, name: "My study" },
      summary: { ...real.summary, cost_drag: "0.4400", charges: "82245", pre_charge_pnl: "186729" },
      curve: [{ date: "2025-06-09", equity: "10000", drawdown: "0.0000" }, { date: "2025-06-10", equity: "9000", drawdown: "-0.1000" }, { date: "2025-06-11", equity: "9500", drawdown: "-0.0500" }] });
    expect(await screen.findByText(/44\.00% of the profit before charges/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Drawdown over time, worst -10.0 percent on 2025-06-10" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "My study" })).toHaveAttribute("href", "/research/studies/7");
    expect(screen.getByText(/survivorship bias flatters/)).toBeInTheDocument();
  });
  it("shows no comparison block when the response carries none", async () => {
    show({ ...real, benchmark: null });
    expect(await screen.findByText("Ended with")).toBeInTheDocument();
    expect(screen.queryByText(/Compared with/)).not.toBeInTheDocument();
  });
  it("shows the charges for the whole run and says how dividends and held shares make up the total", async () => {
    show({ ...real, benchmark: null, headline: { ...real.headline, charges: "528267.56", dividends: "217310.9" } });
    expect(await screen.findByText("₹5,28,267.56")).toBeInTheDocument();
    expect(screen.getByText(/adds ₹2,17,310.90 of dividends and the gain on shares still held/)).toBeInTheDocument();
  });
});
