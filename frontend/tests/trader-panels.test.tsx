import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AlertsPanel } from "@/components/market/AlertsPanel";
import { PositionsPanel } from "@/components/market/PositionsPanel";
import { SetupsPanel } from "@/components/market/SetupsPanel";

const lv = (price: number, d: number) => ({ price, touches: 3, bars_since: 4, distance_pct: d });
const LEVELS = { symbol: "TANLA", name: "Tanla", as_of: "2026-11-17", enough_history: true, supports: [lv(688, -3.2)], resistances: [lv(726, 2.1)], status: { state: "Testing resistance", level: 726, volume_ratio: 1.1, delivery_vs_avg: null }, series: [] };
const SUMMARY = { equity: "100000", cash: "50000", invested: "50000", pnl: { realized: "0", unrealized: "1200", fees: "10", net: "1190" }, positions: [{ instrument_id: 7, symbol: "TANLA", qty: "50", avg_cost: "690", last_price: "714", value: "35700", unrealized: "1200", upcoming: [] }], equity_curve: [], pending_orders: 0 };
const RUN = (names: string[]) => ({ total: names.length, sort: "score", as_of: "2026-11-17", rows: names.map((s, i) => ({ instrument_id: i + 1, symbol: s, score: `${80 - i}.2000`, chg_1m: i === 0 ? "12.3456" : "-4.0000", // the API sends numbers as text
 setup: i === 0 ? "Breakout setup" : null, score_why: i === 0 ? "Rising over 1 month" : null })) });

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

  it("shows the live price and the day's change beside each stock", async () => {
    routes({ "/api/screener/run": RUN(["GAIL"]), "/api/live/quotes": { quotes: { "1": { ltp: "184.30", prev_close: "180.00", change: "4.30", change_pct: 2.39, source: "live", as_of: "2026-11-18T05:00:00+00:00" } } } });
    mount(<SetupsPanel />);
    expect(await screen.findByText("184.30")).toBeInTheDocument();
    expect(screen.getByText("+2.39%")).toBeInTheDocument();
  });

  it("says when nothing matches", async () => {
    routes({ "/api/screener/run": RUN([]) });
    mount(<SetupsPanel />);
    expect(await screen.findByText("Nothing matches today.")).toBeInTheDocument();
  });
});

describe("PositionsPanel", () => {
  it("shows each holding with its nearest levels and breakout state", async () => {
    routes({ "/api/paper/summary": SUMMARY, "/api/market/levels": LEVELS, "/api/market/score": { symbol: "TANLA", name: "Tanla", as_of: "2026-11-17", scored: true, score: 33.4, components: { trend: null, participation: null, smart_money: null, quality: null }, setup: null, why: null, history: [] } });
    mount(<PositionsPanel />);
    expect(await screen.findByRole("rowheader", { name: "TANLA" })).toBeInTheDocument();
    expect(await screen.findByText("Testing resistance")).toBeInTheDocument();
    expect(screen.getByText("688")).toBeInTheDocument();
    expect(screen.getByText("726")).toBeInTheDocument();
    expect(screen.getByText("+1,200")).toBeInTheDocument();
    expect(await screen.findByText("33")).toBeInTheDocument();
  });

  it("shows nothing without positions or an account", async () => {
    routes({ "/api/paper/summary": { ...SUMMARY, positions: [] } });
    const { container } = mount(<PositionsPanel />);
    await vi.waitFor(() => expect(container.textContent).toBe(""));
  });
});

describe("AlertsPanel", () => {
  const ZONE = (a: string, b: string) => ({ latest: null, drivers: [], history: [{ day: "2026-11-16", fear_greed: 50, trend: a }, { day: "2026-11-17", fear_greed: 48, trend: b }] });
  it("flags a holding that broke support and a change of market trend", async () => {
    routes({ "/api/paper/summary": SUMMARY, "/api/market/levels": { ...LEVELS, status: { ...LEVELS.status, state: "Breakdown" } }, "/api/market/zone": ZONE("BULL", "SIDEWAYS") });
    mount(<AlertsPanel />);
    expect(await screen.findByText("TANLA: breakdown")).toBeInTheDocument();
    expect(await screen.findByText("Market trend changed to SIDEWAYS")).toBeInTheDocument();
  });
  it("shows nothing when nothing changed", async () => {
    routes({ "/api/paper/summary": SUMMARY, "/api/market/levels": LEVELS, "/api/market/zone": ZONE("BULL", "BULL") });
    const { container } = mount(<AlertsPanel />);
    await new Promise((r) => setTimeout(r, 100));
    expect(container.textContent).toBe("");
  });
});
