import { describe, expect, it } from "vitest";
import { INTRADAY_MAX_DAYS, barLabel, barTime, intradayStart, isIntraday, shiftDays } from "@/lib/timeframes";

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
