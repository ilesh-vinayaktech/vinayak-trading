import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import IntelPage from "@/app/market/intel/page";
import { Providers } from "@/app/providers";
import { SmartMoneyPanel } from "@/components/market/SmartMoneyPanel";
import { nseFlowsSchema, nseInstrumentSchema } from "@/lib/schemas";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/market/intel",
  useSearchParams: () => new URLSearchParams(""),
}));

const ME = { user: { id: "u1", email: "a@b.c", name: "A", role: "ADMIN", permissions: ["research:read"], mfa_enabled: true, enrolment_required: false, must_change_password: false } };
const FLOWS = { rows: [
  { date: "2026-11-16", fii_buy: 15636.88, fii_sell: 10772.2, fii_net: 4864.68, dii_buy: 11752.03, dii_sell: 15271.08, dii_net: -3519.05 },
] };
const STOCK = {
  symbol: "AAA",
  delivery: [{ date: "2026-11-16", close: 100, volume: 1000, delivery_qty: 900, delivery_pct: 90 }, { date: "2026-11-13", close: 99, volume: 1000, delivery_qty: 500, delivery_pct: 50 }],
  holdings: [
    { period_end: "2026-09-30", promoter: 52, fii: 12, dii: 19, mf: 5, insurance: null, retail: 8, public: 48, filed_at: "2026-10-20T10:00:00+00:00", revised: false },
    { period_end: "2026-06-30", promoter: 50, fii: 10, dii: 20, mf: 5, insurance: null, retail: 8, public: 50, filed_at: "2026-07-20T10:00:00+00:00", revised: false },
  ],
  insider: [{ did: "1", symbol: "AAA", person: "P Person", category: "Promoters", type: "Buy", mode: "Market", quantity: 10, value: 30000000, pct_after: 52, from_date: null, intimation_date: null, broadcast_at: "2026-11-16T10:00:00+00:00" }],
  deals: [{ date: "2026-11-16", kind: "bulk", client: "FUND LLP", side: "BUY", quantity: 1000000, price: 200, value_cr: 20, remarks: null }],
};

function backend(table: Record<string, unknown>) {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const hit = table[`${init?.method ?? "GET"} ${url.pathname}`];
    return new Response(JSON.stringify(hit ?? { detail: "no route" }), { status: hit === undefined ? 404 : 200 });
  });
}
beforeEach(() => backend({ "GET /api/auth/me": ME, "GET /api/nse/flows": FLOWS, "GET /api/nse/instrument/7": STOCK }));
afterEach(() => vi.unstubAllGlobals());

describe("smart money", () => {
  it("the fixtures match the schemas the pages parse with", () => {
    expect(nseFlowsSchema.parse(FLOWS).rows).toHaveLength(1);
    expect(nseInstrumentSchema.parse(STOCK).symbol).toBe("AAA");
  });

  it("shows the FII and DII net flow of the latest session", async () => {
    render(<Providers><IntelPage /></Providers>);
    expect(await screen.findByText("FII net, last session")).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText(/4,864\.68/).length).toBeGreaterThan(0));
    expect(screen.getAllByText(/3,519\.05/).length).toBeGreaterThan(0);
  });

  it("shows one stock's holdings with the change since the previous quarter", async () => {
    render(<Providers><SmartMoneyPanel instrumentId={7} /></Providers>);
    expect(await screen.findByText("AAA: smart money")).toBeTruthy();
    expect(screen.getAllByText("+2.00")).toHaveLength(2);
    expect(screen.getByText("-1.00")).toBeTruthy(); // DII 20 -> 19
    expect(screen.getByText("Ownership changed.")).toBeTruthy(); // promoter +2, FII +2, DII -1 since June
    expect(screen.getByText(/Last session: 1,000 shares traded, 90.00% delivered/)).toBeTruthy();
    expect(screen.getByText("High delivery.")).toBeTruthy(); // 90% delivered: the 50%+ band
    expect(screen.getByText("P Person")).toBeTruthy();
    expect(screen.getByText("FUND LLP")).toBeTruthy();
  });

  it("says plainly when nothing is stored", async () => {
    backend({ "GET /api/auth/me": ME, "GET /api/nse/instrument/7": { ...STOCK, holdings: [], insider: [], deals: [], delivery: [] } });
    render(<Providers><SmartMoneyPanel instrumentId={7} /></Providers>);
    expect(await screen.findByText("No shareholding filing stored for this stock yet.")).toBeTruthy();
    expect(screen.getByText("No insider trades stored for this stock.")).toBeTruthy();
  });
});
