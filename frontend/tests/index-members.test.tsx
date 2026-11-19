import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import IndexMembersPage from "@/app/market/index/page";

let search = "symbol=NIFTY%20IT";
vi.mock("@/components/charts/IndexChart", () => ({ IndexChart: ({ symbol }: { symbol: string }) => <div data-testid="index-chart-stub" data-symbol={symbol} /> })); // the chart has its own tests
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams(search), useRouter: () => ({ replace: vi.fn() }), usePathname: () => "/" }));

const MEMBERS = { kind: "index", symbol: "NIFTY IT", name: "IT", as_of: "2026-11-17", unmatched: 1, members: [
  { instrument_id: 1, symbol: "TCS", name: "Tata Consultancy", industry: "IT" },
  { instrument_id: 2, symbol: "INFY", name: "Infosys", industry: "IT" },
  { instrument_id: 3, symbol: "WIPRO", name: "Wipro", industry: "IT" },
  { instrument_id: 4, symbol: "NOQUOTE", name: "No Quote Ltd", industry: "IT" },
] };
const quote = (ltp: string, pct: number) => ({ ltp, prev_close: "100", change: "1", change_pct: pct, source: "live", as_of: "2026-11-18T05:00:00+00:00" });
const QUOTES = { quotes: { "1": quote("3900.00", -1.2), "2": quote("1500.00", 2.5), "3": quote("250.00", 0.4) } };

function backend(members: unknown = MEMBERS, status = 200) {
  vi.stubGlobal("fetch", async (url: string) => (url.includes("/api/live/quotes") ? new Response(JSON.stringify(QUOTES), { status: 200 }) : new Response(JSON.stringify(members), { status })));
}
const mount = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><IndexMembersPage /></QueryClientProvider>);
afterEach(() => { vi.unstubAllGlobals(); search = "symbol=NIFTY%20IT"; });
const order = () => within(screen.getByRole("table")).getAllByRole("link").map((e) => e.textContent);

describe("index members page", () => {
  it("lists every stock with its live price and change, strongest mover first, a stock with no price last", async () => {
    backend();
    mount();
    expect(await screen.findByRole("heading", { name: "IT" })).toBeInTheDocument();
    await screen.findByText("1,500.00");
    expect(order()).toEqual(["INFY", "WIPRO", "TCS", "NOQUOTE"]);
    expect(screen.getByLabelText("Summary")).toHaveTextContent("2 up");
    expect(screen.getByLabelText("Summary")).toHaveTextContent("1 down");
    expect(screen.getByLabelText("Summary")).toHaveTextContent("1 on the list not in our stock master");
  });

  it("can be sorted weakest first and by name, and a stock with no price stays last", async () => {
    backend();
    mount();
    await screen.findByText("1,500.00");
    fireEvent.click(screen.getByRole("button", { name: /Change/ })); // already by change, descending: a second click reverses it
    expect(order()).toEqual(["TCS", "WIPRO", "INFY", "NOQUOTE"]);
    fireEvent.click(screen.getByRole("button", { name: "Name" }));
    expect(order()).toEqual(["INFY", "NOQUOTE", "TCS", "WIPRO"]); // A to Z
  });

  it("opens an industry group the same way", async () => {
    search = "industry=Realty";
    backend({ ...MEMBERS, kind: "industry", symbol: null, name: "Realty", as_of: null, unmatched: 0 });
    mount();
    expect(await screen.findByText(/Nifty 500 stocks NSE files under this industry/)).toBeInTheDocument(); // the heading shows at once; the subtitle says the list arrived
    expect(screen.getByRole("heading", { name: "Realty" })).toBeInTheDocument();
  });

  it("says plainly when there is no list for the index", async () => {
    backend({ detail: "no constituent list stored for SENSEX" }, 404);
    mount();
    expect(await screen.findByText("No list of stocks for this one")).toBeInTheDocument();
    expect(screen.getByTestId("index-chart-stub")).toHaveAttribute("data-symbol", "NIFTY IT"); // no list of stocks, but the index still has a chart
    expect(screen.getByRole("heading", { name: "NIFTY IT" })).toBeInTheDocument();
    expect(screen.getByText(/Its chart is below/)).toBeInTheDocument();
  });

  it("shows the chart straight away and the stocks when their list arrives", async () => {
    backend();
    mount();
    expect(screen.getByTestId("index-chart-stub")).toBeInTheDocument(); // not held back by the list of stocks
    expect(await screen.findByText(/The 4 stocks in this index/)).toBeInTheDocument();
    expect(screen.getAllByTestId("index-chart-stub")).toHaveLength(1); // and not rebuilt when the list arrives
  });
});
