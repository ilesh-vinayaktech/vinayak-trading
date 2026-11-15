import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import IntelligencePage from "@/app/research/intelligence/page";
import { Providers } from "@/app/providers";
import allocations from "./contract/intel_allocations.json";
import alpha from "./contract/intel_alpha.json";
import notes from "./contract/intel_notes.json";
import overview from "./contract/intel_overview.json";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/research/intelligence",
  useSearchParams: () => new URLSearchParams(""),
}));

const who = { user: { id: "u1", email: "jane@example.com", name: "Jane", role: "TRADER", permissions: ["research:read"], mfa_enabled: true, enrolment_required: false, must_change_password: false } };
const empty = {
  overview: { features: { by_status: {} }, alpha: { tests_ever_run: 0, by_status: {} }, factory: { definitions: 0, experiments: 0, trials: 0 }, notes: { total: 0 }, health: [], allocation: null },
  alpha: { hypotheses: [] },
  notes: { notes: [] },
};
const seen: string[] = [];
function backend(table: { overview: unknown; alpha: unknown; notes: unknown }) {
  seen.length = 0;
  vi.stubGlobal("fetch", async (input: RequestInfo | URL) => {
    const url = new URL(String(input));
    seen.push(url.pathname + url.search);
    const body = { "/api/auth/me": who, "/api/intel/overview": table.overview, "/api/intel/alpha": table.alpha, "/api/intel/notes": table.notes, "/api/intel/allocations": allocations }[url.pathname];
    if (body === undefined) return new Response(JSON.stringify({ detail: "no route" }), { status: 404 });
    return new Response(JSON.stringify(body), { status: 200 });
  });
}
const mount = () => render(<Providers><IntelligencePage /></Providers>);
afterEach(() => vi.unstubAllGlobals());

describe("Research intelligence", () => {
  it("shows what has been recorded: counts, health, allocation advice, alpha tests and notes", async () => {
    backend({ overview, alpha, notes });
    mount();
    expect(await screen.findByText("Where the research stands")).toBeTruthy();
    expect(screen.getByText("12 draft")).toBeTruthy();
    expect(screen.getByText("Alpha tests ever run")).toBeTruthy();
    expect(screen.getByText("Degraded")).toBeTruthy();
    expect(screen.getByText(/DEGRADED: mean return/)).toBeTruthy();
    expect(screen.getByText(/Advice only, nothing was changed/)).toBeTruthy();
    const tests = within(await screen.findByRole("table", { name: "Alpha hypotheses" }));
    expect(tests.getByText("ret_5d v1")).toBeTruthy();
    expect(tests.getByText("Worth validating")).toBeTruthy();
    expect(tests.getByText("Rejected")).toBeTruthy();
    const memory = within(await screen.findByRole("table", { name: "Research notes" }));
    expect(memory.getByText("capital")).toBeTruthy();
  });

  it("says plainly that nothing has been recorded yet instead of showing zeros as results", async () => {
    backend(empty);
    mount();
    expect(await screen.findByText("No health check has run yet")).toBeTruthy();
    expect(screen.getByText("No allocation advice yet")).toBeTruthy();
    expect(screen.getByText("No alpha test has been recorded")).toBeTruthy();
    expect(screen.getByText("No notes match")).toBeTruthy();
    expect(screen.getByText("None yet")).toBeTruthy();
  });

  it("asks the API for only the chosen verdict and for the searched notes", async () => {
    backend({ overview, alpha, notes });
    mount();
    await screen.findByText("Where the research stands");
    fireEvent.change(screen.getByLabelText("Verdict filter"), { target: { value: "CANDIDATE" } });
    await waitFor(() => expect(seen).toContain("/api/intel/alpha?status=CANDIDATE"));
    fireEvent.change(screen.getByLabelText("Search notes"), { target: { value: "capital" } });
    await waitFor(() => expect(seen).toContain("/api/intel/notes?q=capital"));
  });

  it("explains a failed load instead of showing a blank page", async () => {
    vi.stubGlobal("fetch", async (input: RequestInfo | URL) => (new URL(String(input)).pathname === "/api/auth/me" ? new Response(JSON.stringify(who)) : new Response(JSON.stringify({ detail: "not allowed" }), { status: 403 })));
    mount();
    expect(await screen.findByText(/Could not load the research overview/)).toBeTruthy();
  });
});
