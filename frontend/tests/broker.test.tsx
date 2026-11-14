import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import BrokerPage from "@/app/broker/page";
import OverviewPage from "@/app/overview/page";
import { AuthProvider } from "@/lib/auth";
import me from "./contract/dashboard_me.json";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/broker",
  useSearchParams: () => new URLSearchParams(""),
}));

const who = (perms: string[]) => ({
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
const account = {
  state: "ok",
  message: null,
  read_at: "2026-11-14T12:00:00+00:00",
  kite_user_id: "AB1234",
  cash: "1234.50",
  holdings: [
    {
      symbol: "AAA",
      instrument_id: 7,
      quantity: "100",
      unsettled: "0",
      average_price: "200.50",
      last_price: "210.00",
      value: "21000.00",
      pnl: "950.00",
      platform_qty: "0",
      outside_qty: "100",
    },
    {
      symbol: "BBB",
      instrument_id: null,
      quantity: "15",
      unsettled: "5",
      average_price: "50.25",
      last_price: "48.00",
      value: "720.00",
      pnl: "-33.75",
      platform_qty: "10",
      outside_qty: "5",
    },
  ],
  positions: [],
  totals: { holdings_value: "21720.00", holdings_pnl: "916.25" },
};
let reads = 0;
function backend(
  perms: string[],
  acct: unknown,
  extra: Record<string, unknown> = {},
) {
  reads = 0;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const path = new URL(String(input)).pathname;
    if (path === "/api/kite/account") reads += 1;
    const table: Record<string, unknown> = {
      "/api/auth/me": who(perms),
      "/api/kite/account": acct,
      ...extra,
    };
    return table[path] === undefined
      ? new Response("{}", { status: 404 })
      : new Response(JSON.stringify(table[path]), { status: 200 });
  });
}
const mount = (ui: React.ReactElement) =>
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <AuthProvider>{ui}</AuthProvider>
    </QueryClientProvider>,
  );
afterEach(() => vi.unstubAllGlobals());

describe("Broker account", () => {
  it("shows cash, what is held, what is unsettled and who bought it, and says outside shares are safe", async () => {
    backend(["kite:own"], account);
    mount(<BrokerPage />);
    expect(await screen.findByText("₹1,234.50")).toBeInTheDocument();
    const holdings = within(screen.getByRole("table", { name: "Holdings" }));
    expect(holdings.getByText("AAA")).toBeInTheDocument();
    expect(holdings.getByText("5 not settled yet")).toBeInTheDocument();
    expect(holdings.getByText("100 outside the platform")).toBeInTheDocument();
    expect(
      holdings.getByText(/Platform 10, 5 outside the platform/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Shares you bought yourself are safe"),
    ).toBeInTheDocument();
    expect(screen.getByText("No positions today")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /sell|buy|cancel/i }),
    ).toBeNull(); // read only: nothing here can trade
  });

  it("opens the stock's detail page from its name, and shows a stock we do not know as plain text", async () => {
    backend(["kite:own"], account);
    mount(<BrokerPage />);
    const holdings = within(
      await screen.findByRole("table", { name: "Holdings" }),
    );
    expect(holdings.getByRole("link", { name: "Open AAA" })).toHaveAttribute(
      "href",
      "/data/instruments?id=7",
    );
    expect(holdings.queryByRole("link", { name: "Open BBB" })).toBeNull();
    expect(holdings.getByText("BBB")).toHaveAttribute(
      "title",
      expect.stringMatching(/no detail page/),
    );
  });

  it("reads again only when asked", async () => {
    backend(["kite:own"], account);
    mount(<BrokerPage />);
    await screen.findByText("₹1,234.50");
    expect(reads).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(reads).toBe(2));
  });

  it.each([
    ["not_connected", "Kite is not connected"],
    ["expired", "The Kite session has ended"],
  ])(
    "sends you to the Kite connection when the state is %s",
    async (state, title) => {
      backend(["kite:own"], {
        ...account,
        state,
        cash: null,
        holdings: [],
        totals: { holdings_value: "0", holdings_pnl: "0" },
        read_at: null,
      });
      mount(<BrokerPage />);
      expect(await screen.findByText(title)).toBeInTheDocument();
      expect(
        screen.getByRole("link", { name: "Open Kite connection" }),
      ).toHaveAttribute("href", "/kite");
      expect(screen.queryByText("Holdings value")).toBeNull();
    },
  );

  it("shows Kite's failure and no numbers rather than a guess", async () => {
    backend(["kite:own"], {
      ...account,
      state: "unavailable",
      message: "Kite answered HTTP 500",
      cash: null,
      holdings: [],
    });
    mount(<BrokerPage />);
    expect(
      await screen.findByText(/Kite answered HTTP 500/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Cash available")).toBeNull();
  });
});

describe("the overview's broker card", () => {
  const connected = {
    ...me,
    kite: {
      ...me.kite,
      state: "connected",
      token_expires_at: "2026-11-15T00:30:00+00:00",
    },
    tickets: { open: 0, latest: [] },
  };

  it("shows cash and holdings and links to the page, once Kite is connected", async () => {
    backend(["kite:own"], account, { "/api/dashboard/me": connected });
    mount(<OverviewPage />);
    const card = await screen.findByRole("link", { name: /Broker account/ });
    await waitFor(() => expect(card).toHaveTextContent("₹1,234.50"));
    expect(card).toHaveTextContent("2 holdings worth ₹21,720");
    expect(card).toHaveAttribute("href", "/broker");
  });

  it("does not ask Kite at all when it is not connected, or when the role has no Kite", async () => {
    backend(["kite:own"], account, {
      "/api/dashboard/me": {
        ...connected,
        kite: { ...connected.kite, state: "expired" },
      },
    });
    mount(<OverviewPage />);
    await screen.findByText("Kite connection");
    expect(screen.queryByRole("link", { name: /Broker account/ })).toBeNull();
    expect(reads).toBe(0);
  });
});
