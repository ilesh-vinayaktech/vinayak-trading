import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HoldCell, HoldText, useHoldSignal } from "@/components/market/HoldCell";
import { HoldSignalPanel } from "@/components/market/HoldSignalPanel";
import { holdSignalLatestSchema, holdSignalTodaySchema } from "@/lib/schemas";

const load = (n: string) => JSON.parse(readFileSync(join(__dirname, `contract/${n}.json`), "utf8"));
const TODAY = holdSignalTodaySchema.parse(load("market_hold_signal_today")); // a real response: it must parse with the schema the panel uses
const EMPTY = holdSignalTodaySchema.parse(load("market_hold_signal_today_empty"));
const LATEST = holdSignalLatestSchema.parse(load("market_hold_signal_latest"));
const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
afterEach(() => vi.unstubAllGlobals());

describe("HoldSignalPanel", () => {
  it("lists what to buy and what to sell with the day, the counts and the honest evidence", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(TODAY), { status: 200 }));
    wrap(<HoldSignalPanel />);
    const buy = TODAY.buy[0]!;
    const link = await screen.findByRole("link", { name: buy.symbol });
    expect(link).toHaveAttribute("href", `/data/instruments?id=${buy.instrument_id}`);
    expect(screen.getByTestId("hold-summary")).toHaveTextContent(`As of ${TODAY.day}`);
    expect(screen.getByTestId("hold-summary")).toHaveTextContent(`${TODAY.counts.buy} to buy at the next open, ${TODAY.counts.sell} to sell`);
    expect(screen.getByText(/Buy at the next open, best chance first/)).toBeInTheDocument();
    expect(screen.getByText(/Sell at the next open \(held and ranked 20 or lower\), weakest first/)).toBeInTheDocument();
    expect(screen.getByText(/\+0\.29% per trade over the market after real costs/)).toBeInTheDocument();
    expect(screen.getByText(/not confirmatory/)).toBeInTheDocument(); // the 2025 to 2026 read is described as what it is
    expect(screen.getByText(/not advice and not an order/)).toBeInTheDocument();
    expect(screen.getByText(/at most 10 positions/)).toBeInTheDocument();
  });

  it("says nothing is scored yet when the signal has never been made", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(EMPTY), { status: 200 }));
    wrap(<HoldSignalPanel />);
    expect(await screen.findByText(/No stock has been scored yet/)).toBeInTheDocument();
    expect(screen.queryByTestId("hold-summary")).not.toBeInTheDocument();
  });

  it("shows only as many buys as the rule holds and says how many more there are", async () => {
    const many = { ...TODAY, max_positions: 1, counts: { ...TODAY.counts, buy: 3 }, buy: [TODAY.buy[0]!, { ...TODAY.buy[0]!, instrument_id: 99, symbol: "TWO" }, { ...TODAY.buy[0]!, instrument_id: 98, symbol: "THREE" }] };
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(many), { status: 200 }));
    wrap(<HoldSignalPanel />);
    await screen.findByRole("link", { name: TODAY.buy[0]!.symbol });
    expect(screen.queryByRole("link", { name: "TWO" })).not.toBeInTheDocument();
    expect(screen.getByText(/1 of 3 shown: the rule holds at most 1 at a time/)).toBeInTheDocument();
  });

  it("reports a failed load instead of an empty list", async () => {
    vi.stubGlobal("fetch", async () => new Response("{}", { status: 500 }));
    wrap(<HoldSignalPanel />);
    expect(await screen.findByText("Could not load the hold signal")).toBeInTheDocument();
  });
});

describe("HoldText", () => {
  const base = { day: "2026-11-18", prob: 0.55, rank_pct: 93.2, in_position: true, entry_day: "2026-11-18" };
  it("shows BUY and SELL in colour with the rank and a plain title", () => {
    render(<><HoldText signal={{ ...base, action: "BUY" }} /><HoldText signal={{ ...base, action: "SELL", rank_pct: 12, in_position: false, entry_day: null }} /></>);
    expect(screen.getByText("BUY")).toHaveClass("text-emerald-700");
    expect(screen.getByText("BUY")).toHaveAttribute("title", expect.stringContaining("Buy at the next open"));
    expect(screen.getByText("SELL")).toHaveAttribute("title", expect.stringContaining("Sell at the next open"));
    expect(screen.getByText("r93")).toBeInTheDocument();
  });

  it("says since when a stock is held, and 'weak' for an unheld stock at rank 20 or lower, and a dash for the rest", () => {
    render(<><HoldText signal={{ ...base, action: "HOLD", rank_pct: 61.5, entry_day: "2026-11-06" }} /><HoldText signal={{ ...base, action: "NONE", rank_pct: 8, in_position: false, entry_day: null }} /><HoldText signal={{ ...base, action: "NONE", rank_pct: 50, in_position: false, entry_day: null }} /></>);
    expect(screen.getByText("HOLD")).toHaveAttribute("title", expect.stringContaining("Held since 2026-11-06"));
    expect(screen.getByText("weak")).toHaveClass("text-red-700");
    expect(screen.getByText("weak")).toHaveAttribute("title", expect.stringContaining("would sell"));
    expect(screen.getByText("–")).toHaveAttribute("title", expect.stringContaining("a buy needs rank 90 or more"));
  });

  it("shows a dash with the reason for a stock outside the ranked universe", () => {
    render(<HoldText signal={undefined} />);
    expect(screen.getByText("–")).toHaveAttribute("title", expect.stringContaining("Not scored"));
  });
});

describe("useHoldSignal and HoldCell", () => {
  function Probe({ ids }: { ids: number[] }) {
    const hold = useHoldSignal(ids);
    return <table><tbody><tr>{ids.map((i, k) => <HoldCell key={k} signal={hold[String(i)]} />)}</tr></tbody></table>;
  }
  it("asks once for the whole list and puts each stock's call in its cell; an unlisted stock gets a dash", async () => {
    const asked: string[] = [];
    vi.stubGlobal("fetch", async (url: string) => {
      asked.push(String(url));
      return new Response(JSON.stringify(LATEST), { status: 200 });
    });
    const id = Number(Object.keys(LATEST.items)[0]);
    const first = LATEST.items[String(id)]!;
    wrap(<Probe ids={[id, id, 424242]} />);
    expect(await screen.findAllByText(first.action)).toHaveLength(2); // the same stock listed twice shows its call twice
    expect(screen.getByText("–")).toHaveAttribute("title", expect.stringContaining("Not scored")); // the stock the server did not list
    expect(asked.filter((u) => u.includes("hold-signal/latest"))).toHaveLength(1);
    expect(asked[0]).toContain(`ids=${id},424242`); // sorted and without duplicates
  });
});
