import { expect, test } from "@playwright/test";

import { addDays, mondayOf, zoned, zonedToUtc } from "../src/lib/time";

const NY = "America/New_York";

test("local wall time to UTC, across DST changes", () => {
  expect(zonedToUtc("2026-10-25", "10:30", NY).toISOString()).toBe("2026-10-25T14:30:00.000Z"); // EDT
  expect(zonedToUtc("2026-11-02", "10:30", NY).toISOString()).toBe("2026-11-02T15:30:00.000Z"); // EST
  expect(zonedToUtc("2026-03-08", "03:30", NY).toISOString()).toBe("2026-03-08T07:30:00.000Z"); // first EDT hour
  expect(zonedToUtc("2026-11-01", "00:30", NY).toISOString()).toBe("2026-11-01T04:30:00.000Z"); // before fall back
  expect(zonedToUtc("2026-10-25", "10:30", "Asia/Kolkata").toISOString()).toBe("2026-10-25T05:00:00.000Z");
});

test("UTC to local day and time", () => {
  expect(zoned("2026-10-26T03:30:00Z", NY)).toEqual({ day: "2026-10-25", time: "23:30" });
  expect(zoned(zonedToUtc("2026-03-08", "12:00", NY), NY)).toEqual({ day: "2026-03-08", time: "12:00" });
});

test("week arithmetic", () => {
  expect(mondayOf("2026-10-25")).toBe("2026-10-19"); // a Sunday
  expect(mondayOf("2026-10-19")).toBe("2026-10-19");
  expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
});
