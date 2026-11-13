"use client";

import { useMemo, useState, useTransition } from "react";
import { CircleAlert, CircleCheck, CircleDashed, TriangleAlert } from "lucide-react";

import type { Schemas } from "@/lib/api";
import { amount, money, parseDollars } from "@/lib/format";
import { suggestIngredient, toBase } from "@/lib/units";

import { confirmReceipt } from "../actions";
import { LineEditor, type Decision } from "./line-editor";

type Line = Schemas["ReceiptLineOut"];
type Ingredient = Schemas["IngredientOut"];

/** The model's best reading of a line, if it's complete enough to accept in one click. */
function autoDecision(line: Line, ingredients: Ingredient[]): Decision | null {
  const match = suggestIngredient(line.description, ingredients);
  const base = match ? toBase(Number(line.quantity), line.unit, match.base_unit) : null;
  if (!match || base === null) return null;
  return {
    ingredient_id: match.id,
    description: line.description,
    quantity: line.quantity,
    unit: line.unit,
    line_total_cents: line.line_total_cents,
    base_qty: String(base),
  };
}

// Owner at night on the laptop: photo left, lines right, least sure first. Nothing is saved
// until every line is decided, matching the API's rule.
export function Review({
  receipt,
  version,
  ingredients,
}: {
  receipt: Schemas["ReceiptDetail"];
  version: number;
  ingredients: Ingredient[];
}) {
  const [opened] = useState(() => Date.now()); // review time: the number this screen should shrink
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [editing, setEditing] = useState<Line | null>(null);
  const [supplier, setSupplier] = useState(receipt.supplier_name ?? "");
  const [date, setDate] = useState(receipt.receipt_date ?? "");
  const [total, setTotal] = useState(receipt.total_cents === null ? "" : (receipt.total_cents / 100).toFixed(2));
  const [error, setError] = useState<string | null>(null);
  const [saving, startSaving] = useTransition();

  const names = useMemo(() => new Map(ingredients.map((i) => [i.id, i])), [ingredients]);
  const autos = useMemo(
    () => Object.fromEntries(receipt.lines.map((l) => [l.id, autoDecision(l, ingredients)])),
    [receipt.lines, ingredients],
  );
  const check = receipt.lines
    .filter((l) => l.needs_review || !autos[l.id])
    .sort((a, b) => Number(a.confidence) - Number(b.confidence));
  const fine = receipt.lines.filter((l) => !check.includes(l));
  const acceptable = fine.filter((l) => !decisions[l.id]);
  const undecided = receipt.lines.filter((l) => !decisions[l.id]).length;
  const prices = Object.values(decisions).filter((d) => d.ingredient_id).length;
  const linesSum = receipt.lines.reduce((s, l) => s + (decisions[l.id]?.line_total_cents ?? l.line_total_cents), 0);
  const totalCents = parseDollars(total);

  function save() {
    if (total && totalCents === null) return setError("The receipt total isn't an amount. Use a format like 61.50.");
    setError(null);
    startSaving(async () => {
      setError(
        await confirmReceipt(
          receipt.id,
          version,
          {
            supplier_name: supplier.trim() || null,
            receipt_date: date || null,
            total_cents: totalCents,
            lines: receipt.lines.map((l) => ({ line_id: l.id, ...decisions[l.id] })),
          },
          (Date.now() - opened) / 1000,
        ),
      );
    });
  }

  const row = (line: Line) => {
    const d = decisions[line.id];
    const ingredient = d?.ingredient_id ? names.get(d.ingredient_id) : undefined;
    const auto = autos[line.id];
    return (
      <li key={line.id}>
        <button
          type="button"
          onClick={() => setEditing(line)}
          className={`grid w-full cursor-pointer grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1 px-4 py-3 text-left transition-colors hover:bg-bg ${line.needs_review && !d ? "shadow-[inset_4px_0_0_var(--warn)]" : ""}`}
        >
          <span className="font-medium [overflow-wrap:anywhere]">{d?.description ?? line.description}</span>
          <span className="font-medium">{money(d?.line_total_cents ?? line.line_total_cents)}</span>
          <span className="col-span-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-fg-muted">
            <span>
              {amount(Number(d?.quantity ?? line.quantity))} {d?.unit ?? line.unit}
            </span>
            {d ? (
              <span className="inline-flex items-center gap-1 font-medium text-ok">
                <CircleCheck aria-hidden className="size-4" />
                {ingredient
                  ? `${ingredient.name}, ${amount(Number(d.base_qty))} ${ingredient.base_unit}`
                  : "Not an ingredient"}
              </span>
            ) : line.needs_review ? (
              <span className="inline-flex items-center gap-1 font-medium text-warn">
                <TriangleAlert aria-hidden className="size-4" />
                Check this
              </span>
            ) : auto ? (
              <span>
                Reads as {names.get(auto.ingredient_id!)?.name}, {amount(Number(auto.base_qty))}{" "}
                {names.get(auto.ingredient_id!)?.base_unit}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1">
                <CircleDashed aria-hidden className="size-4" />
                What is it?
              </span>
            )}
            <span>Read with {Math.round(Number(line.confidence) * 100)}% confidence</span>
          </span>
        </button>
      </li>
    );
  };

  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start">
      <figure className="grid gap-2 lg:sticky lg:top-6">
        {/* eslint-disable-next-line @next/next/no-img-element -- short-lived presigned URL, not optimizable */}
        <img
          src={receipt.photo_url}
          alt={`Receipt photo from ${receipt.supplier_name ?? "an unknown supplier"}`}
          className="max-h-[40dvh] w-full rounded-lg border border-line bg-surface object-contain object-top lg:max-h-[calc(100dvh-6rem)]"
        />
        <figcaption className="text-sm text-fg-muted">
          <a href={receipt.photo_url} target="_blank" rel="noreferrer" className="font-medium text-accent-text underline underline-offset-2">
            Open the photo full size
          </a>
        </figcaption>
      </figure>

      <div className="grid gap-6">
        <div className="panel grid gap-4 p-5 sm:grid-cols-3">
          <h1 className="text-xl font-semibold sm:col-span-3">Check this receipt</h1>
          <label className="grid gap-1.5 text-sm font-medium sm:col-span-3">
            Supplier
            <input className="field" value={supplier} onChange={(e) => setSupplier(e.target.value)} />
          </label>
          <label className="grid gap-1.5 text-sm font-medium">
            Date
            <input type="date" className="field" value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
          <label className="grid gap-1.5 text-sm font-medium">
            Total ($)
            <input inputMode="decimal" className="field" value={total} onChange={(e) => setTotal(e.target.value)} />
          </label>
          <p
            className={`flex items-center gap-1.5 self-end pb-3 text-sm font-medium ${totalCents === linesSum ? "text-ok" : "text-warn"}`}
          >
            {totalCents === linesSum ? (
              <CircleCheck aria-hidden className="size-4 shrink-0" />
            ) : (
              <TriangleAlert aria-hidden className="size-4 shrink-0" />
            )}
            {totalCents === linesSum
              ? "Lines add up to the total"
              : `Lines add up to ${money(linesSum)}. Look for a missed or misread line.`}
          </p>
        </div>

        {check.length > 0 && (
          <section aria-labelledby="check">
            <h2 id="check" className="pb-2 font-semibold">
              Check these <span className="font-normal text-fg-muted">({check.length}, least sure first)</span>
            </h2>
            <ul className="panel divide-y divide-line overflow-hidden">{check.map(row)}</ul>
          </section>
        )}

        {fine.length > 0 && (
          <section aria-labelledby="fine">
            <div className="flex flex-wrap items-center justify-between gap-2 pb-2">
              <h2 id="fine" className="font-semibold">
                Look right <span className="font-normal text-fg-muted">({fine.length})</span>
              </h2>
              {acceptable.length > 0 && (
                <button
                  type="button"
                  onClick={() =>
                    setDecisions((all) => ({
                      ...all,
                      ...Object.fromEntries(acceptable.map((l) => [l.id, autos[l.id]!])),
                    }))
                  }
                  className="btn-secondary"
                >
                  Accept {acceptable.length}
                </button>
              )}
            </div>
            <ul className="panel divide-y divide-line overflow-hidden">{fine.map(row)}</ul>
          </section>
        )}

        <div className="sticky bottom-0 grid gap-3 border-t border-line bg-bg py-4">
          {error && (
            <p role="alert" className="flex gap-2 rounded-md bg-danger-bg p-3 text-danger">
              <CircleAlert aria-hidden className="mt-0.5 size-5 shrink-0" />
              {error}
            </p>
          )}
          <p className="text-sm text-fg-muted" aria-live="polite">
            {receipt.lines.length - undecided} of {receipt.lines.length} lines decided
          </p>
          <button type="button" onClick={save} disabled={undecided > 0 || saving} className="btn-primary">
            {saving
              ? "Saving…"
              : undecided > 0
                ? `Decide ${undecided} more ${undecided === 1 ? "line" : "lines"}`
                : `Save receipt and ${prices} ${prices === 1 ? "price" : "prices"}`}
          </button>
        </div>
      </div>

      {editing && (
        <LineEditor
          line={editing}
          start={decisions[editing.id] ?? autos[editing.id]}
          ingredients={ingredients}
          onSave={(d) => {
            setDecisions((all) => ({ ...all, [editing.id]: d }));
            setEditing(null);
          }}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  );
}
