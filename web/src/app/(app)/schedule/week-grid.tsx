"use client";

import { useState } from "react";
import { Plus } from "lucide-react";

import type { Schemas } from "@/lib/api";
import { moneyWhole } from "@/lib/format";
import { dayLabel, zoned } from "@/lib/time";

import { ShiftEditor, type Editing } from "./shift-editor";

type Shift = Schemas["ShiftOut"];
type Staff = Schemas["StaffOut"];

const hours = (s: Shift) => (Date.parse(s.ends_at) - Date.parse(s.starts_at)) / 3_600_000;
const cost = (s: Shift) => Math.round(hours(s) * s.hourly_rate_cents);

/** Staff x day. A shift belongs to the local day it starts on (a 17:00-01:00 close is Friday's). */
export function WeekGrid({
  days,
  tz,
  staff,
  shifts,
  laborByDay,
}: {
  days: string[];
  tz: string;
  staff: Staff[];
  shifts: Shift[];
  laborByDay: Record<string, number>;
}) {
  const [editing, setEditing] = useState<Editing | null>(null);
  const cell = (staffId: string, day: string) =>
    shifts
      .filter((s) => s.staff_id === staffId && zoned(s.starts_at, tz).day === day)
      .sort((a, b) => a.starts_at.localeCompare(b.starts_at));

  if (staff.length === 0) {
    return <p className="text-fg-muted">No active staff yet. Add staff through the API to build a schedule.</p>;
  }
  return (
    <>
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full min-w-[56rem] border-collapse text-sm">
          <thead>
            <tr className="bg-bg text-left text-fg-muted">
              <th scope="col" className="w-36 px-3 py-2 font-medium">
                Staff
              </th>
              {days.map((d) => (
                <th key={d} scope="col" className="border-l border-line px-2 py-2 font-medium">
                  {dayLabel(d)}
                </th>
              ))}
              <th scope="col" className="border-l border-line px-3 py-2 text-right font-medium">
                Week
              </th>
            </tr>
          </thead>
          <tbody>
            {staff.map((person) => {
              const theirs = shifts.filter((s) => s.staff_id === person.id);
              return (
                <tr key={person.id} className="border-t border-line align-top">
                  <th scope="row" className="px-3 py-3 text-left font-medium">
                    {person.name}
                    <span className="block font-normal text-fg-muted">{moneyWhole(person.hourly_rate_cents)}/h</span>
                  </th>
                  {days.map((d) => (
                    <td key={d} className="border-l border-line p-1.5">
                      <div className="grid gap-1.5">
                        {cell(person.id, d).map((s) => (
                          <button
                            key={s.id}
                            type="button"
                            onClick={() => setEditing({ staff: person, day: d, shift: s })}
                            className="cursor-pointer rounded-sm border border-line-strong bg-surface px-2 py-1.5 text-left hover:border-primary"
                          >
                            <span className="block font-semibold whitespace-nowrap">
                              {zoned(s.starts_at, tz).time}–{zoned(s.ends_at, tz).time}
                            </span>
                            <span className="block text-fg-muted">
                              {hours(s).toFixed(1)} h, {moneyWhole(cost(s))}
                            </span>
                            {s.note && <span className="block truncate text-fg-muted">{s.note}</span>}
                          </button>
                        ))}
                        <button
                          type="button"
                          onClick={() => setEditing({ staff: person, day: d, shift: null })}
                          aria-label={`Add a shift for ${person.name} on ${dayLabel(d)}`}
                          className="grid min-h-8 cursor-pointer place-items-center rounded-sm text-fg-muted hover:bg-surface-sunken hover:text-fg"
                        >
                          <Plus aria-hidden className="size-4" />
                        </button>
                      </div>
                    </td>
                  ))}
                  <td className="border-l border-line px-3 py-3 text-right">
                    <span className="block font-semibold">{theirs.reduce((h, s) => h + hours(s), 0).toFixed(1)} h</span>
                    <span className="block text-fg-muted">{moneyWhole(theirs.reduce((c, s) => c + cost(s), 0))}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
          <tfoot>
            <tr className="border-t border-line-strong bg-bg">
              <th scope="row" className="px-3 py-2 text-left font-medium">
                Labor per day
              </th>
              {days.map((d) => (
                <td key={d} className="border-l border-line px-2 py-2 font-semibold">
                  {moneyWhole(laborByDay[d] ?? 0)}
                </td>
              ))}
              <td className="border-l border-line px-3 py-2 text-right font-semibold">
                {moneyWhole(Object.values(laborByDay).reduce((a, b) => a + b, 0))}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      {editing && (
        <ShiftEditor
          key={editing.shift?.id ?? `${editing.staff.id}${editing.day}`}
          editing={editing}
          tz={tz}
          shifts={shifts}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  );
}
