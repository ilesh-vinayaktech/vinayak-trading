import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SymbolSearch } from "@/components/charts/SymbolSearch";

const inst = (id: number, symbol: string) => ({ id, symbol, name: `${symbol} Ltd`, isin: `INE00${id}`, status: "active", listed_on: null, delisted_on: null });
const LIST = [inst(1, "ABC"), inst(2, "ABD"), inst(3, "ABE")];
afterEach(() => vi.unstubAllGlobals());

function mount() {
  vi.stubGlobal("fetch", async () => new Response(JSON.stringify(LIST), { status: 200 }));
  const onPick = vi.fn();
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><SymbolSearch current={null} onPick={onPick} /></QueryClientProvider>);
  return onPick;
}

describe("SymbolSearch keyboard", () => {
  it("starts on the first match, moves with the arrow keys, stops at the ends and picks the highlighted row with Enter", async () => {
    const onPick = mount();
    const box = screen.getByLabelText("Symbol, ISIN or name");
    fireEvent.change(box, { target: { value: "ab" } });
    const first = await screen.findByRole("button", { name: /ABC/ });
    expect(first).toHaveAttribute("aria-current", "true");
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "ArrowDown" });
    fireEvent.keyDown(box, { key: "ArrowDown" }); // past the last row: stays on it
    expect(screen.getByRole("button", { name: /ABE/ })).toHaveAttribute("aria-current", "true");
    expect(box).toHaveAttribute("aria-activedescendant", "symbol-match-2");
    fireEvent.keyDown(box, { key: "ArrowUp" });
    expect(screen.getByRole("button", { name: /ABD/ })).toHaveAttribute("aria-current", "true");
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick.mock.calls[0]?.[0]).toMatchObject({ symbol: "ABD" });
    expect(screen.queryByRole("list", { name: "Matches" })).toBeNull(); // picking closes the list
  });

  it("Enter with nothing listed yet does nothing, and the mouse moving over a row highlights it", async () => {
    const onPick = mount();
    const box = screen.getByLabelText("Symbol, ISIN or name");
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onPick).not.toHaveBeenCalled();
    fireEvent.change(box, { target: { value: "ab" } });
    const second = await screen.findByRole("button", { name: /ABD/ });
    fireEvent.mouseMove(second);
    expect(second).toHaveAttribute("aria-current", "true");
  });
});
