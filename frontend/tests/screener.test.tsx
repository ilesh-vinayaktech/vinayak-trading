import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import ScreenerPage from "@/app/screener/page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/screener",
  useSearchParams: () => new URLSearchParams(""),
}));

const META = {
  fields: [
    {
      key: "pe",
      label: "Price to earnings (P/E)",
      group: "valuation",
      kind: "fundamental",
      unit: "x",
    },
    {
      key: "roe",
      label: "Return on equity (ROE)",
      group: "profitability",
      kind: "fundamental",
      unit: "pct",
    },
    {
      key: "price",
      label: "Last close",
      group: "trend",
      kind: "technical",
      unit: "inr",
    },
    {
      key: "chg_1d",
      label: "Change, 1 day",
      group: "momentum",
      kind: "technical",
      unit: "pct",
    },
    {
      key: "rsi_14",
      label: "RSI (14)",
      group: "momentum",
      kind: "technical",
      unit: "x",
    },
    {
      key: "pe_vs_sector",
      label: "P/E relative to its sector peers (1 = same)",
      group: "valuation",
      kind: "profile",
      unit: "x",
    },
  ],
  presets: [
    {
      id: "value-oversold",
      name: "Value on a dip",
      category: "combined",
      description: "Cheap and sold down.",
      sort: "rsi_14",
      descending: false,
      conditions: [
        { field: "pe", op: "between", value: [1, 20] },
        { field: "rsi_14", op: "lte", value: 40 },
      ],
    },
    {
      id: "value-picks",
      name: "Value picks",
      category: "fundamental",
      description: "Cheap.",
      sort: "pe",
      descending: false,
      conditions: [{ field: "pe", op: "lte", value: 15 }],
    },
  ],
};
const calls: { path: string; body: unknown }[] = [];
beforeEach(() => {
  document.cookie = "csrf=tok";
  calls.length = 0;
  vi.stubGlobal(
    "fetch",
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input)).pathname;
      calls.push({
        path,
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
      });
      const body =
        path === "/api/strategies"
          ? { config_id: "c1" }
          : path.endsWith("/meta")
            ? META
            : path.endsWith("/run")
              ? {
                  total: 1,
                  sort: "rsi_14",
                  rows: [
                    {
                      instrument_id: 1,
                      symbol: "TCS",
                      name: "Tata Consultancy",
                      price: "3500.0000",
                      chg_1d: "1.5000",
                      pe: "18.0000",
                      rsi_14: "35.0000",
                    },
                  ],
                }
              : {
                  user: {
                    id: "u",
                    email: "a@b.c",
                    name: "A",
                    role: "RESEARCHER",
                    permissions: ["research:read"],
                    mfa_enabled: true,
                    enrolment_required: false,
                    must_change_password: false,
                  },
                };
      return new Response(JSON.stringify(body), { status: 200 });
    },
  );
});
afterEach(() => vi.unstubAllGlobals());

describe("screener", () => {
  it("runs a ready-made screen and shows its conditions, and the matching stocks with the fields screened on", async () => {
    render(
      <Providers>
        <ScreenerPage />
      </Providers>,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /Value on a dip/ }),
    );
    expect(await screen.findByText("Tata Consultancy")).toBeInTheDocument();
    expect(screen.getByText("₹3,500")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /RSI \(14\)/ }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Upper value")).toHaveValue("20");
    const run = calls.find((c) => c.path === "/api/screener/run");
    expect(run?.body).toMatchObject({
      match: "all",
      sort: "rsi_14",
      descending: false,
      conditions: [
        { field: "pe", op: "between", value: ["1", "20"] },
        { field: "rsi_14", op: "lte", value: "40" },
      ],
    });
  });

  it("offers P/E against the sector as a screen condition but says it cannot back a study or a saved strategy", async () => {
    render(
      <Providers>
        <ScreenerPage />
      </Providers>,
    );
    await screen.findByRole("button", { name: /Value picks/ });
    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));
    fireEvent.change(screen.getByLabelText("Field"), { target: { value: "pe_vs_sector" } });
    expect(screen.getByLabelText("Field")).toHaveValue("pe_vs_sector");
    expect(screen.getByText(/or a view against its sector cannot be a condition here/)).toBeInTheDocument();
  });

  it("filters ready-made screens by type and lets you add your own condition", async () => {
    render(
      <Providers>
        <ScreenerPage />
      </Providers>,
    );
    await screen.findByRole("button", { name: /Value picks/ });
    fireEvent.click(screen.getByRole("tab", { name: "Technical" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /Value picks/ }),
      ).not.toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: "Add condition" }));
    expect(screen.getByLabelText("Field")).toHaveValue("pe");
    expect(screen.getByRole("button", { name: "Run screen" })).toBeEnabled();
  });

  it("saves a screen as a strategy with its name, number of stocks and market-cap classes, filed ratios included", async () => {
    render(
      <Providers>
        <ScreenerPage />
      </Providers>,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /Value on a dip/ }),
    );
    await screen.findByText("Tata Consultancy");
    expect(
      screen.getByRole("button", { name: "Save as a strategy" }),
    ).toBeEnabled(); // filed ratios (P/E) can be saved too
    fireEvent.click(
      screen.getAllByRole("button", { name: "Remove" })[0] as HTMLElement,
    );
    fireEvent.click(screen.getByRole("button", { name: "Save as a strategy" }));
    fireEvent.change(await screen.findByLabelText("Name"), {
      target: { value: "Dip buyer" },
    });
    fireEvent.change(screen.getByLabelText("Stocks held"), {
      target: { value: "20" },
    });
    fireEvent.click(screen.getByLabelText("Small caps"));
    fireEvent.click(screen.getByRole("button", { name: "Save strategy" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/strategies")).toBe(true),
    );
    expect(calls.find((c) => c.path === "/api/strategies")?.body).toEqual({
      name: "Dip buyer",
      universe: "segments",
      max_instruments: null,
      timeframe: "1D",
      params: { max_positions: 20 },
      screen: {
        conditions: [{ field: "rsi_14", op: "lte", value: "40" }],
        match: "all",
        sort: "rsi_14",
        descending: false,
        segments: ["large", "mid", "small"],
      },
    });
  });
});
