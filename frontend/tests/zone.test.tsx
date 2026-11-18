import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ZonePanel } from "@/components/market/ZonePanel";
import { marketZoneSchema } from "@/lib/schemas";

const LATEST = {
  day: "2026-11-17",
  age_days: 0,
  live: false,
  as_of: null,
  fear_greed: 63.4,
  label: "Greed",
  trend: "BULL",
  volatility: "CALM",
  universe: 1619,
  advancers: 900,
  decliners: 600,
  unchanged: 119,
  pct_above_50: 45.3,
  pct_above_200: 50.1,
  highs: 44,
  lows: 21,
};
const ZONE = {
  latest: LATEST,
  drivers: [
    { key: "momentum", name: "Index trend against its 125-day average", score: 81.2 },
    { key: "breadth", name: "Stocks above their 50-day average", score: 22.0 },
  ],
  history: [
    { day: "2026-11-13", fear_greed: 50, trend: "SIDEWAYS" },
    { day: "2026-11-16", fear_greed: 58, trend: "BULL" },
    { day: "2026-11-17", fear_greed: 63.4, trend: "BULL" },
  ],
};
function backend(zone: unknown, status = 200) {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(zone), { status }));
}
const mount = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ZonePanel />
    </QueryClientProvider>,
  );
afterEach(() => vi.unstubAllGlobals());

describe("market zone panel", () => {
  it("explains each signal in plain words with the points it adds to the score", async () => {
    backend(ZONE);
    mount();
    expect(await screen.findByText("Is the market trending up?")).toBeInTheDocument();
    expect(screen.getByText(/Strongly greedy · \+15\.6 points/)).toBeInTheDocument(); // (81.2 - 50) / 2 signals
    expect(screen.getByText(/Strongly fearful · −14\.0 points/)).toBeInTheDocument(); // (22 - 50) / 2
    expect(screen.getByText("The market is well above its usual level: buyers are in control.")).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 signals lean greedy, 1 lean fearful, 0 are normal/)).toBeInTheDocument();
  });

  it("shows how Nifty 50 did after each zone", async () => {
    const forward = [5, 20, 60].map((horizon) => ({ horizon, avg_pct: 1.5, up_pct: 70 }));
    const perf = { nifty: [{ day: "2026-11-17", close: 24000 }], zones: [{ zone: "Extreme greed", days: 633, forward }, { zone: "All days", days: 2645, forward }] };
    vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(String(url).includes("performance") ? perf : ZONE), { status: 200 }));
    mount();
    expect(await screen.findByText("Nifty 50 after each zone")).toBeInTheDocument();
    expect(screen.getByText("633")).toBeInTheDocument();
    expect(screen.getAllByText(/\+1\.5%/).length).toBe(6);
  });

  it("shows the score, the zone, the market type and the breadth", async () => {
    backend(ZONE);
    mount();
    expect(await screen.findByText("63")).toBeInTheDocument();
    expect(screen.getByText("Greed", { selector: "div" })).toBeInTheDocument();
    expect(screen.getByText("Bull market")).toBeInTheDocument();
    expect(screen.getByText("Calm volatility")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Fear and greed 63 out of 100" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "900 stocks up, 600 down" })).toBeInTheDocument();
    expect(screen.getByText("45.3%")).toBeInTheDocument();
    expect(screen.getByText("44 / 21")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /^Fear and greed over the last 3 trading days/ })).toBeInTheDocument();
  });
  it("says when the reading is live and when it was worked out", async () => {
    backend({ ...ZONE, latest: { ...LATEST, live: true, as_of: "2026-11-18T05:05:00+00:00" } });
    mount();
    expect(await screen.findByText(/worked out at 10:35/)).toBeInTheDocument();
    expect(screen.queryByText(/As of the close/)).toBeNull();
  });

  it("lists the signals with the biggest pull on the score first", async () => {
    backend(ZONE);
    mount();
    expect(await screen.findByText("Is the market trending up?")).toBeInTheDocument();
    const names = screen.getAllByRole("listitem").map((li) => li.textContent ?? "");
    expect(names[0]).toContain("Is the market trending up?");
    expect(names[1]).toContain("Are most stocks doing well?");
  });
  it("says there is not enough history instead of a number, and warns when the data is old", async () => {
    backend({ ...ZONE, latest: { ...LATEST, fear_greed: null, label: null, age_days: 6, trend: "UNKNOWN", volatility: "UNKNOWN" } });
    mount();
    expect(await screen.findByText("Not enough history yet")).toBeInTheDocument();
    expect(screen.getByText("Trend unknown")).toBeInTheDocument();
    expect(screen.getByText("The zone is out of date")).toBeInTheDocument();
  });
  it("says it is not built yet when there is nothing, and when it cannot load", async () => {
    backend({ latest: null, history: [], drivers: [] });
    const first = mount();
    expect(await screen.findByText("Market zone not built yet")).toBeInTheDocument();
    first.unmount();
    backend({}, 500);
    mount();
    expect(await screen.findByText("Could not load the market zone")).toBeInTheDocument();
  });
  it("accepts the shape the API sends", () => {
    expect(marketZoneSchema.safeParse(ZONE).success).toBe(true);
    expect(marketZoneSchema.safeParse({ latest: null, history: [], drivers: [] }).success).toBe(true);
  });
});
