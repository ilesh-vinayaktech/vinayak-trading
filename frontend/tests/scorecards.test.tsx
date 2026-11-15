import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Scorecards } from "@/components/status/Scorecards";
import type { Dashboard } from "@/lib/schemas";

const cards: NonNullable<Dashboard["scorecards"]> = {
  platform_correctness: {
    status: "FAIL",
    items: [
      { name: "price continuity", status: "FAIL", detail: "the newest continuity run found a problem" },
      { name: "bar completeness", status: "PASS", detail: "the newest completeness run found nothing" },
    ],
  },
  strategy_validity: {
    status: "INCOMPLETE",
    items: [{ name: "holdout", status: "UNKNOWN", detail: "the holdout has not been evaluated: no result is proven out of sample" }],
  },
  operational_reliability: {
    status: "OK",
    items: [{ name: "scheduled jobs", status: "PASS", detail: "all 12 job(s) that have run ended well" }],
  },
};

describe("scorecards", () => {
  it("shows the three questions as three separate cards, each with its own status", () => {
    render(<Scorecards cards={cards} />);
    for (const [title, status] of [
      ["Platform correctness", "fail"],
      ["Strategy validity", "incomplete"],
      ["Operational reliability", "ok"],
    ] as const) {
      const card = screen.getByRole("region", { name: title });
      expect(within(card).getByText(status, { selector: "[data-card-status]" })).toBeInTheDocument();
    }
  });

  it("lists each item with its own state word and detail, and never shows missing evidence as a pass", () => {
    render(<Scorecards cards={cards} />);
    const strategy = screen.getByRole("region", { name: "Strategy validity" });
    expect(within(strategy).getByText(/no result is proven out of sample/)).toBeInTheDocument();
    expect(within(strategy).getByText("no evidence", { selector: "[data-item-status]" })).toBeInTheDocument();
    expect(within(strategy).queryByText("ok")).not.toBeInTheDocument();
    const platform = screen.getByRole("region", { name: "Platform correctness" });
    expect(within(platform).getByText("fail", { selector: "[data-item-status]" })).toBeInTheDocument();
    expect(within(platform).getByText("pass", { selector: "[data-item-status]" })).toBeInTheDocument();
  });
});
