import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AccountSecurity from "@/app/account/security/page";
import { Providers } from "@/app/providers";
import { Shell } from "@/components/layout/Shell";
import { Alert, Avatar } from "@/components/ui/Alert";
import { Field, PasswordInput } from "@/components/ui/Field";
import { Icon } from "@/components/ui/Icon";
import { buttonClass, inputClass } from "@/components/ui/styles";

const nav = vi.hoisted(() => ({ replace: vi.fn(), path: "/dashboard" }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: nav.replace }),
  usePathname: () => nav.path,
  useSearchParams: () => new URLSearchParams(""),
}));
vi.mock("qrcode", () => ({ default: { toDataURL: vi.fn(async () => "data:image/png;base64,AAAA") } }));

const user = (over: Record<string, unknown> = {}, perms: string[] = ["research:read", "kite:own", "tickets:own"]) => ({ user: { id: "u1", email: "jane@example.com", name: "Jane Roe", role: "TRADER", permissions: perms, mfa_enabled: false, enrolment_required: false, must_change_password: false, ...over } });
function backend(table: Record<string, unknown>) {
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input));
    const hit = table[`${init?.method ?? "GET"} ${url.pathname}`];
    if (hit === undefined) return new Response(JSON.stringify({ detail: "no route" }), { status: 404 });
    const [status, body] = Array.isArray(hit) && typeof hit[0] === "number" ? (hit as [number, unknown]) : [200, hit];
    return new Response(JSON.stringify(body), { status });
  });
}
const mount = (ui: React.ReactElement) => render(<Providers>{ui}</Providers>);
const HEALTH = { "GET /api/health": { api: "ok", database: "ok", redis: "x" } };

beforeEach(() => {
  nav.replace.mockReset();
  nav.path = "/dashboard";
  document.cookie = "csrf=tok";
  Object.assign(navigator, { clipboard: { writeText: vi.fn(async () => undefined) } });
});
afterEach(() => vi.unstubAllGlobals());

describe("ui primitives", () => {
  it("styles are shared: buttons by variant and size, inputs without a fixed width", () => {
    expect(buttonClass("primary")).toContain("bg-brand");
    expect(buttonClass("danger")).toContain("bg-red-600");
    expect(buttonClass("secondary", true)).toContain("text-xs");
    expect(buttonClass()).toContain("px-3.5");
    expect(inputClass).not.toMatch(/\bw-/);
  });

  it("a field puts its label above its control and shows an error instead of the hint", () => {
    const { rerender } = render(<Field id="x" label="Email" hint="We never share it"><input id="x" /></Field>);
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByText("We never share it")).toBeInTheDocument();
    rerender(<Field id="x" label="Email" hint="We never share it" error="Required"><input id="x" /></Field>);
    expect(screen.getByRole("alert").textContent).toBe("Required");
    expect(screen.queryByText("We never share it")).not.toBeInTheDocument();
  });

  it("the password box hides its text until asked, and the toggle reports its state", () => {
    const onChange = vi.fn();
    render(<PasswordInput id="p" value="secret" onChange={onChange} autoComplete="current-password" />);
    const input = document.getElementById("p") as HTMLInputElement;
    expect(input.type).toBe("password");
    const toggle = screen.getByRole("button", { name: "Show password" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(toggle);
    expect(input.type).toBe("text");
    expect(screen.getByRole("button", { name: "Hide password" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.change(input, { target: { value: "x" } });
    expect(onChange).toHaveBeenCalledWith("x");
  });

  it("alerts carry an icon and the right role: errors are announced, the rest are status", () => {
    const { rerender } = render(<Alert tone="error" title="Failed">Try again</Alert>);
    expect(screen.getByRole("alert").textContent).toBe("FailedTry again");
    for (const tone of ["info", "success", "warn"] as const) {
      rerender(<Alert tone={tone}>Note</Alert>);
      expect(screen.getByRole("status")).toBeInTheDocument();
    }
  });

  it("an avatar shows initials and falls back for a blank name; an icon is decorative", () => {
    const { container } = render(<><Avatar name="Ilesh Patel" /><Avatar name="  " /><Icon name="shield" /></>);
    const [a, b] = [...container.querySelectorAll("span")];
    expect(a?.textContent).toBe("IP");
    expect(b?.textContent).toBe("?");
    expect(container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("app shell", () => {
  it("groups navigation by purpose, marks the current page and shows only what the role may use", async () => {
    backend({ "GET /api/auth/me": user(), ...HEALTH });
    mount(<Shell>page</Shell>);
    const main = within(await screen.findByRole("navigation", { name: "Main" }));
    for (const heading of ["Research", "Operations", "Account"]) expect(main.getByText(heading)).toBeInTheDocument();
    expect(main.queryByText("Administration")).not.toBeInTheDocument(); // empty group is not shown
    expect(main.getByRole("link", { name: "Dashboard" })).toHaveAttribute("aria-current", "page");
    expect(main.getByRole("link", { name: "Support" })).toBeInTheDocument();
    expect(main.queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });

  it("the account menu names the user, links to security, closes on Escape and signs out", async () => {
    backend({ "GET /api/auth/me": user(), "POST /api/auth/logout": { ok: true }, ...HEALTH });
    mount(<Shell>page</Shell>);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Account menu" }));
    const menu = within(screen.getByRole("menu", { name: "Account" }));
    expect(menu.getByText("Jane Roe")).toBeInTheDocument();
    expect(menu.getByRole("menuitem", { name: "Account security" })).toHaveAttribute("href", "/account/security");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Account menu" }));
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument(); // a click elsewhere also closes it
  });

  it("on a phone the menu button opens a drawer with the same navigation and closes again", async () => {
    backend({ "GET /api/auth/me": user(), ...HEALTH });
    mount(<Shell>page</Shell>);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Open menu" }));
    const drawer = within(screen.getByRole("dialog", { name: "Navigation" }));
    expect(within(drawer.getByRole("navigation", { name: "Mobile" })).getByRole("link", { name: "Data Explorer" })).toBeInTheDocument();
    fireEvent.click(drawer.getAllByRole("button", { name: "Close menu" })[0] as HTMLElement);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("link", { name: "Data Explorer" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); // choosing a page closes it
  });

  it("an account that must finish setup sees an explanation instead of an empty sidebar", async () => {
    nav.path = "/account/security";
    backend({ "GET /api/auth/me": user({ role: "ADMIN", enrolment_required: true }), ...HEALTH });
    mount(<Shell>setup</Shell>);
    expect(await screen.findByText(/Finish the account setup on this page/)).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
    expect(within(screen.getByRole("dialog")).getByText(/Finish the account setup/)).toBeInTheDocument();
  });

  it("while loading it offers a plain reload link in case the page scripts failed", async () => {
    nav.path = "/dashboard";
    vi.stubGlobal("fetch", () => new Promise(() => undefined)); // never answers
    mount(<Shell>page</Shell>);
    expect(await screen.findByRole("link", { name: "Taking long? Reload" })).toHaveAttribute("href", "/dashboard");
  });
});

describe("account security page", () => {
  const sessions = { "GET /api/auth/sessions": { sessions: [] } };

  it("checks password requirements as you type", async () => {
    backend({ "GET /api/auth/me": user(), ...sessions });
    mount(<AccountSecurity />);
    const list = within(await screen.findByRole("list", { name: "Password requirements" }));
    expect(list.getByText(/At least 12 characters/).textContent).toContain("not met yet");
    fireEvent.change(screen.getByLabelText("New password"), { target: { value: "violet-harbor-lantern-42" } });
    expect(list.getByText(/At least 12 characters/).textContent).toContain("(met)");
    fireEvent.change(screen.getByLabelText("Repeat new password"), { target: { value: "violet-harbor-lantern-42" } });
    expect(list.getByText(/Both new passwords match/).textContent).toContain("(met)");
  });

  it("walks through the three setup steps and shows the recovery codes with a copy button", async () => {
    const codes = Array.from({ length: 10 }, (_, i) => `abcde-fgh${i}k`);
    backend({ "GET /api/auth/me": user({ role: "ADMIN", enrolment_required: true }), ...sessions, "POST /api/auth/mfa/enrol": { secret: "JBSWY3DPEHPK3PXP", uri: "otpauth://totp/x?secret=JBSWY3DPEHPK3PXP" }, "POST /api/auth/mfa/confirm": { recovery_codes: codes } });
    mount(<AccountSecurity />);
    expect((await screen.findByRole("status")).textContent).toContain("Finish setting up your account");
    expect(screen.getByText("Change your password instead (optional)").closest("details")).not.toHaveAttribute("open"); // out of the way until asked for
    fireEvent.click(screen.getByRole("button", { name: "Set up two-factor authentication" }));
    for (const step of ["Open your authenticator app", "Scan this code", "Enter the 6-digit code it shows"]) expect(await screen.findByText(step)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Code from the app"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    await screen.findByRole("list", { name: "Recovery codes" });
    fireEvent.click(screen.getByRole("button", { name: "Copy all codes" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(codes.join("\n"));
    expect(await screen.findByRole("button", { name: "Copied" })).toBeInTheDocument();
  });

  it("an account with a temporary password sees the password form first and no sessions list", async () => {
    backend({ "GET /api/auth/me": user({ must_change_password: true }), ...sessions });
    mount(<AccountSecurity />);
    await screen.findByText("Choose a new password to continue.");
    const headings = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    await waitFor(() => expect(headings()[0]).toBe("Password"));
    expect(headings()).not.toContain("Active sessions");
    expect(screen.getByText("Choose a new password to continue.")).toBeInTheDocument();
  });
});
