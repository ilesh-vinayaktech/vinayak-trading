import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AlertsPanel } from "@/components/market/AlertsPanel";
import { WatchlistPanel } from "@/components/market/WatchlistPanel";

const lv = (price: number, d: number) => ({ price, touches: 3, bars_since: 4, distance_pct: d });
const LEVELS = (state: string) => ({ symbol: "TANLA", name: "Tanla", as_of: "2026-11-17", enough_history: true, supports: [lv(688, -3.2)], resistances: [lv(726, 2.1)], status: { state, level: 726, volume_ratio: 2, delivery_vs_avg: null }, series: [] });
const SCORE = { symbol: "TANLA", name: "Tanla", as_of: "2026-11-17", scored: true, score: 82.2, components: { trend: null, participation: null, smart_money: null, quality: null }, setup: null, why: null, history: [] };

function backend(items: { instrument_id: number; symbol: string; name: string }[], state = "Testing resistance") {
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url}`);
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
    if (url.includes("/api/instruments")) return json([{ id: 9, symbol: "GAIL", name: "GAIL (India)", isin: "INE129A01019", status: "active", listed_on: null, delisted_on: null }]);
    if (url.includes("/api/market/watchlist")) return init?.method === "POST" || init?.method === "DELETE" ? json({ ok: true }) : json({ items });
    if (url.includes("/api/market/score")) return json(SCORE);
    if (url.includes("/api/market/levels")) return json(LEVELS(state));
    return json({}, 404);
  });
  return calls;
}
const mount = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
afterEach(() => vi.unstubAllGlobals());
const ITEM = { instrument_id: 7, symbol: "TANLA", name: "Tanla" };

describe("WatchlistPanel", () => {
  it("shows each watched stock with its score and status, and removes one", async () => {
    const calls = backend([ITEM]);
    mount(<WatchlistPanel />);
    expect(await screen.findByRole("rowheader", { name: "TANLA" })).toBeInTheDocument();
    expect(await screen.findByText("82")).toBeInTheDocument();
    expect(await screen.findByText("Testing resistance")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove TANLA" }));
    await waitFor(() => expect(calls.some((c) => c.startsWith("DELETE ") && c.endsWith("/api/market/watchlist/7"))).toBe(true));
  });

  it("adds a stock by symbol", async () => {
    const calls = backend([]);
    mount(<WatchlistPanel />);
    expect(await screen.findByText("Nothing watched yet.")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Stock symbol"), { target: { value: "gail" } });
    const pick = await screen.findByRole("button", { name: /GAIL.*GAIL \(India\).*INE129A01019/ });
    fireEvent.click(pick);
    await waitFor(() => expect(calls.some((c) => c.startsWith("POST ") && c.endsWith("/api/market/watchlist"))).toBe(true));
  });
});

describe("AlertsPanel with a watchlist", () => {
  it("flags a watched stock that broke out", async () => {
    backend([ITEM], "Breakout");
    mount(<AlertsPanel />);
    expect(await screen.findByText("TANLA: breakout")).toBeInTheDocument();
  });
});
