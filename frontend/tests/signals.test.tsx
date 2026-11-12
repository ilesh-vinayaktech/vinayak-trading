import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import { SignalsPanel, type Mark } from "@/components/strategies/SignalsPanel";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/data/instruments",
  useSearchParams: () => new URLSearchParams(""),
}));

const OPTIONS = {
  universes: [{ key: "nifty200", label: "Nifty 200" }],
  timeframes: [{ key: "1D", label: "Daily", available: true }],
  params: { trend_sma: [100, 200], entry_rsi: [20, 25, 30], exit_rsi: [55, 60, 65], max_positions: [5, 10, 20] },
};
const PARAMS = { trend_sma: 200, entry_rsi: 30, exit_rsi: 60, max_positions: 10 };
const strategy = (id: string, name: string) => ({ config_id: id, name, strategy_id: "trend_pullback", universe: "nifty200", max_instruments: null, timeframe: "1D", params: PARAMS, in_use: false, created_at: "2026-11-11T10:00:00+00:00" });
const LIST = { label: "UNVALIDATED", options: OPTIONS, strategies: [strategy("c1", "Cautious"), strategy("c2", "Bolder")] };
const day = (d: string, over: Record<string, unknown> = {}) => ({ day: d, close: "150.5", sma: "140", rsi: "22.5", ready: true, action: null, reason: null, holding_after: false, fill_day: null, fill_price: null, ...over });
const SIGNALS = {
  label: "UNVALIDATED",
  strategy: "Cautious",
  params: PARAMS,
  notes: ["Decisions only: this is not a backtest and shows no profit or loss."],
  summary: { buys: 1, sells: 1 },
  days: [
    day("2026-01-02", { ready: false, sma: null, rsi: null }),
    day("2026-01-05", { action: "BUY", reason: "oversold in an uptrend", holding_after: true, fill_day: "2026-01-06", fill_price: "151.25" }),
    day("2026-01-20", { action: "SELL", reason: "rsi_above_exit", close: "170", rsi: "71" }),
  ],
};
const INSTRUMENT = { id: 7, symbol: "TCS", isin: null, name: "TCS", status: "ACTIVE", listed_on: null, delisted_on: null };
const who = { user: { id: "u1", email: "j@example.com", name: "Jane", role: "TRADER", permissions: ["strategy:own"], mfa_enabled: true, enrolment_required: false, must_change_password: false } };

const calls: { method: string; path: string; query: string }[] = [];
function backend(table: Record<string, unknown>) {
  calls.length = 0;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const method = init?.method ?? "GET";
    calls.push({ method, path: url.pathname, query: url.search });
    const hit = table[`${method} ${url.pathname}`];
    if (hit === undefined) return new Response(JSON.stringify({ detail: "no route" }), { status: 404 });
    const [status, body] = Array.isArray(hit) && typeof hit[0] === "number" ? (hit as [number, unknown]) : [200, hit];
    return new Response(JSON.stringify(body), { status });
  });
}
const marks: Mark[][] = [];
const mount = (instrument: typeof INSTRUMENT | null = INSTRUMENT) =>
  render(
    <Providers>
      <SignalsPanel instrument={instrument} start="2026-01-01" end="2026-06-30" onMarks={(m) => marks.push(m)} />
    </Providers>,
  );
const ready = (extra: Record<string, unknown> = {}) => ({ "GET /api/auth/me": who, "GET /api/strategies": LIST, "GET /api/strategies/c1/signals": SIGNALS, ...extra });
const enabledRun = async () => {
  const b = await screen.findByRole("button", { name: "Run strategy" });
  await waitFor(() => expect(b).toBeEnabled()); // the list of strategies has loaded
  return b;
};
const signalCalls = () => calls.filter((c) => c.path.endsWith("/signals"));

beforeEach(() => {
  document.cookie = "csrf=tok";
  marks.length = 0;
});
afterEach(() => vi.unstubAllGlobals());

describe("the strategy signals panel", () => {
  it("offers the saved strategies and starts the replay on the chart's first day", async () => {
    backend(ready());
    mount();
    const pick = await screen.findByLabelText("Strategy");
    await waitFor(() => expect(pick).toHaveValue("c1"));
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["Cautious", "Bolder"]);
    expect(screen.getByLabelText("Replay from")).toHaveValue("2026-01-01");
    expect(screen.getByLabelText("To")).toHaveValue("2026-06-30");
    expect(signalCalls()).toHaveLength(0); // nothing runs until asked
  });

  it("runs the chosen strategy on the open stock and lists the buy and sell decisions with their next-open fills", async () => {
    backend(ready());
    mount();
    fireEvent.click(await enabledRun());
    expect(await screen.findByText(/1 buy and 1 sell signals between 2026-01-01 and 2026-06-30/)).toBeInTheDocument();
    expect(screen.getByText(/1 early days had too little history/)).toBeInTheDocument();
    expect(screen.getByText("oversold in an uptrend")).toBeInTheDocument();
    expect(screen.getByText("Recovered (RSI above the sell level)")).toBeInTheDocument();
    expect(screen.getByText("151.25 on 2026-01-06")).toBeInTheDocument();
    expect(screen.getByText("not yet")).toBeInTheDocument(); // the last decision has no next session
    expect(screen.getByText(/not a backtest and shows no profit or loss/)).toBeInTheDocument();
    expect(signalCalls()[0]?.query).toContain("instrument_id=7");
    expect(signalCalls()[0]?.query).toContain("holding=false");
    await waitFor(() => expect(marks.at(-1)).toEqual([{ day: "2026-01-05", action: "BUY" }, { day: "2026-01-20", action: "SELL" }]));
  });

  it("replays from a chosen day, for a stock already held, with a different strategy", async () => {
    backend(ready({ "GET /api/strategies/c2/signals": { ...SIGNALS, strategy: "Bolder" } }));
    mount();
    fireEvent.change(await screen.findByLabelText("Strategy"), { target: { value: "c2" } });
    fireEvent.change(screen.getByLabelText("Replay from"), { target: { value: "2026-03-02" } });
    fireEvent.change(screen.getByLabelText("To"), { target: { value: "2026-04-01" } });
    fireEvent.click(screen.getByLabelText("Already holding it on that day"));
    fireEvent.click(await enabledRun());
    expect(await screen.findByText("Bolder")).toBeInTheDocument();
    const q = signalCalls()[0]?.query ?? "";
    expect(q).toContain("start=2026-03-02");
    expect(q).toContain("end=2026-04-01");
    expect(q).toContain("holding=true");
  });

  it("will not run without a stock", async () => {
    backend(ready());
    mount(null);
    expect(await screen.findByRole("button", { name: "Run strategy" })).toBeDisabled();
  });

  it("will not run with the dates the wrong way round", async () => {
    backend(ready());
    mount();
    const run = await enabledRun();
    fireEvent.change(screen.getByLabelText("Replay from"), { target: { value: "2026-12-01" } });
    expect(run).toBeDisabled();
    fireEvent.submit(run.closest("form") as HTMLFormElement);
    expect(signalCalls()).toHaveLength(0);
  });

  it("says when the strategy would not have traded", async () => {
    backend(ready({ "GET /api/strategies/c1/signals": { ...SIGNALS, summary: { buys: 0, sells: 0 }, days: [day("2026-01-05")] } }));
    mount();
    fireEvent.click(await enabledRun());
    expect(await screen.findByText("No signals")).toBeInTheDocument();
    await waitFor(() => expect(marks.at(-1)).toEqual([]));
  });

  it("shows the server's reason when the run fails, and a general one when it is not a server answer", async () => {
    backend(ready({ "GET /api/strategies/c1/signals": [404, { detail: "no instrument 7" }] }));
    mount();
    fireEvent.click(await enabledRun());
    expect(await screen.findByText("no instrument 7")).toBeInTheDocument();
  });

  it("points to the Strategies page when there are none yet", async () => {
    backend(ready({ "GET /api/strategies": { ...LIST, strategies: [] } }));
    mount();
    expect(await screen.findByText(/You have no saved strategies yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run strategy" })).not.toBeInTheDocument();
  });
});
