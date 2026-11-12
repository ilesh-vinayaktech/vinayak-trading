import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StrategiesPage from "@/app/strategies/page";
import { Providers } from "@/app/providers";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/strategies",
  useSearchParams: () => new URLSearchParams(""),
}));

const OPTIONS = {
  universes: [
    { key: "nifty50", label: "Nifty 50" },
    { key: "nifty200", label: "Nifty 200" },
  ],
  timeframes: [
    { key: "1D", label: "Daily", available: true },
    { key: "1h", label: "1 hour", available: false },
  ],
  params: { trend_sma: [100, 200], entry_rsi: [20, 25, 30], exit_rsi: [55, 60, 65], max_positions: [5, 10, 20] },
};
const S = {
  config_id: "c1",
  name: "Cautious",
  strategy_id: "trend_pullback",
  universe: "nifty50",
  max_instruments: 20,
  timeframe: "1D",
  params: { trend_sma: 200, entry_rsi: 30, exit_rsi: 60, max_positions: 10 },
  in_use: false,
  created_at: "2026-11-11T10:00:00+00:00",
};
const list = (strategies: unknown[]) => ({ label: "UNVALIDATED", options: OPTIONS, strategies });
const who = {
  user: { id: "u1", email: "jane@example.com", name: "Jane Roe", role: "TRADER", permissions: ["strategy:own"], mfa_enabled: true, enrolment_required: false, must_change_password: false },
};

const calls: { method: string; path: string; body: unknown }[] = [];
function backend(table: Record<string, unknown>) {
  calls.length = 0;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    calls.push({ method, path: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const hit = table[`${method} ${url.pathname}`];
    if (hit === undefined) return new Response(JSON.stringify({ detail: "no route" }), { status: 404 });
    const [status, body] = Array.isArray(hit) && typeof hit[0] === "number" ? (hit as [number, unknown]) : [200, hit];
    return new Response(JSON.stringify(body), { status });
  });
}
const mount = () => render(<Providers><StrategiesPage /></Providers>);
const posted = () => calls.filter((c) => c.method === "POST");
const ready = (strategies: unknown[], extra: Record<string, unknown> = {}) => ({ "GET /api/auth/me": who, "GET /api/strategies": list(strategies), ...extra });

beforeEach(() => {
  document.cookie = "csrf=tok";
});
afterEach(() => vi.unstubAllGlobals());

describe("the strategies list", () => {
  it("says it is unvalidated and shows each strategy's index, number of stocks, rules and whether the paper account uses it", async () => {
    backend(ready([S, { ...S, config_id: "c2", name: "Bolder", universe: "nifty200", max_instruments: null, in_use: true }]));
    mount();
    expect(await screen.findByText("Unvalidated research")).toBeInTheDocument();
    expect(await screen.findByText("Nifty 50, top 20 stocks")).toBeInTheDocument();
    expect(screen.getByText("Nifty 200, all stocks")).toBeInTheDocument();
    expect(screen.getAllByText(/Uptrend 200 days · buy RSI < 30 · sell RSI > 60 · up to 10 stocks/).length).toBeGreaterThan(0);
    expect(screen.getByText("In use")).toBeInTheDocument();
    expect(screen.getByText("Not used")).toBeInTheDocument();
    const used = screen.getByText("Bolder").closest("tr") as HTMLElement;
    expect(within(used).queryByRole("button", { name: "Delete" })).not.toBeInTheDocument(); // one in use cannot be deleted
    expect(within(used).queryByRole("button", { name: "Use for paper trading" })).not.toBeInTheDocument();
  });

  it("invites the first strategy when there are none", async () => {
    backend(ready([]));
    mount();
    expect(await screen.findByText("No strategies yet")).toBeInTheDocument();
  });

  it("says so when the list cannot be loaded", async () => {
    backend({ "GET /api/auth/me": who });
    mount();
    expect(await screen.findByText("Could not load your strategies")).toBeInTheDocument();
  });
});

describe("creating and changing", () => {
  it("creates a strategy from the chosen name, index, number of stocks, time frame and rules", async () => {
    backend(ready([], { "POST /api/strategies": { config_id: "new" } }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "New strategy" }));
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "  Quick  " } });
    fireEvent.change(screen.getByLabelText("Index"), { target: { value: "nifty50" } });
    fireEvent.change(screen.getByLabelText("Number of stocks"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("Buy when the 5-day RSI is below"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: "Create strategy" }));
    await waitFor(() =>
      expect(posted()[0]).toMatchObject({
        path: "/api/strategies",
        body: { name: "Quick", universe: "nifty50", max_instruments: 30, timeframe: "1D", params: { trend_sma: 200, entry_rsi: 20, exit_rsi: 60, max_positions: 10 } },
      }),
    );
    expect(await screen.findByText("Strategy created.")).toBeInTheDocument();
  });

  it("needs a name, refuses a nonsense number of stocks, and only offers the daily time frame", async () => {
    backend(ready([]));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "New strategy" }));
    const create = await screen.findByRole("button", { name: "Create strategy" });
    expect(create).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "X" } });
    expect(create).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Number of stocks"), { target: { value: "3" } });
    expect(screen.getByText("Enter a whole number from 5 to 500, or leave it empty.")).toBeInTheDocument();
    expect(create).toBeDisabled();
    const frames = within(screen.getByLabelText("Time frame")).getAllByRole("option");
    expect(frames.map((o) => [o.textContent, (o as HTMLOptionElement).disabled])).toEqual([["Daily", false], ["1 hour (not available yet)", true]]);
    expect(posted()).toHaveLength(0);
  });

  it("shows the server's reason when the name is taken", async () => {
    backend(ready([], { "POST /api/strategies": [400, { detail: "you already have a strategy with that name" }] }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "New strategy" }));
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Cautious" } });
    fireEvent.click(screen.getByRole("button", { name: "Create strategy" }));
    expect(await screen.findByText("you already have a strategy with that name")).toBeInTheDocument();
  });

  it("changes an existing strategy, starting from its current choices, and warns when the paper account uses it", async () => {
    backend(ready([{ ...S, in_use: true }], { "POST /api/strategies/c1": { ok: true } }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Change" }));
    expect(await screen.findByLabelText("Name")).toHaveValue("Cautious");
    expect(screen.getByLabelText("Index")).toHaveValue("nifty50");
    expect(screen.getByLabelText("Number of stocks")).toHaveValue("20");
    expect(screen.getByText(/Your paper account uses this strategy/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Number of stocks"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save strategy" }));
    await waitFor(() => expect(posted()[0]).toMatchObject({ path: "/api/strategies/c1", body: { name: "Cautious", max_instruments: null } }));
    expect(await screen.findByText("Strategy saved.")).toBeInTheDocument();
  });

  it("closes the dialog without saving when cancelled", async () => {
    backend(ready([S]));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Change" }));
    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByLabelText("Name")).not.toBeInTheDocument());
    expect(posted()).toHaveLength(0);
  });
});

describe("using and deleting", () => {
  it("gives the paper account a strategy", async () => {
    backend(ready([S], { "POST /api/strategies/c1/use": { ok: true } }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Use for paper trading" }));
    await waitFor(() => expect(posted()[0]?.path).toBe("/api/strategies/c1/use"));
    expect(await screen.findByText("Your paper account now uses this strategy.")).toBeInTheDocument();
  });

  it("asks before deleting and then deletes", async () => {
    backend(ready([S], { "POST /api/strategies/c1/delete": { ok: true } }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(posted()).toHaveLength(0);
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await waitFor(() => expect(posted()[0]?.path).toBe("/api/strategies/c1/delete"));
    expect(await screen.findByText("Strategy deleted.")).toBeInTheDocument();
  });

  it("shows the server's reason when giving the strategy fails", async () => {
    backend(ready([S], { "POST /api/strategies/c1/use": [400, { detail: "no paper account yet" }] }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Use for paper trading" }));
    expect(await screen.findByText("no paper account yet")).toBeInTheDocument();
  });
});
