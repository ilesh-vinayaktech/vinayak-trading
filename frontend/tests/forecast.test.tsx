import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ForecastPanel } from "@/components/market/ForecastPanel";
import { forecastSchema } from "@/lib/schemas";

const EV = [{ feature: "momentum", value: 70, effect: 0.21 }];
const record = (over = {}) => ({ subject: "Market", horizon_days: 1, live: false, n: 1678, hit_rate: 0.548, base_rate: 0.565, base_hit: 0.565, brier_skill: -0.008, beats_guessing: false, calibration: [], ...over });
const FORECAST = {
  as_of: "2026-11-17",
  market: [{ horizon_days: 1, p_up: 0.58, evidence: EV }, { horizon_days: 5, p_up: 0.5, evidence: [] }],
  sectors: [{ name: "Bank", p_1d: 0.56, p_5d: 0.55, evidence: EV }, { name: "IT", p_1d: 0.41, p_5d: null, evidence: [] }, { name: "Auto", p_1d: 0.5, p_5d: null, evidence: [] }],
  record: [record()],
  misses: [{ as_of: "2026-03-02", p_up: 0.7, realized: -0.021, went_up: false, evidence: [] }],
  labels: { momentum: "Index momentum" },
  overnight: {
    for_day: "2026-11-18", sp: 0.8, nq: 1.1, vix: -4.2, gift_gap_pct: 0.35,
    gift_history: [{ label: "Down more than 0.3%", days: 59, up_pct: 15.3, avg_pct: -0.84 }, { label: "Down up to 0.3%", days: 0, up_pct: null, avg_pct: null }, { label: "Up more than 0.3%", days: 228, up_pct: 69.3, avg_pct: 0.38 }],
  },
  today: { market_change_pct: 0.42, as_of: "2026-11-18T05:30:00+00:00", sectors: { Bank: 0.8, IT: 0.6, Auto: -0.3 } },
};
function backend(body: unknown, status = 200) {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(body), { status }));
}
const mount = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ForecastPanel />
    </QueryClientProvider>,
  );
afterEach(() => vi.unstubAllGlobals());

describe("ForecastPanel", () => {
  beforeEach(() => vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-18T06:00:00Z") }));
  afterEach(() => vi.useRealTimers());
  it("matches the schema", () => expect(forecastSchema.safeParse(FORECAST).success).toBe(true));

  it("puts what was expected beside what is happening, for the market and each sector", async () => {
    backend(FORECAST);
    mount();
    expect(await screen.findByLabelText("58% chance up")).toBeInTheDocument();
    expect(screen.getAllByText(/Expects a rise/).length).toBeGreaterThan(0);
    expect(screen.getByText("+0.42%")).toBeInTheDocument();
    expect(screen.getByText("Going as expected")).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "Bank" })).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 that had a lean are moving the way we expected/)).toBeInTheDocument(); // Bank up as expected, IT expected down but rose
    expect(screen.getAllByText("✗ against").length).toBe(1);
    expect(screen.getAllByText(/Index momentum points up/).length).toBeGreaterThan(0);
    expect(screen.getByText(/the market has closed higher on 56% of days/)).toBeInTheDocument();
    expect(screen.getByText(/The call has not yet beaten that/)).toBeInTheDocument();
  });

  it("shows the overnight US moves and GIFT Nifty, and how such mornings ended before", async () => {
    backend(FORECAST);
    mount();
    expect(await screen.findByText("Overnight, before the open")).toBeInTheDocument();
    expect(screen.getByText("+0.35%")).toBeInTheDocument();
    expect(screen.getByText("−4.20%")).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "Up more than 0.3%" })).toBeInTheDocument();
    expect(screen.getByText("69%")).toBeInTheDocument();
    expect(screen.queryByRole("rowheader", { name: "Down up to 0.3%" })).not.toBeInTheDocument(); // no mornings, no row
  });

  it("says it has no live prices when the feed is off, and does not judge the call", async () => {
    backend({ ...FORECAST, today: { market_change_pct: null, as_of: null, sectors: {} } });
    mount();
    expect(await screen.findByText(/No live prices right now/)).toBeInTheDocument();
    expect(screen.queryByText("Going as expected")).not.toBeInTheDocument();
  });

  it("says plainly when the model has not beaten guessing, with the numbers", async () => {
    backend(FORECAST);
    mount();
    expect(await screen.findByText("Not yet: it has not beaten plain guessing")).toBeInTheDocument();
    expect(screen.getByText(/called the direction right 55% of the time/)).toBeInTheDocument();
    expect(screen.getByText(/would have been right 56%/)).toBeInTheDocument();
  });

  it("does not warn when the model beats guessing, and lists the misses", async () => {
    backend({ ...FORECAST, record: [record({ beats_guessing: true, brier_skill: 0.02, hit_rate: 0.6 })] });
    mount();
    await screen.findByLabelText("58% chance up");
    expect(screen.queryByText("Not yet: it has not beaten plain guessing")).not.toBeInTheDocument();
    expect(screen.getByText(/2026-03-02: said 70% up, the market fell 2.1%/)).toBeInTheDocument();
  });

  it("says when nothing has been forecast and when loading fails", async () => {
    backend({ as_of: null, market: [], sectors: [], record: [], misses: [], today: null });
    mount();
    expect(await screen.findByText("No forecast yet")).toBeInTheDocument();
    vi.unstubAllGlobals();
    backend({}, 500);
    mount();
    expect(await screen.findByText("Could not load the forecast")).toBeInTheDocument();
  });
});
