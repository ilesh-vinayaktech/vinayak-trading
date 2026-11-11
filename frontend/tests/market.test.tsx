import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MarketPage from "@/app/market/page";
import { Providers } from "@/app/providers";
import fixture from "./contract/market_calendar.json";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/market",
  useSearchParams: () => new URLSearchParams(""),
}));

const calendar = {
  ...fixture,
  exceptions: fixture.exceptions.map((r, i) => ({ ...r, id: i + 1 })),
}; // the fixture scrubs ids to 0
const who = (perms: string[]) => ({
  user: {
    id: "u1",
    email: "ops@example.com",
    name: "Olive Ops",
    role: "OPERATOR",
    permissions: perms,
    mfa_enabled: true,
    enrolment_required: false,
    must_change_password: false,
  },
});
const calls: { method: string; path: string; body: unknown }[] = [];
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
      <MarketPage />
    </Providers>,
  );
const STAFF = ["ops:read", "ops:write"];

beforeEach(() => {
  document.cookie = "csrf=tok";
});
afterEach(() => vi.unstubAllGlobals());

describe("trading calendar", () => {
  it("shows today's hours, the upcoming exceptions and what still needs hours", async () => {
    backend({
      "GET /api/auth/me": who(STAFF),
      "GET /api/market/calendar": calendar,
    });
    mount();
    expect(await screen.findByTestId("today")).toHaveTextContent(
      "09:15 to 15:30 IST",
    );
    const table = within(
      screen.getByRole("table", {
        name: "Upcoming holidays and special sessions",
      }),
    );
    expect(table.getByText("Special session")).toBeInTheDocument();
    expect(table.getByText("09:15 to 10:00")).toBeInTheDocument();
    expect(table.getAllByText("Closed")).toHaveLength(2);
    expect(table.getAllByText("NSE list")).toHaveLength(2);
    expect(table.getByText("Added by hand")).toBeInTheDocument();
    expect(table.getByText("Hours needed")).toBeInTheDocument();
    expect(table.getByText("Special Muhurat")).toBeInTheDocument(); // the star is NSE's marker, not part of the name
    expect(
      screen.getByText("1 special session needs its hours"),
    ).toBeInTheDocument();
  });

  it("says plainly when today has no trading, and when there are no exceptions at all", async () => {
    backend({
      "GET /api/auth/me": who(STAFF),
      "GET /api/market/calendar": {
        today: { day: "2026-11-14", windows: [] },
        exceptions: [],
      },
    });
    mount();
    expect(await screen.findByTestId("today")).toHaveTextContent(
      "no trading, the feed stays idle",
    );
    expect(screen.getByText("No exceptions")).toBeInTheDocument();
    expect(screen.queryByText(/need.* their hours/)).not.toBeInTheDocument();
  });

  it("lists several windows of one day together", async () => {
    backend({
      "GET /api/auth/me": who(STAFF),
      "GET /api/market/calendar": {
        today: {
          day: "2026-11-14",
          windows: [
            { start: "09:00", end: "10:00" },
            { start: "18:00", end: "19:00" },
          ],
        },
        exceptions: [],
      },
    });
    mount();
    expect(await screen.findByTestId("today")).toHaveTextContent(
      "09:00 to 10:00 and 18:00 to 19:00 IST",
    );
  });

  it("adds hours for a listed special day: the form starts on that date and posts what was typed", async () => {
    backend({
      "GET /api/auth/me": who(STAFF),
      "GET /api/market/calendar": calendar,
      "POST /api/market/sessions": { id: 9 },
    });
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Add hours" }));
    const dialog = within(
      await screen.findByRole("dialog", { name: "Add a special session" }),
    );
    expect(dialog.getByLabelText("Date")).toHaveValue("2026-11-28");
    fireEvent.change(dialog.getByLabelText("Starts"), {
      target: { value: "18:15" },
    });
    fireEvent.change(dialog.getByLabelText("Ends"), {
      target: { value: "19:15" },
    });
    fireEvent.change(dialog.getByLabelText("Note"), {
      target: { value: "Muhurat" },
    });
    fireEvent.click(dialog.getByRole("button", { name: "Add session" }));
    await waitFor(() =>
      expect(calls.find((c) => c.method === "POST")?.body).toEqual({
        day: "2026-11-28",
        start: "18:15",
        end: "19:15",
        note: "Muhurat",
      }),
    );
    expect(await screen.findByText(/Session added for/)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("opens an empty-date form from the header button and shows the server's reason when it refuses", async () => {
    backend({
      "GET /api/auth/me": who(STAFF),
      "GET /api/market/calendar": calendar,
      "POST /api/market/sessions": [
        400,
        { detail: "that window overlaps another session on the same day" },
      ],
    });
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Add special session" }),
    );
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByLabelText("Date")).toHaveValue("");
    fireEvent.change(dialog.getByLabelText("Date"), {
      target: { value: "2026-11-14" },
    });
    fireEvent.click(dialog.getByRole("button", { name: "Add session" }));
    expect(await dialog.findByRole("alert")).toHaveTextContent(
      "that window overlaps another session on the same day",
    );
    fireEvent.click(dialog.getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("removes an entry only after a confirmation", async () => {
    backend({
      "GET /api/auth/me": who(STAFF),
      "GET /api/market/calendar": calendar,
      "POST /api/market/sessions/1/remove": { ok: true },
    });
    mount();
    const row = (await screen.findByText("Special live session")).closest(
      "tr",
    ) as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Remove" }));
    expect(calls.some((c) => c.path.endsWith("/remove"))).toBe(false);
    fireEvent.click(within(row).getByRole("button", { name: "Remove" })); // the confirm button of the same name
    await waitFor(() =>
      expect(
        calls.some(
          (c) =>
            c.method === "POST" && c.path === "/api/market/sessions/1/remove",
        ),
      ).toBe(true),
    );
    expect(await screen.findByText("Entry removed.")).toBeInTheDocument();
  });

  it("shows a refused removal", async () => {
    backend({
      "GET /api/auth/me": who(STAFF),
      "GET /api/market/calendar": calendar,
      "POST /api/market/sessions/1/remove": [404, { detail: "no such entry" }],
    });
    mount();
    const row = (await screen.findByText("Special live session")).closest(
      "tr",
    ) as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Remove" }));
    fireEvent.click(within(row).getByRole("button", { name: "Remove" }));
    expect(await screen.findByText("no such entry")).toBeInTheDocument();
  });

  it("is read-only for someone who can see operations but not change them", async () => {
    backend({
      "GET /api/auth/me": who(["ops:read"]),
      "GET /api/market/calendar": calendar,
    });
    mount();
    await screen.findByTestId("today");
    expect(
      screen.queryByRole("button", { name: "Add special session" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Remove" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add hours" }),
    ).not.toBeInTheDocument();
  });

  it("says so when the calendar cannot load", async () => {
    backend({ "GET /api/auth/me": who(STAFF) });
    mount();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load the calendar",
    );
  });
});
