import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SectorPanel } from "@/components/market/SectorPanel";
import { sectorRotationSchema } from "@/lib/schemas";

const row = (name: string, over: Record<string, unknown> = {}) => ({
  name, score: 70, close: 1234.5, ret_1d: 0.012, ret_5d: 0.02, ret_21d: 0.08, ret_63d: -0.03, ret_252d: null,
  above_50: true, above_200: false, rs_ratio: 104.2, rs_momentum: 101.3, quadrant: "Leading", symbol: "NIFTY PSU BANK", now: { ltp: 7250.5, prev_close: 7200, change_pct: 0.7, as_of: "2026-11-18T05:00:00+00:00" }, ...over,
});
const DATA = {
  as_of: "2026-11-17",
  benchmark: "NIFTY 500",
  sectors: [row("PSU bank", { score: 94 }), row("IT", { symbol: "NIFTY IT", now: null, score: 20, quadrant: "Lagging", rs_ratio: 96.1, ret_1d: -0.009, above_50: false, above_200: false })],
};
function backend(body: unknown, status = 200) {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(body), { status }));
}
const mount = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><SectorPanel /></QueryClientProvider>);
afterEach(() => vi.unstubAllGlobals());

describe("sector rotation panel", () => {
  it("shows each sector's live level and change and links to its stocks", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(DATA), { status: 200 }));
    mount();
    expect(await screen.findByText("7,250.50")).toBeInTheDocument();
    expect(screen.getByText("+0.70%")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "PSU bank" })).toHaveAttribute("href", "/market/index?symbol=NIFTY%20PSU%20BANK");
  });

  it("lists the sectors strongest first with returns, strength and the rotation quadrant", async () => {
    backend(DATA);
    mount();
    const table = await screen.findByRole("table", { name: "Sector rotation, strongest first" });
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByRole("rowheader")).toHaveTextContent("PSU bank");
    expect(within(rows[0]!).getByText("+1.2%")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("-3.0%")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("104.2")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Leading")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Lagging")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("-0.9%")).toBeInTheDocument();
  });
  it("shows a missing return as a dash and says what the trend dots mean", async () => {
    backend(DATA);
    mount();
    await screen.findByRole("table");
    expect(screen.getAllByText("–").length).toBeGreaterThan(0);
    expect(screen.getByRole("img", { name: "Above its 50-day average, below its 200-day" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Below both averages" })).toBeInTheDocument();
  });
  it("says so when there is no sector data, and when it cannot load", async () => {
    backend({ as_of: null, benchmark: "NIFTY 500", sectors: [] });
    const first = mount();
    expect(await screen.findByText("No sector data yet")).toBeInTheDocument();
    first.unmount();
    backend({}, 500);
    mount();
    expect(await screen.findByText("Could not load the sectors")).toBeInTheDocument();
  });
  it("accepts the shape the API sends", () => {
    expect(sectorRotationSchema.safeParse(DATA).success).toBe(true);
  });
});
