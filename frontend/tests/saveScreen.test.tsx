import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/app/providers";
import { SaveScreenDialog } from "@/components/strategies/SaveScreenDialog";

const nav = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: nav.push, replace: vi.fn() }), usePathname: () => "/screener", useSearchParams: () => new URLSearchParams("") }));

const SCREEN = { conditions: [{ field: "rsi_14", op: "lte" as const, value: "40" }], match: "all" as const, sort: "rsi_14", descending: false };
const posts: unknown[] = [];

beforeEach(() => {
  document.cookie = "csrf=tok";
  nav.push.mockClear();
  posts.length = 0;
  vi.stubGlobal("fetch", async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") posts.push(JSON.parse(String(init.body)));
    return new Response(JSON.stringify({ config_id: "c1" }), { status: 200 });
  });
});
afterEach(() => vi.unstubAllGlobals());

async function save() {
  const onClose = vi.fn();
  render(<Providers><SaveScreenDialog screen={SCREEN} onClose={onClose} /></Providers>);
  fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Dip buyer" } });
  fireEvent.change(screen.getByLabelText("Stocks held"), { target: { value: "20" } });
  fireEvent.click(screen.getByLabelText("Mid caps")); // large + mid -> large only
  fireEvent.click(screen.getByRole("button", { name: "Save strategy" }));
  return onClose;
}

describe("saving a screen as a strategy", () => {
  it("stays open after saving and offers to backtest it, with the screen, caps and slots carried over", async () => {
    await save();
    fireEvent.click(await screen.findByRole("button", { name: "Backtest it" }));
    expect(posts).toHaveLength(1);
    const url = new URL(String(nav.push.mock.calls[0]?.[0]), "http://x");
    expect(url.pathname).toBe("/research/studies/new");
    expect(JSON.parse(url.searchParams.get("screen") ?? "null")).toEqual(SCREEN);
    expect(url.searchParams.get("segments")).toBe("large");
    expect(url.searchParams.get("slots")).toBe("20");
  });
  it("can instead go on to the strategies list", async () => {
    const onClose = await save();
    fireEvent.click(await screen.findByRole("button", { name: "Go to strategies" }));
    await waitFor(() => expect(nav.push).toHaveBeenCalledWith("/strategies"));
    expect(onClose).toHaveBeenCalled();
  });
});
