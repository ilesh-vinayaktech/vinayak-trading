import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LevelsPanel } from "@/components/market/LevelsPanel";
import { stockLevelsSchema } from "@/lib/schemas";

const lv = (price: number, d: number) => ({ price, touches: 4, bars_since: 10, distance_pct: d });
const DATA = {
  symbol: "TANLA",
  name: "Tanla Platforms",
  as_of: "2026-11-17",
  enough_history: true,
  since_split: null,
  price: 711,
  supports: [lv(688, -3.2), lv(650, -8.6)],
  resistances: [lv(726, 2.1)],
  status: { state: "Breakout", level: 705, volume_ratio: 2.1, delivery_vs_avg: 1.4 },
  profile: { bins: [{ price: 690, share: 0.1 }, { price: 700, share: 0.3 }, { price: 710, share: 0.2 }], poc: 700, value_low: 685, value_high: 715 },
  returns: { bins: [{ low: -2, high: 0, count: 100 }, { low: 0, high: 2, count: 140 }], last: 1.2, last_percentile: 71, worst: -6, best: 7 },
  high_52w: 733,
  low_52w: 540,
  series: [{ day: "2026-11-14", close: 700 }, { day: "2026-11-17", close: 711 }],
};
function backend(body: unknown, status = 200) {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(body), { status }));
}
const mount = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <LevelsPanel symbol="TANLA" />
    </QueryClientProvider>,
  );
afterEach(() => vi.unstubAllGlobals());

describe("LevelsPanel", () => {
  it("matches the schema", () => expect(stockLevelsSchema.safeParse(DATA).success).toBe(true));

  it("shows the breakout state with its volume and delivery, the levels and the histogram", async () => {
    backend(DATA);
    mount();
    expect(await screen.findByText("Breakout")).toBeInTheDocument();
    expect(screen.getByText(/volume 2.1× its norm/)).toBeInTheDocument();
    expect(screen.getByText(/delivery 1.4× its norm/)).toBeInTheDocument();
    expect(screen.getByText("726")).toBeInTheDocument();
    expect(screen.getByText("688")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /price over the last 2 days/ })).toBeInTheDocument();
    expect(screen.getByText(/bigger than 71% of days/)).toBeInTheDocument();
  });

  it("says plainly when there are too few bars, and shows nothing for an instrument with no levels", async () => {
    backend({ symbol: "NEW", name: null, as_of: "2026-11-17", enough_history: false });
    mount();
    expect(await screen.findByText("Not enough history for levels")).toBeInTheDocument();
  });

  it("shows nothing when the instrument is not a stock (404) and an error otherwise", async () => {
    backend({ detail: "no listed stock" }, 404);
    const { container } = mount();
    await vi.waitFor(() => expect(container.textContent).toBe(""));
    vi.unstubAllGlobals();
    backend({}, 500);
    mount();
    expect(await screen.findByText("Could not load the levels")).toBeInTheDocument();
  });
});
