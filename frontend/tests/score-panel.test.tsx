import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ScorePanel } from "@/components/market/ScorePanel";
import { stockScoreSchema } from "@/lib/schemas";

const SCORED = {
  symbol: "TANLA", name: "Tanla", as_of: "2026-11-17", scored: true, score: 71.4,
  components: { trend: 80, participation: 55.5, smart_money: null, quality: 60 },
  setup: "Accumulation", why: "Rising over 1 month; High delivery %",
  history: [{ day: "2026-11-03", score: 60 }, { day: "2026-11-10", score: 66 }, { day: "2026-11-17", score: 71.4 }],
};
function backend(body: unknown, status = 200) {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(body), { status }));
}
const mount = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ScorePanel symbol="TANLA" /></QueryClientProvider>);
afterEach(() => vi.unstubAllGlobals());

describe("ScorePanel", () => {
  it("matches the schema", () => expect(stockScoreSchema.safeParse(SCORED).success).toBe(true));

  it("shows the score, its parts (a missing one as no data, not zero), the reasons and the history", async () => {
    backend(SCORED);
    mount();
    expect(await screen.findByLabelText("Score 71 out of 100")).toBeInTheDocument();
    expect(screen.getByText("Accumulation")).toBeInTheDocument();
    expect(screen.getByText("Rising over 1 month")).toBeInTheDocument();
    expect(screen.getByText("High delivery %")).toBeInTheDocument();
    expect(screen.getAllByText("Strong").length).toBeGreaterThan(0);
    expect(screen.getByText("no data")).toBeInTheDocument();
    expect(screen.getByText("+5")).toBeInTheDocument(); // 71.4 against the 66 of 2026-11-10; no reading a month back, so no month line
    expect(screen.queryByText(/vs 1 month/)).toBeNull();

  });

  it("explains an unscored stock instead of inventing a number, and shows nothing for a non-stock", async () => {
    backend({ ...SCORED, scored: false, score: null, components: { trend: null, participation: null, smart_money: null, quality: null }, history: [] });
    mount();
    expect(await screen.findByText(/has no score today/)).toBeInTheDocument();
    vi.unstubAllGlobals();
    backend({ detail: "no" }, 404);
    const { container } = mount();
    await vi.waitFor(() => expect(container.textContent).toBe(""));
  });
});
