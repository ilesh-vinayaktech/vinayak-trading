import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import KiteCallback from "@/app/kite/callback/page";
import KitePage from "@/app/kite/page";
import { Providers } from "@/app/providers";
import { fmtIst } from "@/lib/formatting";

const nav = vi.hoisted(() => ({ replace: vi.fn(), search: "" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  usePathname: () => "/kite",
  useSearchParams: () => new URLSearchParams(nav.search),
}));

type Call = { method: string; path: string; body: unknown };
type Reply = unknown | ((call: Call) => unknown);
const me = (perms: string[] = ["research:read", "kite:own"]) => ({ user: { id: "u1", email: "jane@example.com", name: "Jane Roe", role: "TRADER", permissions: perms, mfa_enabled: false, enrolment_required: false, must_change_password: false } });
const conn = (over: Record<string, unknown> = {}) => ({ state: "not_configured", api_key_hint: null, kite_user_id: null, connected_at: null, token_expires_at: null, is_system: false, redirect_url: "https://portal.example/kite/callback", ...over });

function backend(table: Record<string, Reply>) {
  const calls: Call[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const call: Call = { method: init?.method ?? "GET", path: url.pathname, body: init?.body ? JSON.parse(String(init.body)) : undefined };
    calls.push(call);
    const hit = table[`${call.method} ${call.path}`];
    if (hit === undefined) return new Response(JSON.stringify({ detail: "no route" }), { status: 404 });
    const out = typeof hit === "function" ? (hit as (c: Call) => unknown)(call) : hit;
    const [status, body] = Array.isArray(out) && typeof out[0] === "number" ? (out as [number, unknown]) : [200, out];
    return new Response(JSON.stringify(body), { status });
  });
  return calls;
}
const mount = (ui: React.ReactElement) => render(<Providers>{ui}</Providers>);

beforeEach(() => {
  nav.replace.mockReset();
  nav.search = "";
  document.cookie = "csrf=tok";
});
afterEach(() => vi.unstubAllGlobals());

describe("time in India", () => {
  it("shows an instant in IST", () => {
    expect(fmtIst("2026-11-12T00:30:00Z")).toBe("12 Nov, 06:00 IST");
    expect(fmtIst("nonsense")).toBe("nonsense");
  });
});

describe("Kite page", () => {
  it("walks a new user through registering the redirect URL and saving credentials, then clears the secret from the page", async () => {
    let saved = false;
    const calls = backend({
      "GET /api/auth/me": me(),
      "GET /api/kite/connection": () => conn(saved ? { state: "saved", api_key_hint: "5678" } : {}),
      "POST /api/kite/credentials": () => {
        saved = true;
        return { ok: true };
      },
    });
    mount(<KitePage />);
    expect((await screen.findByTestId("redirect-url")).textContent).toBe("https://portal.example/kite/callback");
    expect(screen.getByText("Not set up")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect to Zerodha" })).toBeDisabled(); // nothing saved yet
    expect(screen.getByLabelText("API secret")).toHaveAttribute("type", "password");
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "abcd1234efgh5678" } });
    fireEvent.change(screen.getByLabelText("API secret"), { target: { value: "zyxw9876vuts5432" } });
    fireEvent.click(screen.getByRole("button", { name: "Save credentials" }));
    expect((await screen.findByRole("status")).textContent).toBe("Saved.");
    expect(calls.find((c) => c.path === "/api/kite/credentials")?.body).toEqual({ api_key: "abcd1234efgh5678", api_secret: "zyxw9876vuts5432" });
    expect(screen.getByLabelText("API secret")).toHaveValue(""); // the secret does not stay in the page
    expect(screen.getByLabelText("API key")).toHaveValue("");
    expect(await screen.findByText(/Saved key ending/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect to Zerodha" })).toBeEnabled();
  });

  it("shows why saving was refused", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/kite/connection": conn(), "POST /api/kite/credentials": [422, { detail: "the API key should be letters and digits only" }] });
    mount(<KitePage />);
    fireEvent.change(await screen.findByLabelText("API key"), { target: { value: "bad key!" } });
    fireEvent.change(screen.getByLabelText("API secret"), { target: { value: "secret12345" } });
    fireEvent.click(screen.getByRole("button", { name: "Save credentials" }));
    expect((await screen.findByRole("alert")).textContent).toBe("the API key should be letters and digits only");
  });

  it("sends the browser to Zerodha when connecting", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, origin: "http://localhost:3000" });
    backend({ "GET /api/auth/me": me(), "GET /api/kite/connection": conn({ state: "saved", api_key_hint: "5678" }), "POST /api/kite/connect/start": { login_url: "https://kite.zerodha.com/connect/login?v=3&api_key=K&redirect_params=state%3Dabc" } });
    mount(<KitePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect to Zerodha" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://kite.zerodha.com/connect/login?v=3&api_key=K&redirect_params=state%3Dabc"));
  });

  it("shows a live connection with its expiry and disconnects only after confirming", async () => {
    let state = "connected";
    const calls = backend({
      "GET /api/auth/me": me(),
      "GET /api/kite/connection": () => conn({ state, api_key_hint: "5678", kite_user_id: "AB1234", token_expires_at: "2026-11-12T00:30:00Z" }),
      "POST /api/kite/disconnect": () => {
        state = "saved";
        return { ok: true };
      },
    });
    mount(<KitePage />);
    expect(await screen.findByText("Connected")).toBeInTheDocument();
    expect(screen.getByText("Zerodha user AB1234")).toBeInTheDocument();
    expect(screen.getByText("until 12 Nov, 06:00 IST")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect to Zerodha" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    expect(calls.some((c) => c.path === "/api/kite/disconnect")).toBe(false); // it asked first
    fireEvent.click(screen.getByRole("button", { name: "Disconnect" })); // now the confirming button
    expect(await screen.findByText("Credentials saved, not connected")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/kite/disconnect")).toBe(true);
  });

  it("says when the daily connection has expired and offers to remove the credentials", async () => {
    const calls = backend({ "GET /api/auth/me": me(), "GET /api/kite/connection": conn({ state: "expired", api_key_hint: "5678", kite_user_id: "AB1234", token_expires_at: "2026-11-11T00:30:00Z" }), "POST /api/kite/credentials/remove": { ok: true } });
    mount(<KitePage />);
    expect(await screen.findByText("Expired: connect again")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove credentials" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/kite/credentials/remove")).toBe(true));
  });

  it("shows an error handed back from the callback", async () => {
    nav.search = "error=This%20connection%20attempt%20is%20not%20valid%20any%20more";
    backend({ "GET /api/auth/me": me(), "GET /api/kite/connection": conn() });
    mount(<KitePage />);
    expect((await screen.findByRole("alert")).textContent).toContain("not valid any more");
  });

  it("shows the success notice after connecting", async () => {
    nav.search = "connected=1";
    backend({ "GET /api/auth/me": me(), "GET /api/kite/connection": conn({ state: "connected", api_key_hint: "5678", kite_user_id: "AB1234", token_expires_at: "2026-11-12T00:30:00Z" }) });
    mount(<KitePage />);
    expect((await screen.findAllByRole("status")).some((s) => s.textContent === "Connected to Zerodha for today.")).toBe(true);
  });

  it("reports a failure to load the connection", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/kite/connection": [403, { detail: "Not permitted" }] });
    mount(<KitePage />);
    expect((await screen.findByRole("alert")).textContent).toContain("Not permitted");
  });

  it("offers the system data feed switch to an administrator only", async () => {
    let mine = false;
    const calls = backend({
      "GET /api/auth/me": me(["research:read", "kite:own", "system:settings"]),
      "GET /api/kite/connection": () => conn({ state: "saved", api_key_hint: "5678", is_system: mine }),
      "GET /api/kite/system": () => ({ feed: mine ? { owner_id: "u1", owner: "Jane Roe", api_key_hint: "5678", state: "saved", token_expires_at: null } : null }),
      "POST /api/kite/system": (c: Call) => {
        mine = (c.body as { enabled: boolean }).enabled;
        return { ok: true };
      },
    });
    mount(<KitePage />);
    expect(await screen.findByText("No connection is the data feed yet.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use my connection as the data feed" }));
    expect(await screen.findByText("Jane Roe")).toBeInTheDocument();
    expect(calls.find((c) => c.path === "/api/kite/system" && c.method === "POST")?.body).toEqual({ enabled: true });
    fireEvent.click(await screen.findByRole("button", { name: "Stop using my connection as the feed" }));
    expect(await screen.findByText("No connection is the data feed yet.")).toBeInTheDocument();
  });

  it("does not show the system feed card to a trader", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/kite/connection": conn() });
    mount(<KitePage />);
    await screen.findByTestId("redirect-url");
    expect(screen.queryByText("System data feed")).not.toBeInTheDocument();
  });

  it("shows a refusal when the system feed cannot be set", async () => {
    backend({ "GET /api/auth/me": me(["research:read", "kite:own", "system:settings"]), "GET /api/kite/connection": conn(), "GET /api/kite/system": { feed: null }, "POST /api/kite/system": [409, { detail: "save the Kite credentials first" }] });
    mount(<KitePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Use my connection as the data feed" }));
    expect((await screen.findByRole("alert")).textContent).toBe("save the Kite credentials first");
  });

  it("shows when starting the connection is refused", async () => {
    backend({ "GET /api/auth/me": me(), "GET /api/kite/connection": conn({ state: "saved", api_key_hint: "5678" }), "POST /api/kite/connect/start": [409, { detail: "save your Kite API key and secret first" }] });
    mount(<KitePage />);
    fireEvent.click(await screen.findByRole("button", { name: "Connect to Zerodha" }));
    expect((await screen.findByRole("alert")).textContent).toBe("save your Kite API key and secret first");
  });
});

describe("Kite callback", () => {
  it("hands the token and state to the server once, then returns to the Kite page", async () => {
    nav.search = "request_token=REQ1&action=login&status=success&state=STATE1";
    const calls = backend({ "POST /api/kite/connect/complete": { kite_user: "AB1234" } });
    mount(<KiteCallback />);
    expect(screen.getByText(/Finishing your Kite connection/)).toBeInTheDocument();
    await waitFor(() => expect(nav.replace).toHaveBeenCalledWith("/kite?connected=1"));
    expect(calls.filter((c) => c.path === "/api/kite/connect/complete")).toHaveLength(1);
    expect(calls.find((c) => c.path === "/api/kite/connect/complete")?.body).toEqual({ request_token: "REQ1", state: "STATE1" });
  });

  it("explains when Zerodha did not complete the login, without calling the server", async () => {
    nav.search = "status=error&state=S";
    const calls = backend({});
    mount(<KiteCallback />);
    expect((await screen.findByRole("alert")).textContent).toContain("did not complete the login");
    expect(calls.filter((c) => c.path.startsWith("/api/kite"))).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Back to the Kite page" }));
    expect(nav.replace).toHaveBeenCalledWith("/kite");
  });

  it("shows the server's reason when the state is no longer valid", async () => {
    nav.search = "request_token=R&status=success&state=OLD";
    backend({ "POST /api/kite/connect/complete": [422, { detail: "this connection attempt is not valid any more: start again from the Kite page" }] });
    mount(<KiteCallback />);
    expect((await screen.findByRole("alert")).textContent).toContain("not valid any more");
  });

  it("reports a network failure", async () => {
    nav.search = "request_token=R&status=success&state=S";
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("down");
    });
    mount(<KiteCallback />);
    expect((await screen.findByRole("alert")).textContent).toContain("Could not reach the server");
  });
});
