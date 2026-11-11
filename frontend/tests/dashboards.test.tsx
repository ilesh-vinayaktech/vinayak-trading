import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import OperationsPage from "@/app/operations/page";
import OverviewPage from "@/app/overview/page";
import { AuthProvider } from "@/lib/auth";
import me from "./contract/dashboard_me.json";
import ops from "./contract/dashboard_operations.json";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/overview",
  useSearchParams: () => new URLSearchParams(""),
}));

const who = (perms: string[]) => ({
  user: {
    id: "u1",
    email: "jane@example.com",
    name: "Jane Roe",
    role: "TRADER",
    permissions: perms,
    mfa_enabled: false,
    enrolment_required: false,
    must_change_password: false,
  },
});
function backend(table: Record<string, unknown>) {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const hit = table[new URL(String(input)).pathname];
    return hit === undefined
      ? new Response("{}", { status: 404 })
      : new Response(JSON.stringify(hit), { status: 200 });
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

describe("my overview", () => {
  it("greets by first name and shows my own connection, requests, two-factor state and setup steps", async () => {
    backend({
      "/api/auth/me": who(["research:read", "kite:own", "tickets:own"]),
      "/api/dashboard/me": me,
    });
    mount(<OverviewPage />);
    expect(
      await screen.findByRole("heading", { name: "Welcome back, Jane" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Kite connection/ }),
    ).toHaveTextContent("Not set up");
    expect(
      screen.getByRole("link", { name: /Open requests/ }),
    ).toHaveTextContent("1");
    expect(
      screen.getByRole("link", { name: /Two-factor sign-in/ }),
    ).toHaveTextContent("Off");
    expect(screen.queryByText("My follow-ups")).not.toBeInTheDocument(); // staff only
    expect(
      within(
        await screen.findByRole("table", { name: "Your open requests" }),
      ).getByText("Help with Kite"),
    ).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("list", { name: "Setup checklist" }),
      ).getAllByRole("link", { name: "Do this" }),
    ).toHaveLength(3);
  });

  it("shows a connected session with its expiry and ticks the finished steps", async () => {
    const connected = {
      ...me,
      kite: {
        ...me.kite,
        state: "connected",
        token_expires_at: "2026-11-12T00:30:00+00:00",
      },
      security: { ...me.security, mfa_enabled: true },
      tickets: { open: 0, latest: [] },
    };
    backend({
      "/api/auth/me": who(["kite:own", "crm:read"]),
      "/api/dashboard/me": connected,
    });
    mount(<OverviewPage />);
    expect(
      await screen.findByRole("link", { name: /Kite connection/ }),
    ).toHaveTextContent("Connected");
    expect(
      screen.getByRole("link", { name: /Kite connection/ }),
    ).toHaveTextContent("IST");
    expect(screen.getByText("My follow-ups")).toBeInTheDocument();
    expect(screen.getByText("No open requests")).toBeInTheDocument();
    expect(
      within(
        screen.getByRole("list", { name: "Setup checklist" }),
      ).queryAllByRole("link", { name: "Do this" }),
    ).toHaveLength(0);
  });

  it("says so when the overview cannot load", async () => {
    backend({ "/api/auth/me": who(["kite:own"]) });
    mount(<OverviewPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load your overview",
    );
  });
});

describe("operations", () => {
  it("flags a missing data feed, failed sign-ins and overdue follow-ups, and lists recent activity", async () => {
    backend({
      "/api/auth/me": who(["ops:read"]),
      "/api/dashboard/operations": {
        ...ops,
        signins: { successes_24h: 5, failures_24h: 2 },
      },
    });
    mount(<OperationsPage />);
    expect(
      await screen.findByRole("link", { name: /Data feed/ }),
    ).toHaveTextContent("No feed");
    expect(screen.getByRole("link", { name: /Sign-ins/ })).toHaveTextContent(
      "2 failed",
    );
    expect(
      screen.getByRole("link", { name: /Open follow-ups/ }),
    ).toHaveTextContent("1 overdue");
    expect(
      screen.getByRole("link", { name: /Open tickets/ }),
    ).toHaveTextContent("1 unassigned");
    expect(
      within(
        screen.getByRole("table", { name: "Recent activity" }),
      ).getAllByText("auth.login"),
    ).toHaveLength(2);
    expect(
      within(screen.getByRole("list", { name: "Users by role" })).getByText(
        "Trader",
      ),
    ).toBeInTheDocument();
  });

  it("shows the live feed with its owner and expiry, and the not-connected and expired states", async () => {
    const feed = (state: string) => ({
      ...ops,
      kite: {
        connected: 1,
        feed: {
          owner_id: "o",
          owner: "Ilesh Patel",
          api_key_hint: "mu81",
          state,
          token_expires_at: "2026-11-12T00:30:00+00:00",
        },
      },
    });
    backend({
      "/api/auth/me": who(["ops:read"]),
      "/api/dashboard/operations": feed("connected"),
    });
    const { unmount } = mount(<OperationsPage />);
    expect(
      await screen.findByRole("link", { name: /Data feed/ }),
    ).toHaveTextContent("Live");
    expect(screen.getByRole("link", { name: /Data feed/ })).toHaveTextContent(
      "Ilesh Patel",
    );
    unmount();
    backend({
      "/api/auth/me": who(["ops:read"]),
      "/api/dashboard/operations": feed("expired"),
    });
    mount(<OperationsPage />);
    expect(
      await screen.findByRole("link", { name: /Data feed/ }),
    ).toHaveTextContent("Expired");
  });

  it("shows what the live market feed is doing, and calls out one that went quiet without saying so", async () => {
    const live = (over: Record<string, unknown>) => ({
      ...ops,
      feed: {
        state: "CONNECTED",
        detail: "497 instruments",
        subscribed: 497,
        heartbeat_age: 4,
        tick_age: 2,
        ...over,
      },
    });
    const cases: [Record<string, unknown>, string, string][] = [
      [{}, "Streaming", "497 instruments, last tick 2s ago"],
      [{ tick_age: null }, "Streaming", "no ticks yet"],
      [{ heartbeat_age: 90 }, "Stopped unexpectedly", "No status for 90s"],
      [
        { state: "RECONNECTING", detail: "OSError: refused; retrying in 4 s" },
        "Reconnecting",
        "retrying in 4 s",
      ],
      [{ state: "TOKEN_EXPIRED" }, "Token expired", "Connect to Zerodha"],
      [{ state: "STARTING", detail: "" }, "Starting", ""],
      [
        { state: "STOPPED", detail: "reached the end time" },
        "Stopped",
        "reached the end time",
      ],
    ];
    for (const [over, word, hint] of cases) {
      backend({
        "/api/auth/me": who(["ops:read"]),
        "/api/dashboard/operations": live(over),
      });
      const { unmount } = mount(<OperationsPage />);
      const card = await screen
        .findByRole("heading", { name: "Operations" })
        .then(() => screen.findByText("Live market feed"));
      const text = card.parentElement?.textContent ?? "";
      expect(text).toContain(word);
      expect(text).toContain(hint);
      unmount();
    }
  });

  it("says the streaming service has not run yet when there is no status", async () => {
    backend({
      "/api/auth/me": who(["ops:read"]),
      "/api/dashboard/operations": ops,
    });
    mount(<OperationsPage />);
    expect(
      (await screen.findByText("Live market feed")).parentElement,
    ).toHaveTextContent("Not started");
  });

  it("says so when operations cannot load", async () => {
    backend({ "/api/auth/me": who(["ops:read"]) });
    mount(<OperationsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load operations",
    );
  });
});
