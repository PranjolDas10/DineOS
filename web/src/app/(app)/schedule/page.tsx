import type { Metadata } from "next";
import Link from "next/link";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { api, me, must } from "@/lib/api";
import { moneyWhole } from "@/lib/format";
import { addDays, mondayOf, zonedToUtc } from "@/lib/time";

import { WeekGrid } from "./week-grid";

export const metadata: Metadata = { title: "Schedule" };

const day = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

// Owner at night on the laptop: building next week. Overlaps are refused by the database and
// explained on the shift; labor cost per day sits under each column.
export default async function SchedulePage({ searchParams }: PageProps<"/schedule">) {
  const asked = (await searchParams).week;
  const client = await api();
  const thisWeek = mondayOf((await me()).today); // the restaurant's local week
  const monday = typeof asked === "string" && /^\d{4}-\d{2}-\d{2}$/.test(asked) ? mondayOf(asked) : thisWeek;
  const days = Array.from({ length: 7 }, (_, i) => addDays(monday, i));

  const labor = must(
    await client.GET("/v1/reports/labor-cost", { params: { query: { from: days[0], to: days[6] } } }),
  );
  const tz = labor.timezone; // the restaurant's timezone: every time on this page is local to it
  const [{ items: shifts }, { items: staff }] = await Promise.all([
    client
      .GET("/v1/shifts", {
        params: {
          query: {
            start: zonedToUtc(monday, "00:00", tz).toISOString(),
            end: zonedToUtc(addDays(monday, 7), "00:00", tz).toISOString(),
          },
        },
      })
      .then(must),
    client.GET("/v1/staff", { params: { query: { limit: 200 } } }).then(must),
  ]);

  const week = (offset: number) => `/schedule?week=${addDays(monday, offset)}`;
  return (
    <div className="rise mx-auto grid max-w-7xl gap-6 [&>*]:min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Schedule</h1>
          <p className="text-fg-muted">
            Week of {day.format(new Date(`${monday}T00:00Z`))}: {Number(labor.total_hours).toFixed(1)} hours,{" "}
            {moneyWhole(labor.total_labor_cents)} labor. Times in {tz.replace(/_/g, " ")}.
          </p>
        </div>
        <nav aria-label="Week" className="flex items-center gap-1">
          <Link href={week(-7)} className="grid size-9 place-items-center rounded-md border border-line-strong bg-surface transition-colors hover:bg-surface-sunken">
            <ChevronLeft aria-hidden className="size-4" />
            <span className="sr-only">Previous week</span>
          </Link>
          {monday !== thisWeek && (
            <Link href="/schedule" className="btn-secondary min-h-9 text-sm">
              This week
            </Link>
          )}
          <Link href={week(7)} className="grid size-9 place-items-center rounded-md border border-line-strong bg-surface transition-colors hover:bg-surface-sunken">
            <ChevronRight aria-hidden className="size-4" />
            <span className="sr-only">Next week</span>
          </Link>
        </nav>
      </div>
      <WeekGrid
        days={days}
        tz={tz}
        staff={staff.filter((s) => s.active)}
        shifts={shifts}
        laborByDay={Object.fromEntries(labor.days.map((d) => [d.date, d.labor_cents]))}
      />
    </div>
  );
}
