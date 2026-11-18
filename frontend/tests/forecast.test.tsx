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

  it("says when the US moved little overnight that the call is little more than the usual tendency", async () => {
    backend({ ...FORECAST, overnight: { ...FORECAST.overnight, sp: 0.2 } });
    mount();
    expect(await screen.findByText(/moved only \+0\.20% overnight.*no skill over the market's usual tendency/)).toBeInTheDocument();
    vi.unstubAllGlobals();
    backend(FORECAST); // the S&P moved +0.8%
    mount();
    expect(await screen.findByText(/moved \+0\.80% overnight.*some skill/)).toBeInTheDocument();
  });

  it("shows the expected range as a research forecast beside the 5-session average, and says it is not a trading signal", async () => {
    const range = { latest: { as_of: "2026-11-17", for_day: "2026-11-18", made_at: "2026-11-18T03:25:00+00:00", forecast_range: 1.15, actual_range: null, version: "range-ridge-v1" }, five_session_avg: 0.92, yesterday_range: 1.31, record: [{ target_day: "2026-11-17", forecast: 1.1, actual: 1.4 }], resolved: 12, needed: 500 };
    vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(String(url).includes("range-forecast") ? range : FORECAST), { status: 200 }));
    mount();
    expect(await screen.findByLabelText("Expected range 1.15%")).toBeInTheDocument();
    expect(screen.getByText("Research forecast, forward validation in progress")).toBeInTheDocument();
    expect(screen.getByText(/average of the last five sessions is 0\.92% and yesterday's range was 1\.31%/)).toBeInTheDocument();
    expect(screen.getByText(/Forecast generated 08:55 am IST/i)).toBeInTheDocument();
    expect(screen.getByText(/not which way the market moves, and it is not a trading signal. 12 of 500 forecasts/)).toBeInTheDocument();
  });

  it("says plainly when no range forecast has been made yet", async () => {
    const none = { latest: null, five_session_avg: null, yesterday_range: null, record: [], resolved: 0, needed: 500 };
    vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(String(url).includes("range-forecast") ? none : FORECAST), { status: 200 }));
    mount();
    expect(await screen.findByText(/No range forecast yet. It is made at 08:55 IST/)).toBeInTheDocument();
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
