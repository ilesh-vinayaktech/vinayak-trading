import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OrderContext } from "@/components/paper/OrderContext";

const lv = (price: number, d: number) => ({ price, touches: 3, bars_since: 4, distance_pct: d });
const SCORE = (score: number | null) => ({ symbol: "TANLA", name: "Tanla", as_of: "2026-11-17", scored: score !== null, score, components: { trend: null, participation: null, smart_money: null, quality: null }, setup: score !== null ? "Accumulation" : null, why: null, history: [] });
const LEVELS = (state: string) => ({ symbol: "TANLA", name: "Tanla", as_of: "2026-11-17", enough_history: true, supports: [lv(688, -3.2)], resistances: [lv(726, 2.1)], status: { state, level: 700, volume_ratio: 1, delivery_vs_avg: null }, series: [] });
function routes(score: unknown, levels: unknown) {
  vi.stubGlobal("fetch", async (url: string) => (url.includes("/api/market/score") ? new Response(JSON.stringify(score), { status: 200 }) : url.includes("/api/market/levels") ? new Response(JSON.stringify(levels), { status: 200 }) : new Response("{}", { status: 404 })));
}
const mount = (side: "BUY" | "SELL") => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><OrderContext symbol="TANLA" side={side} /></QueryClientProvider>);
afterEach(() => vi.unstubAllGlobals());

describe("OrderContext", () => {
  it("shows the score, setup, breakout state and nearest levels beside the order", async () => {
    routes(SCORE(71.4), LEVELS("Testing resistance"));
    mount("BUY");
    expect(await screen.findByText("Score 71/100, Accumulation")).toBeInTheDocument();
    expect(screen.getByText(/Testing resistance, support 688, resistance 726/)).toBeInTheDocument();
    expect(screen.queryByText(/score is/i)).not.toBeInTheDocument(); // a good score for a buy: no caution
  });

  it("cautions a buy on a low score or just under broken support, and a sale on a high score", async () => {
    routes(SCORE(22), LEVELS("Inside its range"));
    const a = mount("BUY");
    expect(await screen.findByText("The score is low for a buy.")).toBeInTheDocument();
    a.unmount();
    routes(SCORE(85), LEVELS("Inside its range"));
    const b = mount("SELL");
    expect(await screen.findByText("The score is high for a sale.")).toBeInTheDocument();
    b.unmount();
    routes(SCORE(60), LEVELS("Breakdown"));
    mount("BUY");
    expect(await screen.findByText("It has just broken below support.")).toBeInTheDocument();
  });

  it("shows nothing for a stock with no score and no levels, or when both calls fail", async () => {
    routes(SCORE(null), { symbol: "X", name: null, as_of: "2026-11-17", enough_history: false });
    const { container } = mount("BUY");
    await vi.waitFor(() => expect(container.textContent).toBe(""));
    vi.unstubAllGlobals();
    vi.stubGlobal("fetch", async () => new Response("{}", { status: 500 }));
    const second = mount("BUY");
    await vi.waitFor(() => expect(second.container.textContent).toBe(""));
  });
});
