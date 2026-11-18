import { describe, expect, it } from "vitest";
import { schedule } from "@/lib/formatting";

describe("a job's schedule for people", () => {
  it.each([
    ["Mon..Fri *-*-* 18:30 Asia/Kolkata", "Mon..Fri 18:30 IST"],
    ["*-*-* 22:00 Asia/Kolkata", "Daily 22:00 IST"],
    ["Sun *-*-* 03:00 Asia/Kolkata", "Sun 03:00 IST"],
    ["*-*-05 10:00 Asia/Kolkata", "Day 5 of the month, 10:00 IST"],
    ["*-*-01 10:00 Asia/Kolkata", "Day 1 of the month, 10:00 IST"],
    ["Mon..Fri *-*-* 09..15:00/5:00 Asia/Kolkata; Mon..Fri *-*-* 00..08,16..23:20 Asia/Kolkata; Sat,Sun *-*-* *:20 Asia/Kolkata", "Mon..Fri every 5 min, 09:00 to 15:55 IST; hourly at other times and at weekends"],
    ["Mon..Fri *-*-* 18:30 Asia/Kolkata; Sat *-*-* 10:00 Asia/Kolkata", "Mon..Fri 18:30 IST; Sat 10:00 IST"],
    ["weird", "weird"],
  ])("%s -> %s", (calendar, shown) => {
    expect(schedule(calendar)).toBe(shown);
  });
});
