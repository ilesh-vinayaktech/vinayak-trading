import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ActionWorklistPage from "@/app/data/actions/page";
import fixture from "./contract/corporate_action_review.json";

const row = (over: object) => ({ ...fixture.items[0], ...over });

function mount(respond: (url: URL) => unknown) {
  const urls: URL[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    urls.push(url);
    return new Response(JSON.stringify(respond(url)), { status: 200 });
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ActionWorklistPage /></QueryClientProvider>);
  return urls;
}

afterEach(() => vi.unstubAllGlobals());

describe("Corporate action worklist", () => {
  it("shows each action with its impact, the stock's index badge and the price move", async () => {
    mount(() => ({ total: 2, by_kind: { demerger: 1, dividend: 1 }, items: [row({ symbol: "BIG", impact: 420, in_nifty200: true, move_pct: "-10.00" }), row({ symbol: "OLD", kind: "dividend", impact: 0, move_pct: null, has_prices: false })] }));
    expect(await screen.findByText("BIG")).toBeTruthy();
    expect(screen.getByText("Nifty 200")).toBeTruthy();
    expect(screen.getByText("420")).toBeTruthy();
    expect(screen.getByText("-10.00%")).toBeTruthy();
    expect(screen.getByText("no prices")).toBeTruthy();
  });

  it("asks the server for one kind when its button is pressed, and can load the rest", async () => {
    const urls = mount((u) => ({ total: 300, by_kind: { demerger: 100, dividend: 200 }, items: [row({ kind: u.searchParams.get("kind") ?? "demerger" })] }));
    await screen.findByText("Showing 1 of 300.");
    fireEvent.click(screen.getByRole("button", { name: "dividend (200)" }));
    await waitFor(() => expect(urls.some((u) => u.searchParams.get("kind") === "dividend")).toBe(true));
    fireEvent.click(await screen.findByRole("button", { name: "Show all" }));
    await waitFor(() => expect(urls.some((u) => u.searchParams.get("limit") === "5000")).toBe(true));
  });

  it("says so when nothing is waiting", async () => {
    mount(() => ({ total: 0, by_kind: {}, items: [] }));
    expect(await screen.findByText("Nothing waiting")).toBeTruthy();
  });
});
