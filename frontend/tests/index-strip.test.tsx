import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IndexStrip } from "@/components/market/IndexStrip";

const card = (symbol: string, ltp: string, change: string, pct: number, spark: number[] = [], source = "live") => ({ exchange: "NSE", symbol, source, ltp, prev_close: "1", change, change_pct: pct, day_high: null, day_low: null, as_of: "2026-11-18T05:00:00+00:00", spark });
function backend(body: unknown, status = 200) {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(body), { status }));
}
const mount = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><IndexStrip /></QueryClientProvider>);
afterEach(() => vi.unstubAllGlobals());

describe("IndexStrip", () => {
  it("shows each index with its price, change and a line for the day", async () => {
    backend({ live: true, indices: [card("NIFTY 50", "25387.40", "120.5", 0.48, [25300, 25350, 25387]), card("INDIA VIX", "15.50", "0.8", 5.4, [14.7, 15.5])] });
    mount();
    expect(await screen.findByText("Nifty 50")).toBeInTheDocument();
    expect(screen.getByText("25,387.40")).toBeInTheDocument();
    expect(screen.getByText(/\+120\.50 \(\+0\.48%\)/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Today's line, 3 minutes" })).toBeInTheDocument();
    expect(screen.getByText(/Live from the exchange feed/)).toBeInTheDocument();
  });

  it("shows a rising India VIX in the warning colour, because a rising VIX is fear", async () => {
    backend({ live: true, indices: [card("INDIA VIX", "15.50", "0.8", 5.4)] });
    const { container } = mount();
    await screen.findByText("India VIX");
    expect(container.querySelector(".text-red-700")).not.toBeNull();
    expect(container.querySelector(".text-emerald-700 ")).toBeNull();
  });

  it("marks last-close cards and says the feed is off", async () => {
    backend({ live: false, indices: [card("SENSEX", "82,500", "500", 0.6, [], "daily")] });
    mount();
    expect(await screen.findByText("close")).toBeInTheDocument();
    expect(screen.getByText(/feed is off/)).toBeInTheDocument();
  });

  it("shows nothing when there are no indices or the request fails", async () => {
    backend({ live: false, indices: [] });
    const a = mount();
    await new Promise((r) => setTimeout(r, 50));
    expect(a.container.textContent).toBe("");
  });
});
