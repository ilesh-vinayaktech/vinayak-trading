import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { IndustriesPanel } from "@/components/market/IndustriesPanel";
import { industriesSchema } from "@/lib/schemas";

const DATA = {
  as_of: "2026-11-17",
  industries: [
    { name: "Information Technology", stocks: 25, above_50: 80, above_200: 64, up_today: 52, median_1m: 3.4, avg_score: 58.2, scored: 20, top: ["TANLA", "COFORGE"] },
    { name: "Realty", stocks: 11, above_50: 18.2, above_200: 45, up_today: null, median_1m: -4.1, avg_score: null, scored: 0, top: [] },
  ],
};
function backend(body: unknown, status = 200) {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(body), { status }));
}
const mount = () => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><IndustriesPanel /></QueryClientProvider>);
afterEach(() => vi.unstubAllGlobals());

describe("IndustriesPanel", () => {
  it("matches the schema", () => expect(industriesSchema.safeParse(DATA).success).toBe(true));

  it("shows each group's breadth, median move, score with how many were scored, and the best names; a missing figure is a dash", async () => {
    backend(DATA);
    mount();
    expect(await screen.findByRole("rowheader", { name: "Information Technology" })).toBeInTheDocument();
    expect(screen.getByText("80%")).toBeInTheDocument();
    expect(screen.getByText("+3.4%")).toBeInTheDocument();
    expect(screen.getByText("58")).toBeInTheDocument();
    expect(screen.getByText("(20)")).toBeInTheDocument(); // only 20 of 25 were scored
    expect(screen.getByText("TANLA, COFORGE")).toBeInTheDocument();
    expect(screen.getAllByText("–").length).toBeGreaterThanOrEqual(2); // Realty: no up-today figure, no score
    expect(screen.getByText("-4.1%")).toBeInTheDocument();
  });

  it("says so when there is no data, and when loading fails", async () => {
    backend({ as_of: null, industries: [] });
    mount();
    expect(await screen.findByText("No industry breadth yet")).toBeInTheDocument();
    vi.unstubAllGlobals();
    backend({}, 500);
    mount();
    expect(await screen.findByText("Could not load the industries")).toBeInTheDocument();
  });
});
