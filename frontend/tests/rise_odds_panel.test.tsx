import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RiseOddsPanel } from "@/components/market/RiseOddsPanel";
import { riseOddsTopSchema } from "@/lib/schemas";

const load = (n: string) => JSON.parse(readFileSync(join(__dirname, `contract/${n}.json`), "utf8"));
const REAL = riseOddsTopSchema.parse(load("market_rise_odds_top"));
function backend(body: unknown, status = 200) {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(body), { status }));
}
const mount = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><RiseOddsPanel /></QueryClientProvider>);
afterEach(() => vi.unstubAllGlobals());

describe("RiseOddsPanel", () => {
  it("lists the top stocks with their chance and rank, each linking to the explorer, and states the honest numbers", async () => {
    backend(REAL); // a real response: it must parse with the schema the panel uses
    mount();
    const first = REAL.items[0]!;
    const link = await screen.findByRole("link", { name: first.symbol });
    expect(link).toHaveAttribute("href", `/data/instruments?id=${first.instrument_id}`);
    expect(screen.getByText(`${Math.round(first.prob * 100)}%`)).toBeInTheDocument();
    expect(screen.getByText(/57\.1% of the time/)).toBeInTheDocument();
    expect(screen.getByText(/64\.6% of the time/)).toBeInTheDocument(); // and the sharper side, the lag
    expect(screen.getByText(/not 70 to 80%/)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`As of ${REAL.day}`))).toBeInTheDocument();
  });

  it("switches to the stocks most likely to lag and asks the server for that side", async () => {
    const asked: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => {
      if (String(url).includes("rise-odds")) asked.push(String(url));
      return new Response(JSON.stringify(String(url).includes("side=bottom") ? riseOddsTopSchema.parse(load("market_rise_odds_bottom")) : REAL), { status: 200 });
    });
    mount();
    await screen.findByRole("link", { name: REAL.items[0]!.symbol });
    expect(asked.at(-1)).toContain("side=top");
    fireEvent.click(screen.getByRole("tab", { name: "Most likely to lag" }));
    await screen.findByText(/lowest first/i, { selector: "caption" });
    expect(asked.at(-1)).toContain("side=bottom");
  });

  it("switches to the own-direction kind and asks the server for it, with its own wording", async () => {
    const asked: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => {
      if (String(url).includes("rise-odds")) asked.push(String(url));
      return new Response(JSON.stringify(String(url).includes("kind=up") ? riseOddsTopSchema.parse(load("market_rise_odds_top_up")) : REAL), { status: 200 });
    });
    mount();
    await screen.findByRole("link", { name: REAL.items[0]!.symbol });
    expect(asked.at(-1)).toContain("kind=rel");
    fireEvent.click(screen.getByRole("tab", { name: "Own direction" }));
    await screen.findByText(/closing higher in 5 sessions, highest first/i, { selector: "caption" });
    expect(asked.at(-1)).toContain("kind=up");
    expect(screen.getByText(/64\.3% of the time/)).toBeInTheDocument(); // the own-direction evidence replaces the relative one
    expect(screen.getByRole("tab", { name: "Most likely to go down" })).toBeInTheDocument();
  });

  it("says so when nothing has been scored yet, and when it cannot load", async () => {
    backend(riseOddsTopSchema.parse(load("market_rise_odds_top_empty")));
    mount();
    expect(await screen.findByText(/No stock has been scored yet/)).toBeInTheDocument();
    vi.unstubAllGlobals();
    backend({ detail: "boom" }, 500);
    mount();
    expect(await screen.findByText("Could not load the rise odds")).toBeInTheDocument();
  });
});
