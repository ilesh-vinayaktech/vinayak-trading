import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import PaperPage from "@/app/paper/page";
import { Providers } from "@/app/providers";
import { fmtMoney, fmtRelative } from "@/lib/formatting";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/paper",
  useSearchParams: () => new URLSearchParams(""),
}));

const OPTIONS = {
  universes: [
    { key: "nifty50", label: "Nifty 50" },
    { key: "nifty100", label: "Nifty 100" },
    { key: "nifty200", label: "Nifty 200" },
    { key: "midcap100", label: "Nifty Midcap 100" },
    { key: "nifty500", label: "Nifty 500" },
  ],
  timeframes: [
    { key: "1D", label: "Daily", available: true },
    { key: "1h", label: "1 hour", available: false },
    { key: "15m", label: "15 minutes", available: false },
  ],
  params: {
    trend_sma: [100, 200],
    entry_rsi: [20, 25, 30],
    exit_rsi: [55, 60, 65],
    max_positions: [5, 10, 20],
  },
};
const ACCOUNT = {
  strategy_id: "trend_pullback",
  enabled: true,
  mode: "PAPER",
  initial_cash: "1000000",
  started_on: "2026-11-02",
  attention: null,
  universe: "nifty200",
  max_instruments: null,
  timeframe: "1D",
  params: { trend_sma: 200, entry_rsi: 25, exit_rsi: 60, max_positions: 10 },
  screen: null,
  definition: null,
};
const account = (over: Record<string, unknown> | null = {}) => ({
  label: "UNVALIDATED",
  options: OPTIONS,
  account: over === null ? null : { ...ACCOUNT, ...over },
});
const SUMMARY = {
  equity: "1234567.5",
  cash: "234567.5",
  invested: "1000000",
  pnl: {
    realized: "0",
    unrealized: "-1500.25",
    fees: "120.5",
    net: "-1620.75",
  },
  positions: [
    {
      instrument_id: 7,
      symbol: "RELIANCE",
      qty: "100",
      avg_cost: "2850.5",
      last_price: "2900",
      value: "290000",
      unrealized: "4950",
      upcoming: [],
    },
  ],
  equity_curve: [
    { day: "2026-11-02", equity: "1000000" },
    { day: "2026-11-03", equity: "1010000" },
    { day: "2026-11-04", equity: "1234567.5" },
  ],
  pending_orders: 2,
};
const order = (over: Record<string, unknown>) => ({
  order_id: "o1",
  instrument_id: 11,
  symbol: "TCS",
  side: "BUY",
  qty: "10",
  ref_price: "3500",
  reason: "entry: oversold in an uptrend",
  status: "PENDING",
  decision_day: "2026-11-11",
  created_at: "2026-11-11T14:00:00+00:00",
  expires_at: "2026-11-12T10:00:00+00:00",
  fill_price: null,
  fill_commission: null,
  fill_day: null,
  failure: null,
  order_type: "MARKET",
  limit_price: null,
  tick_size: "0.05",
  upcoming: [],
  ...over,
});
const COMING = (
  kind: string,
  ex_date: string,
  amount: string | null,
  subject: string,
) => ({ ex_date, kind, status: "ok", num: null, den: null, amount, subject });
const ORDERS = {
  orders: [
    order({}),
    order({
      order_id: "o2",
      symbol: "INFY",
      side: "SELL",
      qty: "5",
      reason: "exit: below_trend",
    }),
    order({
      order_id: "o3",
      symbol: "SBIN",
      status: "FILLED",
      fill_price: "801.25",
      fill_day: "2026-11-12",
    }),
    order({
      order_id: "o4",
      symbol: "ITC",
      status: "FAILED",
      failure: "not enough cash for this order",
    }),
    order({ order_id: "o5", symbol: "HDFCBANK", status: "REJECTED" }),
    order({ order_id: "o6", symbol: "LT", status: "EXPIRED" }),
    order({ order_id: "o7", symbol: "WIPRO", status: "APPROVED" }),
  ],
};
const RUNS = {
  runs: [
    {
      decision_day: "2026-11-11",
      status: "PROPOSED",
      reason: null,
      orders: 2,
      universe: "nifty200",
      strategy_version: "1",
      created_at: "2026-11-11T14:00:00+00:00",
    },
    {
      decision_day: "2026-11-10",
      status: "ERROR",
      reason: "no nifty200_list in the lake",
      orders: 0,
      universe: null,
      strategy_version: "-",
      created_at: "2026-11-10T14:00:00+00:00",
    },
    {
      decision_day: "2026-11-09",
      status: "NO_CHANGE",
      reason: "holdings already match the targets",
      orders: 0,
      universe: "nifty200",
      strategy_version: "1",
      created_at: "2026-11-09T14:00:00+00:00",
    },
    {
      decision_day: "2026-11-06",
      status: "SKIPPED",
      reason: "the account is switched off",
      orders: 0,
      universe: null,
      strategy_version: "-",
      created_at: "2026-11-06T14:00:00+00:00",
    },
  ],
};
const who = (perms = ["strategy:own"]) => ({
  user: {
    id: "u1",
    email: "jane@example.com",
    name: "Jane Roe",
    role: "TRADER",
    permissions: perms,
    mfa_enabled: true,
    enrolment_required: false,
    must_change_password: false,
  },
});

const calls: { method: string; path: string; query: string; body: unknown }[] =
  [];
function backend(table: Record<string, unknown>) {
  calls.length = 0;
  vi.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input));
      const method = init?.method ?? "GET";
      calls.push({
        method,
        path: url.pathname,
        query: url.search,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      const hit = table[`${method} ${url.pathname}`];
      if (hit === undefined)
        return new Response(JSON.stringify({ detail: "no route" }), {
          status: 404,
        });
      const [status, body] =
        Array.isArray(hit) && typeof hit[0] === "number"
          ? (hit as [number, unknown])
          : [200, hit];
      return new Response(JSON.stringify(body), { status });
    },
  );
}
const mount = () =>
  render(
    <Providers>
      <PaperPage />
    </Providers>,
  );
const ready = (
  over: Record<string, unknown> | null = {},
  extra: Record<string, unknown> = {},
) => ({
  "GET /api/auth/me": who(),
  "GET /api/paper/account": account(over),
  "GET /api/paper/summary": SUMMARY,
  "GET /api/paper/orders": ORDERS,
  "GET /api/paper/runs": RUNS,
  "GET /api/strategies": strategies([]),
  "GET /api/paper/definitions": { label: "UNVALIDATED", definitions: [] },
  ...extra,
});
const STRATEGY = {
  config_id: "c1",
  name: "Cautious",
  strategy_id: "trend_pullback",
  universe: "nifty100",
  max_instruments: 50,
  timeframe: "1D",
  params: { trend_sma: 200, entry_rsi: 30, exit_rsi: 60, max_positions: 10 },
  screen: null,
  in_use: false,
  stage: "RESEARCH",
  created_at: "2026-11-11T10:00:00+00:00",
};
const strategies = (list: Record<string, unknown>[]) => ({
  label: "UNVALIDATED",
  options: OPTIONS,
  strategies: list,
});
const posted = () => calls.filter((c) => c.method === "POST");

beforeEach(() => {
  document.cookie = "csrf=tok";
});
afterEach(() => vi.unstubAllGlobals());

describe("one page for both venues", () => {
  it("names the venue in the title and says what happens to an approved order", async () => {
    backend(ready({ mode: "LIVE" }));
    mount();
    expect(await screen.findByRole("heading", { name: "Trading (live)" })).toBeInTheDocument();
    expect(screen.getByText(/Real money\. You approve every order/)).toBeInTheDocument();
  });
  it("keeps the paper wording for a paper account", async () => {
    backend(ready({ mode: "PAPER" }));
    mount();
    expect(await screen.findByRole("heading", { name: "Trading (paper)" })).toBeInTheDocument();
    expect(screen.getByText(/nothing here places a real one/)).toBeInTheDocument();
  });
});

const LIVE_STATUS = {
  account: true,
  open: false,
  problems: ["ALGO_LIVE=1 is not set", "there is no valid broker session"],
  stage: "RESEARCH",
  process: null,
};
const liveTab = () => screen.findByRole("tab", { name: "Live" });

describe("the live account on the same page", () => {
  it("asks for the live account only when Live is chosen, and paper requests carry no mode", async () => {
    backend(ready({}, { "GET /api/paper/live-status": LIVE_STATUS }));
    mount();
    await screen.findByRole("heading", { name: "Trading (paper)" });
    expect(calls.filter((c) => c.path === "/api/paper/account").every((c) => c.query === "")).toBe(true);
    fireEvent.click(await liveTab());
    await waitFor(() => expect(calls.some((c) => c.path === "/api/paper/account" && c.query === "?mode=live")).toBe(true));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/paper/summary" && c.query === "?mode=live")).toBe(true));
  });
  it("says why live cannot run and whether the live process is alive", async () => {
    backend(ready({ mode: "LIVE" }, { "GET /api/paper/live-status": LIVE_STATUS }));
    mount();
    fireEvent.click(await liveTab());
    expect(await screen.findByText("Live cannot run yet")).toBeInTheDocument();
    expect(screen.getByText("Live process has not reported")).toBeInTheDocument();
    expect(screen.getByText("ALGO_LIVE=1 is not set")).toBeInTheDocument();
    expect(screen.getByText("there is no valid broker session")).toBeInTheDocument();
    expect(screen.getByText("Real money")).toBeInTheDocument();
  });
  it("shows a running live process and an open gate", async () => {
    const open = { ...LIVE_STATUS, open: true, problems: [], stage: "LIVE", process: { state: "RUNNING", silent_s: 12, detail: "" } };
    backend(ready({ mode: "LIVE" }, { "GET /api/paper/live-status": open }));
    mount();
    fireEvent.click(await liveTab());
    expect(await screen.findByText("Live can run")).toBeInTheDocument();
    expect(screen.getByText("Live process running")).toBeInTheDocument();
  });
  it("starts a live account with its capital and a LIVE-stage strategy, and sends the mode", async () => {
    const live = { ...STRATEGY, stage: "LIVE" };
    backend(
      ready(null, {
        "GET /api/paper/live-status": { ...LIVE_STATUS, account: false },
        "GET /api/strategies": strategies([live, { ...STRATEGY, config_id: "c2", name: "Research only", stage: "RESEARCH" }]),
        "POST /api/paper/account": { ok: true },
        "POST /api/strategies/c1/use": { ok: true },
      }),
    );
    mount();
    fireEvent.click(await liveTab());
    expect(await screen.findByText(/no live account yet/)).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Research only" })).not.toBeInTheDocument(); // only what was promoted
    fireEvent.change(await screen.findByLabelText("Capital (₹)"), { target: { value: "50000" } });
    fireEvent.click(screen.getByRole("button", { name: "Start live trading" }));
    await waitFor(() => expect(posted().find((c) => c.path === "/api/paper/account")?.body).toMatchObject({ initial_cash: "50000", mode: "live" }));
    await waitFor(() => expect(posted().some((c) => c.path === "/api/strategies/c1/use" && c.query === "?mode=live")).toBe(true));
  });
  it("will not start a live account without a strategy in the LIVE stage", async () => {
    backend(ready(null, { "GET /api/paper/live-status": { ...LIVE_STATUS, account: false }, "GET /api/strategies": strategies([{ ...STRATEGY, stage: "RESEARCH" }]) }));
    mount();
    fireEvent.click(await liveTab());
    fireEvent.click(await screen.findByRole("button", { name: "Start live trading" }));
    expect(await screen.findByText("Pick a strategy that has been promoted to the LIVE stage first.")).toBeInTheDocument();
    expect(posted()).toHaveLength(0);
  });
});

describe("money formatting", () => {
  it("groups the Indian way from the decimal string, without touching the digits", () => {
    expect(fmtMoney("1234567.5")).toBe("12,34,567.50");
    expect(fmtMoney("0")).toBe("0.00");
    expect(fmtMoney("999")).toBe("999.00");
    expect(fmtMoney("1000")).toBe("1,000.00");
    expect(fmtMoney("-1500.256")).toBe("-1,500.25");
    expect(fmtMoney("12345678901234567890.12")).toBe(
      "1,23,45,67,89,01,23,45,67,890.12",
    );
    expect(fmtMoney("100", 0)).toBe("100");
    expect(fmtMoney("not money")).toBe("not money");
  });
});

describe("relative time", () => {
  const now = Date.parse("2026-11-11T12:00:00Z");
  it("reads the past as ago, the future as in, and falls back to the date a month or more away", () => {
    expect(fmtRelative("2026-11-11T11:59:50Z", now)).toBe("just now");
    expect(fmtRelative("2026-11-11T11:50:00Z", now)).toBe("10 min ago");
    expect(fmtRelative("2026-11-11T09:00:00Z", now)).toBe("3 h ago");
    expect(fmtRelative("2026-11-08T12:00:00Z", now)).toBe("3 d ago");
    expect(fmtRelative("2026-11-11T12:00:30Z", now)).toBe("just now");
    expect(fmtRelative("2026-11-11T12:10:00Z", now)).toBe("in 10 min");
    expect(fmtRelative("2026-11-12T08:00:00Z", now)).toBe("in 20 h");
    expect(fmtRelative("2026-11-14T12:00:00Z", now)).toBe("in 3 d");
    expect(fmtRelative("2027-03-01T00:00:00Z", now)).toBe("2027-03-01");
    expect(fmtRelative("2026-01-01T00:00:00Z", now)).toBe("2026-01-01");
    expect(fmtRelative("garbage", now)).toBe("garbage");
  });
});

describe("strategies from research", () => {
  const defs = (state: string) => ({ label: "UNVALIDATED", definitions: [{ experiment_id: 5, strategy_id: "MOMENTUM_12M_M", version: 1, name: "MOMENTUM_12M_M v1 test", state }] });

  it("says a strategy that passed its development test is waiting for the global holdout and offers no start", async () => {
    backend(ready({}, { "GET /api/paper/definitions": defs("awaiting_holdout") }));
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Settings/ }));
    const row = await screen.findByTestId("research-strategy");
    expect(row).toHaveTextContent("MOMENTUM_12M_M");
    expect(row).toHaveTextContent("Waiting for the global holdout");
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
  });

  it("says one that failed the global holdout cannot be paper traded", async () => {
    backend(ready({}, { "GET /api/paper/definitions": defs("failed_holdout") }));
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Settings/ }));
    const row = await screen.findByTestId("research-strategy");
    expect(row).toHaveTextContent("cannot be paper traded");
    expect(within(row).queryByRole("button")).not.toBeInTheDocument();
  });

  it("tells anyone but the owner that the state of researched strategies is not for them, instead of saying none passed", async () => {
    backend(ready({}, { "GET /api/paper/definitions": [403, { detail: "forbidden" }] }));
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Settings/ }));
    expect(await screen.findByText(/Only the owner can see/)).toBeInTheDocument();
    expect(screen.queryByTestId("research-strategy")).not.toBeInTheDocument();
  });

  it("starts one that passed the global holdout on the account", async () => {
    backend(ready({}, { "GET /api/paper/definitions": defs("ready"), "POST /api/paper/definitions/5/start": { ok: true } }));
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Settings/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Paper trade this" }));
    await waitFor(() => expect(posted().map((c) => c.path)).toEqual(["/api/paper/definitions/5/start"]));
    expect(await screen.findByText("Strategy changed. It applies from the next daily decision.")).toBeInTheDocument();
  });

  it("shows which research strategy the account follows and does not offer it again", async () => {
    backend(ready({ definition: "MOMENTUM_12M_M v1 test" }, { "GET /api/paper/definitions": defs("ready") }));
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Settings/ }));
    expect(await screen.findByRole("button", { name: "In use" })).toBeDisabled();
    expect(screen.getByText(/Strategy definition MOMENTUM_12M_M v1 test/)).toBeInTheDocument();
  });

  it("cannot start before there is an account", async () => {
    backend(ready(null, { "GET /api/paper/definitions": defs("ready") }));
    mount();
    expect(await screen.findByRole("button", { name: "Paper trade this" })).toBeDisabled();
  });
});

describe("the validation banner", () => {
  it("says the strategy passed the holdout when the account follows one that did, and warns otherwise", async () => {
    backend(ready({ definition: "MOMENTUM_12M_M v1 test" }));
    const { unmount } = mount();
    expect(await screen.findByText("Passed the holdout")).toBeInTheDocument();
    expect(screen.getByText(/MOMENTUM_12M_M v1 test passed development and the 2025-2026 holdout/)).toBeInTheDocument();
    expect(screen.queryByText("Unvalidated research")).not.toBeInTheDocument();
    unmount();
    backend(ready({ definition: null }));
    mount();
    expect(await screen.findByText("Unvalidated research")).toBeInTheDocument();
  });
});

describe("starting a paper account", () => {
  it("explains it is unvalidated and, with no saved strategy, starts with the standard settings", async () => {
    backend(ready(null, { "POST /api/paper/account": { ok: true } }));
    mount();
    expect(await screen.findByText("Unvalidated research")).toBeInTheDocument();
    expect(
      await screen.findByText("You have no saved strategies yet."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Create a strategy" }),
    ).toHaveAttribute("href", "/strategies");
    fireEvent.change(screen.getByLabelText("Starting cash (₹)"), {
      target: { value: "500000" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Start paper trading" }),
    );
    await waitFor(() =>
      expect(posted()[0]?.body).toEqual({
        initial_cash: "500000",
        universe: "nifty200",
        max_instruments: null,
        timeframe: "1D",
        params: {
          trend_sma: 200,
          entry_rsi: 25,
          exit_rsi: 60,
          max_positions: 10,
        },
      }),
    );
    expect(posted()).toHaveLength(1);
    expect(
      await screen.findByText("Paper account started."),
    ).toBeInTheDocument();
  });

  it("starts with the chosen saved strategy's settings and links the account to it", async () => {
    backend(
      ready(null, {
        "GET /api/strategies": strategies([
          STRATEGY,
          { ...STRATEGY, config_id: "c2", name: "Bolder", universe: "nifty50" },
        ]),
        "POST /api/paper/account": { ok: true },
        "POST /api/strategies/c2/use": { ok: true },
      }),
    );
    mount();
    const pick = await screen.findByLabelText("Strategy");
    await waitFor(() => expect(pick).toHaveValue("c1"));
    fireEvent.change(pick, { target: { value: "c2" } });
    fireEvent.click(
      screen.getByRole("button", { name: "Start paper trading" }),
    );
    await waitFor(() => expect(posted()).toHaveLength(2));
    expect(posted()[0]?.body).toMatchObject({
      universe: "nifty50",
      max_instruments: 50,
    });
    expect(posted()[1]?.path).toBe("/api/strategies/c2/use");
  });

  it("starts a screener strategy's account on the standard settings and then puts the strategy on it", async () => {
    const screener = {
      ...STRATEGY,
      config_id: "c3",
      name: "Dip buyer",
      strategy_id: "screener",
      universe: "segments",
      max_instruments: null,
      params: { max_positions: 10 },
      screen: {
        screen: {
          conditions: [{ field: "rsi_14", op: "lte", value: "40" }],
          match: "all",
          sort: "rsi_14",
          descending: false,
        },
        segments: ["large", "mid"],
      },
    };
    backend(
      ready(null, {
        "GET /api/strategies": strategies([screener]),
        "POST /api/paper/account": { ok: true },
        "POST /api/strategies/c3/use": { ok: true },
      }),
    );
    mount();
    await waitFor(() =>
      expect(screen.getByLabelText("Strategy")).toHaveValue("c3"),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Start paper trading" }),
    );
    await waitFor(() => expect(posted()).toHaveLength(2));
    expect(posted()[0]?.body).toMatchObject({
      universe: "nifty200",
      max_instruments: null,
      params: { trend_sma: 200, max_positions: 10 },
    });
    expect(posted()[1]?.path).toBe("/api/strategies/c3/use");
  });

  it("shows the server's reason when starting is refused", async () => {
    backend(
      ready(null, {
        "POST /api/paper/account": [
          400,
          { detail: "this user already has a paper account" },
        ],
      }),
    );
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Start paper trading" }),
    );
    expect(
      await screen.findByText("this user already has a paper account"),
    ).toBeInTheDocument();
  });
});

describe("the account overview", () => {
  it("shows value, cash, profit and the positions with money exactly as the API sent it", async () => {
    backend(ready());
    mount();
    expect(await screen.findByText("₹12,34,567.50")).toBeInTheDocument();
    expect(screen.getByText("₹2,34,567.50 in cash")).toBeInTheDocument();
    expect(screen.getByText("-₹1,620.75")).toBeInTheDocument();
    const table = within(screen.getByRole("table", { name: "Positions" }));
    expect(table.getByText("RELIANCE")).toBeInTheDocument();
    expect(table.getByText("₹2,90,000.00")).toBeInTheDocument();
    expect(table.getByText("₹4,950.00")).toBeInTheDocument();
    expect(
      screen.getByRole("img", {
        name: "Account value from 2026-11-02 to 2026-11-04",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Orders/ })).toHaveTextContent("2");
  });

  it("says what is missing for a brand new account", async () => {
    backend(
      ready(
        {},
        {
          "GET /api/paper/summary": {
            ...SUMMARY,
            positions: [],
            equity_curve: [],
            pending_orders: 0,
            pnl: { realized: "0", unrealized: "0", fees: "0", net: "0" },
          },
        },
      ),
    );
    mount();
    expect(await screen.findByText("No positions yet")).toBeInTheDocument();
    expect(
      screen.getByText("The value chart appears after the second trading day."),
    ).toBeInTheDocument();
    expect(screen.getByText("Nothing waiting")).toBeInTheDocument();
  });

  it("warns when the account is paused or switched off", async () => {
    backend(
      ready({
        attention: "rights (ex 2026-11-05, instrument 7) needs review",
        enabled: false,
      }),
    );
    mount();
    expect(await screen.findByText("Paused")).toBeInTheDocument();
    expect(screen.getByText(/rights \(ex 2026-11-05/)).toBeInTheDocument();
    expect(screen.getByText("Trading is off")).toBeInTheDocument();
  });
});

describe("announced actions coming up", () => {
  it("warns on a holding whose stock has an ex-date within days, and on an order waiting for an answer", async () => {
    const dividend = COMING(
      "dividend",
      "2026-11-20",
      "7",
      "Interim Dividend - Rs 7 Per Share",
    );
    const split = COMING("split", "2026-11-15", null, "Face Value Split");
    const held = {
      ...SUMMARY,
      positions: [{ ...SUMMARY.positions[0], upcoming: [dividend] }],
    };
    const orders = {
      orders: [
        order({ upcoming: [split] }),
        order({ order_id: "o2", symbol: "INFY" }),
      ],
    };
    backend(
      ready(
        {},
        { "GET /api/paper/summary": held, "GET /api/paper/orders": orders },
      ),
    );
    mount();
    const positions = within(
      await screen.findByRole("table", { name: "Positions" }),
    );
    expect(
      positions.getByText(/Ex-date 2026-11-20: dividend ₹7/),
    ).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("tab", { name: /Orders/ }));
    const waiting = within(
      await screen.findByRole("table", {
        name: "Orders waiting for your answer",
      }),
    );
    expect(
      await waiting.findByText(/Ex-date 2026-11-15: split/),
    ).toBeInTheDocument();
    const infy = waiting.getByText("INFY").closest("tr") as HTMLElement;
    expect(within(infy).queryByText(/Ex-date/)).not.toBeInTheDocument(); // nothing coming for it: no noise
  });
});

describe("answering orders", () => {
  const open = async () => {
    backend(
      ready(
        {},
        {
          "POST /api/paper/orders/o1/approve": { ok: true },
          "POST /api/paper/orders/o2/reject": { ok: true },
        },
      ),
    );
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Orders/ }));
  };

  it("lists what waits for an answer separately from the history and labels every status", async () => {
    await open();
    const waiting = within(
      await screen.findByRole("table", {
        name: "Orders waiting for your answer",
      }),
    );
    expect(await waiting.findByText("TCS")).toBeInTheDocument();
    expect(waiting.getByText("INFY")).toBeInTheDocument();
    expect(waiting.getByText("exit: below_trend")).toBeInTheDocument();
    const history = within(
      screen.getByRole("table", { name: "Order history" }),
    );
    for (const label of [
      "Filled",
      "Failed",
      "Rejected",
      "Expired",
      "Approved, waiting to fill",
    ])
      expect(history.getByText(label)).toBeInTheDocument();
    expect(history.getByText("₹801.25")).toBeInTheDocument();
    expect(
      history.getByText("not enough cash for this order"),
    ).toBeInTheDocument();
  });

  it("approves and rejects one order at a time", async () => {
    await open();
    fireEvent.click(
      await screen.findByRole("button", { name: "Approve BUY TCS" }),
    );
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === "POST" && c.path === "/api/paper/orders/o1/approve",
        ),
      ).toBe(true),
    );
    expect(
      await screen.findByText(/Approved\. It fills at the next live price/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reject SELL INFY" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/paper/orders/o2/reject")).toBe(
        true,
      ),
    );
  });

  it("lets the owner choose a limit price when approving, and sends a market order by default", async () => {
    await open();
    fireEvent.change(await screen.findByLabelText("Order type for TCS"), {
      target: { value: "LIMIT" },
    });
    const price = screen.getByLabelText("Limit price for TCS");
    expect(price).toHaveValue("3500"); // starts at the reference price
    expect(price).toHaveAttribute("placeholder", "step 0.05"); // the stock's exchange price step
    fireEvent.change(price, { target: { value: "1490.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Approve BUY TCS" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === "/api/paper/orders/o1/approve")?.body,
      ).toEqual({ order_type: "LIMIT", limit_price: "1490.5" }),
    );
    expect(
      await screen.findByText(
        /fills only at the limit \(₹1490\.5, rounded to the price step\) or better/,
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Approve SELL INFY" }));
    await waitFor(() =>
      expect(
        calls.find((c) => c.path === "/api/paper/orders/o2/approve")?.body,
      ).toEqual({ order_type: "MARKET" }),
    );
  });

  it("will not approve a limit order without a price", async () => {
    await open();
    fireEvent.change(await screen.findByLabelText("Order type for TCS"), {
      target: { value: "LIMIT" },
    });
    fireEvent.change(screen.getByLabelText("Limit price for TCS"), {
      target: { value: "" },
    });
    expect(
      screen.getByRole("button", { name: "Approve BUY TCS" }),
    ).toBeDisabled();
  });

  it("can approve everything waiting at once", async () => {
    backend(
      ready(
        {},
        {
          "POST /api/paper/orders/o1/approve": { ok: true },
          "POST /api/paper/orders/o2/approve": { ok: true },
        },
      ),
    );
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Orders/ }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Approve all 2 at market" }),
    );
    await waitFor(() =>
      expect(
        posted()
          .map((c) => c.path)
          .sort(),
      ).toEqual([
        "/api/paper/orders/o1/approve",
        "/api/paper/orders/o2/approve",
      ]),
    );
  });

  it("shows why the server refused an answer", async () => {
    backend(
      ready(
        {},
        {
          "POST /api/paper/orders/o1/approve": [
            400,
            { detail: "this order has expired" },
          ],
        },
      ),
    );
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Orders/ }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Approve BUY TCS" }),
    );
    expect(
      await screen.findByText("this order has expired"),
    ).toBeInTheDocument();
  });

  it("explains an empty queue", async () => {
    backend(ready({}, { "GET /api/paper/orders": { orders: [] } }));
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Orders/ }));
    expect(await screen.findByText("Nothing to approve")).toBeInTheDocument();
    expect(screen.getByText("No orders yet")).toBeInTheDocument();
  });
});

describe("the decision log", () => {
  it("shows each day's result with its reason", async () => {
    backend(ready());
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Decisions/ }));
    const table = within(
      await screen.findByRole("table", { name: "Daily decisions" }),
    );
    await table.findByText("Orders proposed"); // the rows arrive after the table appears
    for (const label of ["Could not decide", "No change", "Skipped"])
      expect(table.getByText(label)).toBeInTheDocument();
    expect(table.getByText("no nifty200_list in the lake")).toBeInTheDocument();
  });

  it("says so when nothing has run yet", async () => {
    backend(ready({}, { "GET /api/paper/runs": { runs: [] } }));
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: /Decisions/ }));
    expect(await screen.findByText("No decisions yet")).toBeInTheDocument();
  });
});

describe("settings", () => {
  const open = async (
    over: Record<string, unknown> = {},
    extra: Record<string, unknown> = {},
  ) => {
    backend(
      ready(over, {
        "POST /api/paper/account/settings": { ok: true },
        ...extra,
      }),
    );
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: "Settings" }));
  };

  it("shows the index it runs, and no longer holds the strategy's own choices", async () => {
    await open({ universe: "nifty50", max_instruments: 20 });
    expect(
      await screen.findByText("Index: Nifty 50, top 20 stocks."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Number of stocks")).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Create a strategy" }),
    ).toHaveAttribute("href", "/strategies");
  });

  it("switches the account to another saved strategy", async () => {
    await open(
      {},
      {
        "GET /api/strategies": strategies([
          { ...STRATEGY, in_use: true },
          { ...STRATEGY, config_id: "c2", name: "Bolder" },
        ]),
        "POST /api/strategies/c2/use": { ok: true },
      },
    );
    const pick = await screen.findByLabelText("Strategy");
    await waitFor(() => expect(pick).toHaveValue("c1"));
    fireEvent.change(pick, { target: { value: "c2" } });
    await waitFor(() =>
      expect(posted()[0]?.path).toBe("/api/strategies/c2/use"),
    );
    expect(await screen.findByText(/Strategy changed/)).toBeInTheDocument();
  });

  it("switches paper trading off and on", async () => {
    await open();
    const sw = await screen.findByRole("switch", { name: "Trading" });
    expect(sw).toHaveAttribute("aria-checked", "true");
    fireEvent.click(sw);
    await waitFor(() => expect(posted()[0]?.body).toEqual({ enabled: false }));
    expect(
      await screen.findByText(/Trading is off\. No new orders/),
    ).toBeInTheDocument();
  });

  it("confirms turning it back on", async () => {
    await open({ enabled: false });
    fireEvent.click(
      await screen.findByRole("switch", { name: "Trading" }),
    );
    await waitFor(() => expect(posted()[0]?.body).toEqual({ enabled: true }));
    expect(await screen.findByText("Trading is on.")).toBeInTheDocument();
  });

  it("shows the server's reason when a change is refused", async () => {
    await open(
      {},
      {
        "POST /api/paper/account/settings": [
          400,
          { detail: "unknown universe 'x'" },
        ],
      },
    );
    fireEvent.click(
      await screen.findByRole("switch", { name: "Trading" }),
    );
    expect(await screen.findByText("unknown universe 'x'")).toBeInTheDocument();
  });
});

describe("loading and failure", () => {
  it("says so when the account cannot be loaded", async () => {
    backend({ "GET /api/auth/me": who() });
    mount();
    expect(
      await screen.findByText("Could not load your trading account"),
    ).toBeInTheDocument();
  });
});
