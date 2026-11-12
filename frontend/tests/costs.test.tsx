import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CostsPage from "@/app/costs/page";
import { Providers } from "@/app/providers";
import preview from "./contract/costs_preview.json";
import schedules from "./contract/costs_schedules.json";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/costs",
  useSearchParams: () => new URLSearchParams(""),
}));

const CUR = "nse-cash-delivery-zerodha-2026-03-01";
const V = "2026-11-07.1";
const who = (perms: string[]) => ({
  user: {
    id: "u1",
    email: "boss@example.com",
    name: "The Boss",
    role: "ADMIN",
    permissions: perms,
    mfa_enabled: true,
    enrolment_required: false,
    must_change_password: false,
  },
});
const ADMIN = ["research:read", "system:settings"];
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
const ready = (perms = ADMIN, extra: Record<string, unknown> = {}) => ({
  "GET /api/auth/me": who(perms),
  "GET /api/costs/schedules": schedules,
  ...extra,
});
const mount = () =>
  render(
    <Providers>
      <CostsPage />
    </Providers>,
  );
const posted = () => calls.filter((c) => c.method === "POST");

beforeEach(() => {
  document.cookie = "csrf=tok";
});
afterEach(() => vi.unstubAllGlobals());

describe("the schedules", () => {
  it("lists a provider's schedules by start date with their status, newest first, and warns that none is verified", async () => {
    backend(ready());
    mount();
    const table = within(
      await screen.findByRole("table", { name: "Schedules over time" }),
    );
    const rows = table.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("2026-03-01");
    expect(rows[0]).toHaveTextContent("now");
    expect(rows[0]).toHaveTextContent("Needs checking");
    expect(rows[1]).toHaveTextContent("2020-07-01");
    expect(rows[1]).toHaveTextContent("2026-02-28");
    expect(rows[1]).toHaveTextContent("Assumed");
    expect(
      screen.getByText("2 of 2 schedules not verified"),
    ).toBeInTheDocument();
  });

  it("shows the charges of the chosen schedule and where each rate comes from", async () => {
    backend(ready());
    mount();
    const charges = within(
      await screen.findByRole("table", { name: "Charges in this schedule" }),
    );
    expect(charges.getByText("STT")).toBeInTheDocument();
    expect(charges.getByText("0.1% of value")).toBeInTheDocument();
    expect(charges.getByText("Stamp duty")).toBeInTheDocument();
    expect(charges.getByText("Buy only")).toBeInTheDocument();
    expect(charges.getByText("₹15.34 per order")).toBeInTheDocument();
    const sources = within(screen.getByRole("list", { name: "Sources" }));
    expect(sources.getAllByRole("link", { name: "source" })[0]).toHaveAttribute(
      "href",
      expect.stringMatching(/^https:\/\//),
    );
  });

  it("switches to another schedule and to the other product", async () => {
    backend(ready());
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "2020-07-01" }));
    expect(
      await screen.findByText(/extended back to|owner decision|current rate/i),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Intraday" }));
    const rows = within(
      await screen.findByRole("table", { name: "Schedules over time" }),
    )
      .getAllByRole("row")
      .slice(1);
    expect(rows).toHaveLength(2);
    const charges = within(
      screen.getByRole("table", { name: "Charges in this schedule" }),
    );
    expect(charges.getByText("0.03% of value")).toBeInTheDocument(); // intraday brokerage
  });

  it("says when there is nothing and when it cannot load", async () => {
    backend(ready(ADMIN, { "GET /api/costs/schedules": { schedules: [] } }));
    const { unmount } = mount();
    expect(
      await screen.findByText("No cost schedules yet"),
    ).toBeInTheDocument();
    unmount();
    backend({ "GET /api/auth/me": who(ADMIN) });
    mount();
    expect(
      await screen.findByText("Could not load the costs"),
    ).toBeInTheDocument();
  });
});

describe("the calculator", () => {
  it("itemises a trade and says how reliable the schedule behind it is", async () => {
    backend(ready(ADMIN, { "GET /api/costs/preview": preview }));
    mount();
    fireEvent.change(await screen.findByLabelText("Price (₹)"), {
      target: { value: "2850.5" },
    });
    fireEvent.change(screen.getByLabelText("On"), {
      target: { value: "2026-11-12" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Work out the charges" }),
    );
    const box = within(await screen.findByTestId("preview"));
    expect(box.getByText("₹2,85,050.00", { exact: false })).toBeInTheDocument();
    expect(box.getByText("₹285.05")).toBeInTheDocument();
    expect(box.getByText("0.1% of 285050.0")).toBeInTheDocument();
    expect(box.getByText("Total")).toBeInTheDocument();
    expect(box.getByText(/not been checked by a person/)).toBeInTheDocument();
    const q = new URLSearchParams(
      calls.find((c) => c.path === "/api/costs/preview")?.query,
    );
    expect(Object.fromEntries(q)).toEqual({
      broker: "zerodha",
      product: "DELIVERY",
      side: "BUY",
      qty: "100",
      price: "2850.5",
      day: "2026-11-12",
    });
  });

  it("marks an assumed schedule and shows the server's reason when no schedule covers the date", async () => {
    backend(
      ready(ADMIN, {
        "GET /api/costs/preview": {
          ...preview,
          schedule: { ...preview.schedule, status: "assumed_backfill" },
        },
      }),
    );
    const { unmount } = mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Work out the charges" }),
    );
    expect(
      await screen.findByText(/today's rates assumed for this date/),
    ).toBeInTheDocument();
    unmount();
    backend(
      ready(ADMIN, {
        "GET /api/costs/preview": [
          404,
          { detail: "no schedule covers 2010-01-01" },
        ],
      }),
    );
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Work out the charges" }),
    );
    expect(
      await screen.findByText("no schedule covers 2010-01-01"),
    ).toBeInTheDocument();
  });
});

describe("managing the schedules", () => {
  it("verifies the current schedule after a confirmation, which records the person", async () => {
    backend(
      ready(ADMIN, {
        [`POST /api/costs/schedules/${CUR}/${V}/verify`]: { ok: true },
      }),
    );
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Verify" }));
    expect(posted()).toHaveLength(0); // asks first
    fireEvent.click(
      within(
        screen.getByRole("group", {
          name: "I checked every rate against its source",
        }),
      ).getByRole("button", { name: "Verify" }),
    );
    await waitFor(() =>
      expect(posted()[0]?.path).toBe(`/api/costs/schedules/${CUR}/${V}/verify`),
    );
    expect(
      await screen.findByText(/Your name and the time are recorded/),
    ).toBeInTheDocument();
  });

  it("enters a price change with its start date, a source note and only the rates that changed", async () => {
    backend(
      ready(ADMIN, {
        [`POST /api/costs/schedules/${CUR}/${V}/new-version`]: { ok: true },
      }),
    );
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Enter a price change" }),
    );
    const dialog = within(
      await screen.findByRole("dialog", { name: "Enter a price change" }),
    );
    const save = dialog.getByRole("button", { name: "Save new version" });
    expect(save).toBeDisabled(); // nothing changed yet
    fireEvent.change(dialog.getByLabelText("Effective from"), {
      target: { value: "2027-04-01" },
    });
    fireEvent.change(dialog.getByLabelText("Where do these rates come from?"), {
      target: { value: "Budget 2027" },
    });
    fireEvent.change(dialog.getByLabelText(/^STT/), {
      target: { value: "0.11" },
    });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() =>
      expect(posted()[0]?.body).toEqual({
        valid_from: "2027-04-01",
        valid_until: null,
        note: "Budget 2027",
        changes: [{ type: "STT", side: "BOTH", rate_pct: "0.11" }],
      }),
    );
    expect(await screen.findByText(/New version saved/)).toBeInTheDocument();
  });

  it("sends a flat-amount change as an amount and shows the server's reason when it is refused", async () => {
    backend(
      ready(ADMIN, {
        [`POST /api/costs/schedules/${CUR}/${V}/new-version`]: [
          400,
          {
            detail: "a new version must start after 2026-03-01, not before it",
          },
        ],
      }),
    );
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Enter a price change" }),
    );
    const dialog = within(await screen.findByRole("dialog"));
    fireEvent.change(dialog.getByLabelText("Effective from"), {
      target: { value: "2026-01-01" },
    });
    fireEvent.change(dialog.getByLabelText("Where do these rates come from?"), {
      target: { value: "n" },
    });
    fireEvent.change(dialog.getByLabelText(/^Demat/), {
      target: { value: "16" },
    });
    fireEvent.click(dialog.getByRole("button", { name: "Save new version" }));
    expect(
      await dialog.findByText(
        "a new version must start after 2026-03-01, not before it",
      ),
    ).toBeInTheDocument();
    expect(posted()[0]?.body).toMatchObject({
      changes: [{ type: "DP_CHARGE", side: "SELL", amount: "16" }],
    });
  });

  it("extends the current rates over earlier history from a chosen date", async () => {
    backend(
      ready(ADMIN, {
        [`POST /api/costs/schedules/${CUR}/${V}/backfill`]: { ok: true },
      }),
    );
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Use for earlier history" }),
    );
    const dialog = within(
      await screen.findByRole("dialog", {
        name: "Use these rates for earlier history",
      }),
    );
    expect(dialog.getByLabelText("From")).toHaveValue("2016-01-01");
    fireEvent.click(
      dialog.getByRole("button", { name: "Apply to earlier history" }),
    );
    await waitFor(() =>
      expect(posted()[0]?.body).toEqual({ valid_from: "2016-01-01" }),
    );
    expect(
      await screen.findByText(/marked as an assumption/),
    ).toBeInTheDocument();
  });

  it("removes an unverified schedule after a confirmation and shows why a refusal happened", async () => {
    backend(
      ready(ADMIN, {
        [`POST /api/costs/schedules/${CUR}/${V}/remove`]: [
          400,
          { detail: "a verified schedule cannot be removed" },
        ],
      }),
    );
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Remove" }));
    fireEvent.click(
      within(
        screen.getByRole("group", { name: "Remove this schedule?" }),
      ).getByRole("button", { name: "Remove" }),
    );
    expect(
      await screen.findByText("a verified schedule cannot be removed"),
    ).toBeInTheDocument();
  });

  it("adds a provider as a copy of an existing one", async () => {
    backend(ready(ADMIN, { "POST /api/costs/providers": { ok: true } }));
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Add provider" }),
    );
    const dialog = within(
      await screen.findByRole("dialog", { name: "Add a provider" }),
    );
    fireEvent.change(dialog.getByLabelText("Provider name"), {
      target: { value: "Groww" },
    });
    fireEvent.change(dialog.getByLabelText("Effective from"), {
      target: { value: "2026-01-01" },
    });
    fireEvent.click(dialog.getByRole("button", { name: "Add provider" }));
    await waitFor(() =>
      expect(posted()[0]?.body).toEqual({
        name: "Groww",
        template_broker: "zerodha",
        valid_from: "2026-01-01",
        note: "",
      }),
    );
    expect(await screen.findByText(/Provider added/)).toBeInTheDocument();
  });

  it("shows several providers as tabs", async () => {
    const groww = schedules.schedules.map((s) => ({
      ...s,
      schedule_id: `groww-${s.schedule_id}`,
      broker: "groww",
    }));
    backend(
      ready(ADMIN, {
        "GET /api/costs/schedules": {
          schedules: [...schedules.schedules, ...groww],
        },
      }),
    );
    mount();
    fireEvent.click(await screen.findByRole("tab", { name: "groww" }));
    const rows = within(
      await screen.findByRole("table", { name: "Schedules over time" }),
    )
      .getAllByRole("row")
      .slice(1);
    expect(rows).toHaveLength(2);
  });

  it("is read-only for someone who may look but not change", async () => {
    backend(ready(["research:read"]));
    mount();
    await screen.findByRole("table", { name: "Charges in this schedule" });
    for (const name of [
      "Verify",
      "Enter a price change",
      "Use for earlier history",
      "Remove",
      "Add provider",
    ])
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Work out the charges" }),
    ).toBeInTheDocument(); // the calculator is for everyone
  });
});
