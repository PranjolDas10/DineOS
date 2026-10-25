// Wall-clock times in the restaurant's timezone <-> UTC instants, via Intl (no date library).
const parts = (instant: Date, tz: string) =>
  Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    })
      .formatToParts(instant)
      .map((p) => [p.type, p.value]),
  );

/** How far the timezone's wall clock is ahead of UTC at this instant, in ms. */
function offset(instant: Date, tz: string): number {
  const p = parts(instant, tz);
  const wall = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
  return wall - Math.floor(instant.getTime() / 1000) * 1000;
}

/** "2026-10-25" + "10:30" in America/New_York -> the UTC instant. Two passes so a guess on the
 * wrong side of a DST change corrects itself. A time skipped by DST lands an hour later. */
export function zonedToUtc(day: string, time: string, tz: string): Date {
  const [y, m, d] = day.split("-").map(Number);
  const [h, mi] = time.split(":").map(Number);
  const wall = Date.UTC(y, m - 1, d, h, mi);
  const first = wall - offset(new Date(wall), tz);
  return new Date(wall - offset(new Date(first), tz));
}

/** A UTC instant -> the local day ("2026-10-25") and time ("10:30") in the timezone. */
export function zoned(instant: Date | string, tz: string): { day: string; time: string } {
  const p = parts(new Date(instant), tz);
  return { day: `${p.year}-${p.month}-${p.day}`, time: `${p.hour}:${p.minute}` };
}

export function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

export function mondayOf(day: string): string {
  const weekday = new Date(`${day}T00:00:00Z`).getUTCDay(); // 0 = Sunday
  return addDays(day, -((weekday + 6) % 7));
}

const label = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
/** "2026-10-19" -> "Mon, Oct 19" */
export const dayLabel = (day: string) => label.format(new Date(`${day}T00:00Z`));
