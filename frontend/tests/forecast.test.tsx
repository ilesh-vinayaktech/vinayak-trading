import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ForecastPanel } from "@/components/market/ForecastPanel";
import { forecastSchema } from "@/lib/schemas";

const EV = [{ feature: "momentum", value: 70, effect: 0.21 }];
const record = (over = {}) => ({ subject: "Market", horizon_days: 1, live: false, n: 1678, hit_rate: 0.548, base_rate: 0.565, base_hit: 0.565, brier_skill: -0.008, beats_guessing: false, calibration: [], ...over });
const FORECAST = {
  as_of: "2026-11-17",
  market: [{ horizon_days: 1, p_up: 0.58, evidence: EV }, { horizon_days: 5, p_up: 0.5, evidence: [] }],
  sectors: [{ name: "Bank", p_1d: 0.56, p_5d: 0.55, evidence: EV }, { name: "IT", p_1d: 0.41, p_5d: null, evidence: [] }],
  record: [record()],
  misses: [{ as_of: "2026-03-02", p_up: 0.7, realized: -0.021, went_up: false, evidence: [] }],
  labels: { momentum: "Index momentum" },
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
  it("matches the schema", () => expect(forecastSchema.safeParse(FORECAST).success).toBe(true));

  it("shows the chances, the lean, the evidence and each sector", async () => {
    backend(FORECAST);
    mount();
    expect(await screen.findByLabelText("58% chance up")).toBeInTheDocument();
    expect(screen.getByText("Leans up")).toBeInTheDocument();
    expect(screen.getByText("No clear lean")).toBeInTheDocument(); // 50%
    expect(screen.getAllByText(/Index momentum supports up/).length).toBeGreaterThan(0);
    expect(screen.getByRole("rowheader", { name: "Bank" })).toBeInTheDocument();
    expect(screen.getByText("41%")).toBeInTheDocument();
  });

  it("says plainly when the model has not beaten guessing, with the numbers", async () => {
    backend(FORECAST);
    mount();
    expect(await screen.findByText("This forecast has not beaten plain guessing")).toBeInTheDocument();
    expect(screen.getByText(/right 55% of 1678 days, always saying up would be right 56%/)).toBeInTheDocument();
  });

  it("does not warn when the model beats guessing, and lists the misses", async () => {
    backend({ ...FORECAST, record: [record({ beats_guessing: true, brier_skill: 0.02, hit_rate: 0.6 })] });
    mount();
    await screen.findByLabelText("58% chance up");
    expect(screen.queryByText("This forecast has not beaten plain guessing")).not.toBeInTheDocument();
    expect(screen.getByText(/2026-03-02: said 70% up, the market fell 2.1%/)).toBeInTheDocument();
  });

  it("says when nothing has been forecast and when loading fails", async () => {
    backend({ as_of: null, market: [], sectors: [], record: [], misses: [] });
    mount();
    expect(await screen.findByText("No forecast yet")).toBeInTheDocument();
    vi.unstubAllGlobals();
    backend({}, 500);
    mount();
    expect(await screen.findByText("Could not load the forecast")).toBeInTheDocument();
  });
});
