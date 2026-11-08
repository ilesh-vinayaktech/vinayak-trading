import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import ReviewsPage from "@/app/research/reviews/page";

const OPTIONS = [
  { value: "CONFIRM_MAPPING", label: "Same security: map", needs_date: true, date_label: "Alias valid from" },
  { value: "KEEP_SEPARATE", label: "Different security", needs_date: false },
  { value: "NEEDS_MORE_EVIDENCE", label: "Not decided", needs_date: false, needs_evidence: false },
];
const item = (id: string, latest: unknown = null) => ({ id, kind: "SYMBOL_IDENTITY", title: id, question: "q?", category: "UNRESOLVED", context: { Notes: "n" }, leads: ["pr_ind_prs1"], options: OPTIONS, latest });
const list = (writes: boolean, items: unknown[]) => ({ writes_enabled: writes, total: items.length, decided: 0, items });

function mount(table: Record<string, unknown>, posts: unknown[] = []) {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    if (init?.method === "POST") {
      posts.push(JSON.parse(String(init.body)));
      return new Response(JSON.stringify({ decision_id: 1 }), { status: 201 });
    }
    const hit = table[url.pathname];
    return hit === undefined ? new Response("{}", { status: 404 }) : new Response(JSON.stringify(hit), { status: 200 });
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><ReviewsPage /></QueryClientProvider>);
}

afterEach(() => vi.unstubAllGlobals());

describe("Reviews", () => {
  it("needs a date, the evidence and a name before it can save, then posts exactly that decision", async () => {
    const posts: unknown[] = [];
    mount({ "/api/reviews": list(true, [item("symbol:X")]) }, posts);
    fireEvent.click(await screen.findByRole("button", { name: /symbol:X/ }));
    const save = screen.getByRole("button", { name: "Save decision" });
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Decision"), { target: { value: "CONFIRM_MAPPING" } });
    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "ilesh" } });
    fireEvent.change(screen.getByLabelText(/^Evidence/), { target: { value: "pr_ind_prs1 p3" } });
    expect(save).toBeDisabled(); // the date is still missing
    fireEvent.change(screen.getByLabelText("Alias valid from"), { target: { value: "2022-04-01" } });
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toEqual({ decision: "CONFIRM_MAPPING", reviewer: "ilesh", effective_date: "2022-04-01", evidence_ref: "pr_ind_prs1 p3", note: "" });
  });

  it("filters open and decided items and shows the progress", async () => {
    const decided = { decision_id: 1, decision: "KEEP_SEPARATE", effective_date: null, effective_to: null, evidence_ref: "d", note: "", reviewer: "a", decided_at: "2026-11-08T00:00:00Z" };
    mount({ "/api/reviews": { ...list(true, [item("open:1"), item("done:1", decided)]), decided: 1 } });
    expect(await screen.findByText("1 of 2 decided")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open:1/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /done:1/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "decided" }));
    expect(screen.getByRole("button", { name: /done:1/ })).toBeInTheDocument();
  });

  it("says so and disables the form when the server has saving switched off", async () => {
    mount({ "/api/reviews": list(false, [item("symbol:X")]) });
    expect(await screen.findByText(/Saving is switched off/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /symbol:X/ }));
    expect(screen.getByLabelText("Decision")).toBeDisabled();
  });

  it("shows the server's refusal reason", async () => {
    vi.stubGlobal("fetch", async (_: RequestInfo | URL, init?: RequestInit) =>
      init?.method === "POST" ? new Response(JSON.stringify({ detail: "cite the source document" }), { status: 422 }) : new Response(JSON.stringify(list(true, [item("symbol:X")])), { status: 200 }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><ReviewsPage /></QueryClientProvider>);
    fireEvent.click(await screen.findByRole("button", { name: /symbol:X/ }));
    fireEvent.change(screen.getByLabelText("Decision"), { target: { value: "KEEP_SEPARATE" } });
    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "i" } });
    fireEvent.change(screen.getByLabelText(/^Evidence/), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Save decision" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("cite the source document");
  });
});
