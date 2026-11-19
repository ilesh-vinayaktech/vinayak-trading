import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NoteChips } from "@/components/market/NoteChips";
import { StockNotesPanel } from "@/components/market/StockNotesPanel";

const note = (kind: string, text: string, tone: "good" | "bad" | "warn" | "info" = "info", rank = 2, detail: string | null = null) => ({ kind, tone, text, rank, detail });
const NOTES = { as_of: "2026-11-18T05:00:00+00:00", notes: { "7": [note("breakout", "Breakout", "good", 1, "Closed above resistance at 726.00"), note("delivery_surge", "Delivery 1.7x norm", "good", 4, "62% taken for delivery"), note("inside_bar", "Inside bar", "info", 4, null), note("rsi", "Overbought (RSI 74)", "warn", 5, "RSI above 70")] } };
const NEWS = { items: [{ title: "Tanla wins a big order", url: "https://ex.com/1", source: "ET", published_at: "2026-11-18T01:00:00+00:00", sentiment: 0.7, laya: 0.8, laya_confidence: 0.9, reading: "positive", reading_value: 0.8, reading_model: "laya", symbols: ["TANLA"] }], mood: [], stocks: [] };
function backend(news: unknown = NEWS, notes: unknown = NOTES) {
  vi.stubGlobal("fetch", async (url: string) => (url.includes("/api/market/notes") ? new Response(JSON.stringify(notes), { status: 200 }) : new Response(JSON.stringify(news), { status: 200 })));
}
const mount = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>);
afterEach(() => vi.unstubAllGlobals());

describe("NoteChips", () => {
  it("shows the first few notes as chips with their reading on hover, and the rest as one +n chip", () => {
    const list = NOTES.notes["7"];
    render(<NoteChips notes={list} />);
    expect(screen.getByText("Breakout")).toHaveAttribute("title", "Closed above resistance at 726.00");
    expect(screen.getByText("Inside bar")).toBeInTheDocument();
    expect(screen.queryByText("Overbought (RSI 74)")).toBeNull();
    expect(screen.getByText("+1")).toHaveAttribute("title", "Overbought (RSI 74)");
  });
  it("shows a dash when there is nothing to note", () => {
    render(<NoteChips notes={undefined} />);
    expect(screen.getByText("–")).toBeInTheDocument();
  });
});

describe("StockNotesPanel", () => {
  it("lists every note with its reading, then the headlines that name the stock", async () => {
    backend();
    mount(<StockNotesPanel instrumentId={7} symbol="TANLA" />);
    expect(await screen.findByText("Closed above resistance at 726.00")).toBeInTheDocument();
    expect(screen.getByText("Overbought (RSI 74)")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Tanla wins a big order" })).toHaveAttribute("href", "https://ex.com/1");
    expect(screen.getByText("Positive").parentElement).toHaveAttribute("title", "Read by the Laya model, 90% sure");
  });
  it("says so when nothing stands out and no headline names the stock", async () => {
    backend({ ...NEWS, items: [] }, { as_of: "x", notes: {} });
    mount(<StockNotesPanel instrumentId={7} symbol="TANLA" />);
    expect(await screen.findByText("Nothing stands out about this stock right now.")).toBeInTheDocument();
    expect(await screen.findByText(/No headline in the public feeds names TANLA/)).toBeInTheDocument();
  });
});

describe("StockNotesPanel headlines", () => {
  it("shows the top 3 and opens all of them in a dialog, each link in a new tab", async () => {
    const items = Array.from({ length: 5 }, (_, i) => ({ ...NEWS.items[0], title: `Headline ${i}`, url: `https://ex.com/${i}` }));
    backend({ ...NEWS, items });
    mount(<StockNotesPanel instrumentId={7} symbol="TANLA" />);
    expect(await screen.findByText("Headline 2")).toBeInTheDocument();
    expect(screen.queryByText("Headline 3")).toBeNull();
    screen.getByRole("button", { name: "View all 5 headlines" }).click();
    const link = await screen.findByRole("link", { name: "Headline 4" });
    expect(link).toHaveAttribute("target", "_blank");
  });
});
