import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PositionsPanel } from "@/components/market/PositionsPanel";
import { SetupsPanel } from "@/components/market/SetupsPanel";

const lv = (price: number, d: number) => ({ price, touches: 3, bars_since: 4, distance_pct: d });
const LEVELS = { symbol: "TANLA", name: "Tanla", as_of: "2026-11-17", enough_history: true, supports: [lv(688, -3.2)], resistances: [lv(726, 2.1)], status: { state: "Testing resistance", level: 726, volume_ratio: 1.1, delivery_vs_avg: null }, series: [] };
const SUMMARY = { equity: "100000", cash: "50000", invested: "50000", pnl: { realized: "0", unrealized: "1200", fees: "10", net: "1190" }, positions: [{ instrument_id: 7, symbol: "TANLA", qty: "50", avg_cost: "690", last_price: "714", value: "35700", unrealized: "1200", upcoming: [] }], equity_curve: [], pending_orders: 0 };
const RUN = (names: string[]) => ({ total: names.length, sort: "score", as_of: "2026-11-17", rows: names.map((s, i) => ({ instrument_id: i + 1, symbol: s, score: 80 - i, chg_1m: i === 0 ? 12.3 : -4, setup: i === 0 ? "Breakout setup" : null, score_why: i === 0 ? "Rising over 1 month" : null })) });

function routes(map: Record<string, unknown>) {
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    const key = Object.keys(map).find((k) => url.includes(k));
    if (!key) return new Response("{}", { status: 404 });
    const v = map[key];
    return new Response(JSON.stringify(typeof v === "function" ? (v as (b: unknown) => unknown)(init?.body ? JSON.parse(String(init.body)) : null) : v), { status: 200 });
  });
}
const mount = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
afterEach(() => vi.unstubAllGlobals());

describe("SetupsPanel", () => {
  it("lists the best-scoring stocks with their setup and reasons, and switches list", async () => {
    routes({ "/api/screener/run": (b: { preset: string }) => (b.preset === "top-swing-scores" ? RUN(["GAIL", "TANLA"]) : RUN(["INDHOTEL"])) });
    mount(<SetupsPanel />);
    expect(await screen.findByRole("rowheader", { name: "GAIL" })).toBeInTheDocument();
    expect(screen.getByText("Breakout setup")).toBeInTheDocument();
    expect(screen.getByText("+12.3%")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Money and trend agree" }));
    expect(await screen.findByRole("rowheader", { name: "INDHOTEL" })).toBeInTheDocument();
    expect(screen.getByText(/not a signal to trade on/)).toBeInTheDocument();
  });

  it("says when nothing matches", async () => {
    routes({ "/api/screener/run": RUN([]) });
    mount(<SetupsPanel />);
    expect(await screen.findByText("Nothing matches today.")).toBeInTheDocument();
  });
});

describe("PositionsPanel", () => {
  it("shows each holding with its nearest levels and breakout state", async () => {
    routes({ "/api/paper/summary": SUMMARY, "/api/market/levels": LEVELS });
    mount(<PositionsPanel />);
    expect(await screen.findByRole("rowheader", { name: "TANLA" })).toBeInTheDocument();
    expect(await screen.findByText("Testing resistance")).toBeInTheDocument();
    expect(screen.getByText("688")).toBeInTheDocument();
    expect(screen.getByText("726")).toBeInTheDocument();
    expect(screen.getByText("+1,200")).toBeInTheDocument();
  });

  it("shows nothing without positions or an account", async () => {
    routes({ "/api/paper/summary": { ...SUMMARY, positions: [] } });
    const { container } = mount(<PositionsPanel />);
    await vi.waitFor(() => expect(container.textContent).toBe(""));
  });
});
