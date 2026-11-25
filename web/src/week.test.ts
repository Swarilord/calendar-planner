import { describe, expect, test } from "vitest";
import { clock, mondayOf, place, weekDays, zurich } from "./week";

describe("zurich", () => {
  test("winter is UTC+1", () => {
    expect(zurich("2026-11-24T09:15:00Z")).toEqual({ day: "2026-11-24", minutes: 10 * 60 + 15 });
  });

  test("summer is UTC+2", () => {
    expect(zurich("2026-07-06T08:00:00Z")).toEqual({ day: "2026-07-06", minutes: 10 * 60 });
  });

  test("late UTC evening is already the next day in Zurich", () => {
    expect(zurich("2026-11-24T23:30:00Z").day).toBe("2026-11-25");
  });
});

describe("week", () => {
  test("Monday of a Wednesday and of a Sunday", () => {
    expect(mondayOf("2026-11-25")).toBe("2026-11-23");
    expect(mondayOf("2026-11-29")).toBe("2026-11-23");
    expect(mondayOf("2026-11-23")).toBe("2026-11-23");
  });

  test("seven days across a month end", () => {
    expect(weekDays("2026-11-30")).toEqual([
      "2026-11-30",
      "2026-12-01",
      "2026-12-02",
      "2026-12-03",
      "2026-12-04",
      "2026-12-05",
      "2026-12-06",
    ]);
  });

  test("the week with the spring clock change still has seven days", () => {
    // Clocks jump forward on Sunday 29 March 2026.
    expect(weekDays("2026-03-23").at(-1)).toBe("2026-03-29");
  });
});

describe("place", () => {
  const monday = "2026-11-23";
  const span = 17 * 60; // 07:00 to midnight

  test("Tuesday lecture 10:15-12:00", () => {
    const box = place("2026-11-24T09:15:00Z", "2026-11-24T11:00:00Z", monday);
    expect(box?.day).toBe(1);
    expect(box?.top).toBeCloseTo((195 / span) * 100); // 3h15 after 07:00
    expect(box?.height).toBeCloseTo((105 / span) * 100);
  });

  test("before 07:00 is cut off, entirely before is hidden", () => {
    const box = place("2026-11-24T05:00:00Z", "2026-11-24T07:00:00Z", monday); // 06-08
    expect(box?.top).toBe(0);
    expect(box?.height).toBeCloseTo((60 / span) * 100);
    expect(place("2026-11-24T04:00:00Z", "2026-11-24T05:00:00Z", monday)).toBeNull();
  });

  test("past midnight is cut at the end of the day", () => {
    const box = place("2026-11-24T22:00:00Z", "2026-11-25T01:00:00Z", monday); // 23-02
    expect(box?.top! + box?.height!).toBeCloseTo(100);
  });

  test("another week is not shown", () => {
    expect(place("2026-12-01T09:00:00Z", "2026-12-01T10:00:00Z", monday)).toBeNull();
  });
});

test("clock shows Zurich time", () => {
  expect(clock("2026-11-24T13:00:00Z")).toBe("14:00");
  expect(clock("2026-07-06T13:00:00Z")).toBe("15:00");
});
