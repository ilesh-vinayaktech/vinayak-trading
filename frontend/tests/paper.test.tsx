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
  ...over,
});
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
  ...extra,
});
const posted = () => calls.filter((c) => c.method === "POST");

beforeEach(() => {
  document.cookie = "csrf=tok";
});
afterEach(() => vi.unstubAllGlobals());

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

describe("starting a paper account", () => {
  it("explains it is unvalidated and posts what was chosen, including the index, the number of stocks and the time frame", async () => {
    backend(ready(null, { "POST /api/paper/account": { ok: true } }));
    mount();
    expect(await screen.findByText("Unvalidated research")).toBeInTheDocument();
    fireEvent.change(await screen.findByLabelText("Index"), {
      target: { value: "nifty500" },
    });
    fireEvent.change(screen.getByLabelText("Number of stocks"), {
      target: { value: "100" },
    });
    fireEvent.change(screen.getByLabelText("Starting cash (₹)"), {
      target: { value: "500000" },
    });
    fireEvent.change(screen.getByLabelText("Buy when the 5-day RSI is below"), {
      target: { value: "30" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Start paper trading" }),
    );
    await waitFor(() =>
      expect(posted()[0]?.body).toEqual({
        initial_cash: "500000",
        universe: "nifty500",
        max_instruments: 100,
        timeframe: "1D",
        params: {
          trend_sma: 200,
          entry_rsi: 30,
          exit_rsi: 60,
          max_positions: 10,
        },
      }),
    );
    expect(
      await screen.findByText("Paper account started."),
    ).toBeInTheDocument();
  });

  it("leaves the number of stocks empty for the whole index and refuses a nonsense cap before sending anything", async () => {
    backend(ready(null, { "POST /api/paper/account": { ok: true } }));
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Start paper trading" }),
    );
    await waitFor(() =>
      expect(posted()[0]?.body).toMatchObject({ max_instruments: null }),
    );
    calls.length = 0;
    fireEvent.change(screen.getByLabelText("Number of stocks"), {
      target: { value: "3" },
    });
    expect(
      screen.getByText(
        "Enter a whole number from 5 to 500, or leave it empty.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Start paper trading" }),
    );
    expect(posted()).toHaveLength(0);
  });

  it("only offers the daily time frame today and shows the others as not available", async () => {
    backend(ready(null));
    mount();
    const frame = await screen.findByLabelText("Time frame");
    const options = within(frame).getAllByRole("option");
    expect(
      options.map((o) => [o.textContent, (o as HTMLOptionElement).disabled]),
    ).toEqual([
      ["Daily", false],
      ["1 hour (not available yet)", true],
      ["15 minutes (not available yet)", true],
    ]);
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
    expect(screen.getByText("Paper trading is off")).toBeInTheDocument();
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
      await screen.findByRole("button", { name: "Approve all 2" }),
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

  it("shows the current choices and saves changes to the index, the cap and the rules", async () => {
    await open({ universe: "nifty50", max_instruments: 20 });
    expect(await screen.findByLabelText("Index")).toHaveValue("nifty50");
    expect(screen.getByLabelText("Number of stocks")).toHaveValue("20");
    fireEvent.change(screen.getByLabelText("Index"), {
      target: { value: "nifty500" },
    });
    fireEvent.change(screen.getByLabelText("Number of stocks"), {
      target: { value: "" },
    });
    fireEvent.change(screen.getByLabelText("Most stocks held at once"), {
      target: { value: "5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() =>
      expect(posted()[0]?.body).toEqual({
        universe: "nifty500",
        max_instruments: null,
        timeframe: "1D",
        params: {
          trend_sma: 200,
          entry_rsi: 25,
          exit_rsi: 60,
          max_positions: 5,
        },
      }),
    );
    expect(await screen.findByText(/Settings saved/)).toBeInTheDocument();
  });

  it("switches paper trading off and on", async () => {
    await open();
    const sw = await screen.findByRole("switch", { name: "Paper trading" });
    expect(sw).toHaveAttribute("aria-checked", "true");
    fireEvent.click(sw);
    await waitFor(() => expect(posted()[0]?.body).toEqual({ enabled: false }));
    expect(
      await screen.findByText(/Paper trading is off\. No new orders/),
    ).toBeInTheDocument();
  });

  it("confirms turning it back on", async () => {
    await open({ enabled: false });
    fireEvent.click(
      await screen.findByRole("switch", { name: "Paper trading" }),
    );
    await waitFor(() => expect(posted()[0]?.body).toEqual({ enabled: true }));
    expect(await screen.findByText("Paper trading is on.")).toBeInTheDocument();
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
      await screen.findByRole("button", { name: "Save settings" }),
    );
    expect(await screen.findByText("unknown universe 'x'")).toBeInTheDocument();
  });
});

describe("loading and failure", () => {
  it("says so when the account cannot be loaded", async () => {
    backend({ "GET /api/auth/me": who() });
    mount();
    expect(
      await screen.findByText("Could not load your paper account"),
    ).toBeInTheDocument();
  });
});
