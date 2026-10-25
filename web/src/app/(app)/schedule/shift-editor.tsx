"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { CircleAlert } from "lucide-react";

import type { Schemas } from "@/lib/api";
import { money } from "@/lib/format";
import { addDays, dayLabel, zoned, zonedToUtc } from "@/lib/time";

import { createShift, deleteShift, moveShift } from "./actions";

type Shift = Schemas["ShiftOut"];
export type Editing = { staff: Schemas["StaffOut"]; day: string; shift: Shift | null };

/** Add, move or delete one shift. The database refuses overlaps; this dialog explains which
 * shift is in the way, using the week it already has. */
export function ShiftEditor({
  editing: { staff, day, shift },
  tz,
  shifts,
  onClose,
}: {
  editing: Editing;
  tz: string;
  shifts: Shift[];
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => dialog.current?.showModal(), []);

  // A new shift starts from this person's usual hours this week, if they have any.
  const usual = shifts.find((s) => s.staff_id === staff.id);
  const from = shift ?? usual;
  const [start, setStart] = useState(from ? zoned(from.starts_at, tz).time : "10:00");
  const [end, setEnd] = useState(from ? zoned(from.ends_at, tz).time : "18:00");
  const [note, setNote] = useState(shift?.note ?? "");
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [pending, startTransition] = useTransition();

  const overnight = end <= start; // 17:00-01:00 ends the next day
  const startsAt = zonedToUtc(day, start, tz);
  const endsAt = zonedToUtc(overnight ? addDays(day, 1) : day, end, tz);
  const length = (endsAt.getTime() - startsAt.getTime()) / 3_600_000;
  const rate = shift?.hourly_rate_cents ?? staff.hourly_rate_cents;

  function explain(message: string | null) {
    if (message?.includes("overlaps")) {
      const clash = shifts.find(
        (s) =>
          s.staff_id === staff.id &&
          s.id !== shift?.id &&
          Date.parse(s.starts_at) < endsAt.getTime() &&
          startsAt.getTime() < Date.parse(s.ends_at),
      );
      if (clash) {
        const a = zoned(clash.starts_at, tz);
        return `${staff.name} already works ${a.time} to ${zoned(clash.ends_at, tz).time} on ${dayLabel(a.day)}. Change the times or move that shift first.`;
      }
    }
    return message;
  }

  function run(action: () => Promise<string | null>) {
    startTransition(async () => {
      const message = explain(await action());
      if (message) setError(message);
      else dialog.current?.close();
    });
  }

  function save(e: React.FormEvent) {
    e.preventDefault();
    const times = { starts_at: startsAt.toISOString(), ends_at: endsAt.toISOString(), note: note.trim() || null };
    run(() => (shift ? moveShift(shift.id, shift.version, times) : createShift(staff.id, times)));
  }

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      aria-labelledby="shift-title"
      className="m-auto w-[min(30rem,calc(100vw-2rem))] rounded-lg border border-line bg-surface p-0 text-fg backdrop:bg-black/50"
    >
      <form onSubmit={save} className="grid gap-5 p-6">
        <div>
          <h2 id="shift-title" className="text-xl font-semibold">
            {shift ? "Change shift" : "Add shift"}
          </h2>
          <p className="text-fg-muted">
            {staff.name}, {dayLabel(day)}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <label className="grid gap-1.5 font-medium">
            Starts
            <input type="time" required className="field min-w-0" value={start} onChange={(e) => setStart(e.target.value)} />
          </label>
          <label className="grid gap-1.5 font-medium">
            Ends
            <input
              type="time"
              required
              className="field min-w-0"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
              aria-describedby="shift-length"
            />
          </label>
        </div>
        <p id="shift-length" className="-mt-2 text-sm text-fg-muted">
          {overnight ? "Ends the next day. " : ""}
          {length.toFixed(1)} hours, {money(Math.round(length * rate))} at {money(rate)}/h
        </p>
        <label className="grid gap-1.5 font-medium">
          Note <span className="text-sm font-normal text-fg-muted">Optional, e.g. &quot;closing&quot;</span>
          <input className="field" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
        </label>
        {error && (
          <p role="alert" className="flex gap-2 rounded-md bg-danger-bg p-3 text-danger">
            <CircleAlert aria-hidden className="mt-0.5 size-5 shrink-0" />
            {error}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-3">
          {shift && (
            <button
              type="button"
              disabled={pending}
              onClick={() => (confirmDelete ? run(() => deleteShift(shift.id, shift.version)) : setConfirmDelete(true))}
              className="min-h-12 cursor-pointer rounded-md px-3 font-semibold text-danger hover:bg-danger-bg"
            >
              {confirmDelete ? "Yes, delete it" : "Delete shift"}
            </button>
          )}
          <span className="flex-1" />
          <button
            type="button"
            onClick={() => dialog.current?.close()}
            className="min-h-12 cursor-pointer rounded-md border border-line-strong px-5 font-semibold hover:bg-surface-sunken"
          >
            Cancel
          </button>
          <button type="submit" disabled={pending || length > 16} className="btn-primary px-6">
            {pending ? "Saving…" : "Save shift"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
