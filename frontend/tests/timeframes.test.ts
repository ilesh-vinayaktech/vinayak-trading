import { describe, expect, it } from "vitest";
import { INTRADAY_MAX_DAYS, barLabel, barTime, intradayStart, isIntraday, latestDay, shiftDays, todayIST } from "@/lib/timeframes";

const daily = { date: "2025-06-09", open: "1", high: "1", low: "1", close: "1", volume: "1", factor: "1" };
const minute = { ...daily, time: 1749440700 }; // 2025-06-09 03:45 UTC = 09:15 IST

describe("timeframes", () => {
  it("daily bars keep their date as the chart time; intraday bars are shifted so the axis reads IST", () => {
    expect(barTime(daily)).toBe("2025-06-09");
    expect(barTime(minute)).toBe(1749440700 + 19800);
    expect(barLabel(daily)).toBe("2025-06-09");
    expect(barLabel(minute)).toBe("2025-06-09 09:15");
  });

  it("only 1d is not intraday", () => {
    expect(["1m", "5m", "15m", "30m", "1h"].every((t) => isIntraday(t as never))).toBe(true);
    expect(isIntraday("1d")).toBe(false);
  });

  it("the start of an intraday request never exceeds what the API serves", () => {
    expect(shiftDays("2026-03-01", -1)).toBe("2026-02-28");
    expect(intradayStart("2026-11-11", "1m")).toBe("2026-11-06"); // 5 days by default
    expect(intradayStart("2026-11-11", "1m", 400)).toBe(shiftDays("2026-11-11", -INTRADAY_MAX_DAYS["1m"]));
  });
});

describe("timeframe menu data", () => {
  it("has every API timeframe exactly once, in minute / hour / day sections, and only minute and hour bars are intraday", async () => {
    const { TIMEFRAME_GROUPS } = await import("@/lib/timeframes");
    const { TIMEFRAMES } = await import("@/lib/schemas");
    expect(TIMEFRAME_GROUPS.flatMap((g) => g.items.map((i) => i.value))).toEqual([...TIMEFRAMES]);
    expect(TIMEFRAMES.filter((t) => isIntraday(t))).toHaveLength(11);
    expect(isIntraday("1w") || isIntraday("1mo")).toBe(false);
    for (const t of TIMEFRAMES.filter(isIntraday)) expect(INTRADAY_MAX_DAYS[t]).toBeGreaterThan(0);
  });
});

describe("today in India", () => {
  it("is the Indian date even when it is still the day before in UTC", () => {
    expect(todayIST(Date.parse("2026-11-11T20:00:00Z"))).toBe("2026-11-12"); // 01:30 IST
    expect(todayIST(Date.parse("2026-11-12T18:29:00Z"))).toBe("2026-11-12"); // 23:59 IST
  });

  it("an intraday chart reaches today unless the stored bars already go further", () => {
    const now = Date.parse("2026-11-12T06:00:00Z");
    expect(latestDay("2026-11-11", now)).toBe("2026-11-12");
    expect(latestDay("2026-11-12", now)).toBe("2026-11-12");
    expect(latestDay("2026-11-13", now)).toBe("2026-11-13");
  });
});

describe("which strategies a candle size can show", () => {
  it("shows a strategy on a candle at least as long as its own rebalance period, never on minutes or hours", async () => {
    const { cadenceFits, barOfDay } = await import("@/lib/timeframes");
    const fits = (tf: string) => (["DAILY", "WEEKLY", "MONTHLY"] as const).filter((c) => cadenceFits(tf as never, c));
    expect(fits("1d")).toEqual(["DAILY", "WEEKLY", "MONTHLY"]); // a daily chart can show every cadence
    expect(fits("1w")).toEqual(["WEEKLY", "MONTHLY"]); // a daily strategy would put five decisions on one candle
    expect(fits("1mo")).toEqual(["MONTHLY"]);
    expect(fits("5m")).toEqual([]);
    expect(fits("1h")).toEqual([]);
    // weekly and monthly candles are dated by their first trading day: a decision belongs to the last candle that starts on or before it
    const weeks = ["2024-06-03", "2024-06-10", "2024-06-17"];
    expect(barOfDay(weeks, "2024-06-10")).toBe("2024-06-10");
    expect(barOfDay(weeks, "2024-06-13")).toBe("2024-06-10"); // mid-week decision: that week's candle
    expect(barOfDay(weeks, "2024-05-30")).toBeUndefined(); // before the first candle on screen: not drawn
    expect(barOfDay(weeks, "2024-07-01")).toBe("2024-06-17"); // after the last: the last candle
  });
});
