import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NewsPanel } from "@/components/market/NewsPanel";
import { marketNewsSchema } from "@/lib/schemas";

const NEWS = {
  items: [
    { title: "Sensex surges as FII inflows return", url: "https://ex.com/1", source: "economictimes", published_at: new Date().toISOString(), sentiment: 0.1, laya: 0.8, laya_confidence: 0.9, reading: "positive", reading_value: 0.8, reading_model: "laya", symbols: ["TCS"] },
    { title: "Board meeting on Thursday", url: "https://ex.com/2", source: "livemint", published_at: new Date().toISOString(), sentiment: null, laya: null, laya_confidence: null, reading: null, reading_value: null, reading_model: null, symbols: [] },
  ],
  mood: [{ day: "2026-11-16", avg: -0.2, n: 8, positive: 1, negative: 4 }, { day: "2026-11-17", avg: 0.3, n: 10, positive: 6, negative: 2 }],
  stocks: [{ symbol: "TCS", mentions: 3, avg: 0.4 }],
};
function backend(body: unknown, status = 200) {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(body), { status }));
}
const mount = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <NewsPanel />
    </QueryClientProvider>,
  );
afterEach(() => vi.unstubAllGlobals());

describe("NewsPanel", () => {
  it("matches the schema", () => expect(marketNewsSchema.safeParse(NEWS).success).toBe(true));

  it("shows today's mood with its counts, the stocks named and the headlines, unscored ones without a pill", async () => {
    backend(NEWS);
    mount();
    expect(await screen.findAllByText("Positive")).toHaveLength(2); // today's mood and the first headline; the unscored headline has none
    expect(screen.getByText(/6 positive and 2 negative of 10 scored headlines on 2026-11-17/)).toBeInTheDocument();
    expect(screen.getByText(/TCS \(3, positive\)/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sensex surges as FII inflows return" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.getByText(/It has not been tested against what prices did next/)).toBeInTheDocument();
  });

  it("says so when there is no news and when loading fails", async () => {
    backend({ items: [], mood: [], stocks: [] });
    mount();
    expect(await screen.findByText("No news yet")).toBeInTheDocument();
    vi.unstubAllGlobals();
    backend({}, 500);
    mount();
    expect(await screen.findByText("Could not load the news")).toBeInTheDocument();
  });
});
