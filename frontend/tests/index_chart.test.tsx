import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IndexChart } from "@/components/charts/IndexChart";
import { indexBarsSchema } from "@/lib/schemas";

// the chart library itself is exercised elsewhere: here only what the index page hands it
const seen = vi.hoisted(() => ({ props: null as null | Record<string, unknown> }));
vi.mock("@/components/charts/PriceChart", () => ({
  PriceChart: (p: Record<string, unknown> & { topbar: (api: unknown) => React.ReactNode }) => {
    seen.props = p;
    return <div data-testid="price-chart">{p.topbar({ undo() {}, redo() {}, canUndo: false, canRedo: false, count: 0, listOpen: false, toggleList() {}, screenshot() {} })}</div>;
  },
}));

const bar = (date: string, extra = {}) => ({ date, open: "100", high: "110", low: "90", close: "105", volume: "0", factor: "1", ...extra });
const DAILY = { symbol: "NIFTY 50", exchange: "NSE", timeframe: "1d", first: "1990-07-03", last: "2026-11-18", intraday_first: "2026-11-18", bars: [bar("2026-11-17"), bar("2026-11-18")] };
const calls: string[] = [];
function backend(body: (url: URL) => unknown, status = 200) {
  vi.stubGlobal("fetch", async (input: string | URL) => {
    const url = new URL(String(input), "http://x");
    calls.push(url.search);
    return new Response(JSON.stringify(body(url)), { status });
  });
}
const mount = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><IndexChart symbol="NIFTY 50" /></QueryClientProvider>);
afterEach(() => {
  vi.unstubAllGlobals();
  calls.length = 0;
  seen.props = null;
});

describe("IndexChart", () => {
  it("matches the schema", () => expect(indexBarsSchema.safeParse(DAILY).success).toBe(true));

  it("draws the index's daily candles in the same chart as an instrument, with its own key for drawings and no volume or price basis", async () => {
    backend(() => DAILY);
    mount();
    expect(await screen.findByTestId("price-chart")).toBeInTheDocument();
    expect(calls[0]).toContain("symbol=NIFTY+50");
    expect(calls[0]).toContain("timeframe=1d");
    expect(seen.props?.instrumentId).toBe("idx:NIFTY 50"); // an index's drawings never mix with a stock's
    expect(seen.props?.adjust).toBe("none");
    expect((seen.props?.bars as unknown[]).length).toBe(2);
    expect(screen.getByRole("toolbar", { name: "Chart controls" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Events" })).not.toBeInTheDocument();
    expect(screen.getByText(/An index has no volume/)).toBeInTheDocument();
  });

  it("asks for minute candles when an intraday timeframe is picked", async () => {
    backend((u) => (u.searchParams.get("timeframe") === "5m" ? { ...DAILY, timeframe: "5m", bars: [bar("2026-11-18", { time: 1_795_000_000 })] } : DAILY));
    mount();
    await screen.findByTestId("price-chart");
    fireEvent.click(screen.getByRole("button", { name: /Timeframe/i }));
    fireEvent.click(await screen.findByRole("menuitemradio", { name: "5 minutes" }));
    await vi.waitFor(() => expect(calls.some((c) => c.includes("timeframe=5m"))).toBe(true));
    await vi.waitFor(() => expect((seen.props?.bars as { time?: number }[])[0]?.time).toBe(1_795_000_000));
  });

  it("says plainly when an index has no minute candles yet instead of showing an empty chart", async () => {
    backend((u) => (u.searchParams.get("timeframe") === "1d" ? DAILY : { ...DAILY, timeframe: "1m", intraday_first: null, bars: [] }));
    mount();
    await screen.findByTestId("price-chart");
    fireEvent.click(screen.getByRole("button", { name: /Timeframe/i }));
    fireEvent.click(await screen.findByRole("menuitemradio", { name: "1 minute" }));
    expect(await screen.findByText("No minute candles in this range")).toBeInTheDocument();
    expect(screen.getByText(/live feed has not stored minutes for this index yet/)).toBeInTheDocument();
  });

  it("reports an index with no candles", async () => {
    backend(() => ({ detail: "no candles for the index NIFTY 50" }), 404);
    mount();
    expect(await screen.findByText(/no candles for the index|Could not load/i)).toBeInTheDocument();
  });
});
