import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RiseCell, RiseText } from "@/components/market/RiseCell";
import { RiseEffectPanel } from "@/components/market/RiseEffectPanel";
import { riseEffectSchema, riseOddsLatestSchema, riseOddsSchema } from "@/lib/schemas";

const load = (n: string) => JSON.parse(readFileSync(join(__dirname, `contract/${n}.json`), "utf8"));
const ODDS = riseOddsSchema.parse(load("market_rise_odds"));
const REAL_EFFECT = riseEffectSchema.parse(load("market_rise_odds_effect")); // a real response: too few days to say anything
const ENOUGH = riseEffectSchema.parse({
  ...REAL_EFFECT,
  up: {
    horizon: 5, enough: true, days: 75, rank_correlation: 0.21, all: { n: 75, mean: 1.1, up_share: 70 },
    bands: [
      { band: "top fifth", from: 0.55, to: 0.61, n: 15, mean: 2.5, up_share: 80 },
      { band: "middle", from: 0.45, to: 0.55, n: 45, mean: 0.9, up_share: 68 },
      { band: "bottom fifth", from: 0.38, to: 0.45, n: 15, mean: -0.4, up_share: 40 },
    ],
  },
});
function backend(effect: unknown) {
  vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(String(url).includes("effect") ? effect : ODDS), { status: 200 }));
}
const mount = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><RiseEffectPanel symbol="TCS" /></QueryClientProvider>);
afterEach(() => vi.unstubAllGlobals());

describe("RiseEffectPanel", () => {
  it("shows the bands, the all-days line and the correlation, and says the honest thing", async () => {
    backend(ENOUGH);
    mount();
    expect(await screen.findByText("top fifth")).toBeInTheDocument();
    expect(screen.getByText("+2.50%")).toBeInTheDocument();
    expect(screen.getByText("-0.40%")).toBeInTheDocument();
    expect(screen.getByText("All days")).toBeInTheDocument();
    expect(screen.getByText(/Rank correlation[^]*0\.21/)).toBeInTheDocument();
    expect(screen.getByText(/a lean, not a signal/)).toBeInTheDocument();
  });

  it("says nothing about a kind with too few days (a real response)", async () => {
    backend(REAL_EFFECT);
    mount();
    expect((await screen.findAllByText(/too few to say anything/)).length).toBe(2);
    expect(screen.queryByText("top fifth")).toBeNull();
  });

  it("shows nothing for a stock that was never scored", async () => {
    vi.stubGlobal("fetch", async (url: string) => new Response(JSON.stringify(String(url).includes("effect") ? REAL_EFFECT : { ...ODDS, scored: false, latest: null, history: [] }), { status: 200 }));
    const { container } = mount();
    await new Promise((r) => setTimeout(r, 50));
    expect(container.textContent).toBe("");
  });
});

describe("RiseText", () => {
  const LATEST = riseOddsLatestSchema.parse({ horizon: 5, items: { "1": { up: { day: "2026-11-10", prob: 0.58, pct: 90 }, rel: { day: "2026-11-10", prob: 0.52, pct: 70 } }, "2": { rel: { day: "2026-11-10", prob: 0.47, pct: 10 } } } });
  it("shows the own-direction chance coloured by its rank, with the relative rank beside it, and a dash when never scored", () => {
    render(<table><tbody><tr><RiseCell odds={LATEST.items["1"]} /><RiseCell odds={undefined} /></tr></tbody></table>);
    const cell = screen.getByText("58%");
    expect(cell.closest("span")).toHaveClass("text-emerald-700");
    expect(cell.closest("span")).toHaveAttribute("title", expect.stringContaining("Chance of beating the median stock: 52.0%"));
    expect(screen.getByText("r70")).toBeInTheDocument();
    expect(screen.getByTitle("Not scored (too little trading or history)")).toBeInTheDocument();
  });
  it("copes with only the relative model", () => {
    render(<RiseText odds={LATEST.items["2"]} />);
    expect(screen.getByText("r10")).toBeInTheDocument();
  });
});
