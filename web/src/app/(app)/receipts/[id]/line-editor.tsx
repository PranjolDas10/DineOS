"use client";

import { useEffect, useRef, useState } from "react";
import { CircleAlert } from "lucide-react";

import type { Schemas } from "@/lib/api";
import { amount, money, parseDollars } from "@/lib/format";
import { toBase } from "@/lib/units";

export type Decision = {
  ingredient_id: string | null;
  description: string;
  quantity: string;
  unit: string;
  line_total_cents: number;
  base_qty: string | null;
};

const NOT_INGREDIENT = "none";

/** One receipt line: fix what the model misread, then say what it is. A native modal dialog,
 * so focus moves into it, Esc closes it, and the page behind is inert. */
export function LineEditor({
  line,
  start,
  ingredients,
  onSave,
  onClose,
}: {
  line: Schemas["ReceiptLineOut"];
  start: Decision | null | undefined;
  ingredients: Schemas["IngredientOut"][];
  onSave: (d: Decision) => void;
  onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => dialog.current?.showModal(), []);

  const [description, setDescription] = useState(start?.description ?? line.description);
  const [quantity, setQuantity] = useState(start?.quantity ?? line.quantity);
  const [unit, setUnit] = useState(start?.unit ?? line.unit);
  const [total, setTotal] = useState(((start?.line_total_cents ?? line.line_total_cents) / 100).toFixed(2));
  const [what, setWhat] = useState(start ? (start.ingredient_id ?? NOT_INGREDIENT) : "");
  const [baseQty, setBaseQty] = useState(start?.base_qty ?? "");
  const [error, setError] = useState<string | null>(null);

  const ingredient = ingredients.find((i) => i.id === what);
  const cents = parseDollars(total);
  const base = Number(baseQty);

  // Choosing an ingredient fills in the converted amount when the receipt unit allows it.
  function choose(id: string) {
    setWhat(id);
    const picked = ingredients.find((i) => i.id === id);
    const converted = picked ? toBase(Number(quantity), unit, picked.base_unit) : null;
    setBaseQty(converted === null ? "" : String(converted));
  }

  function save(e: React.FormEvent) {
    e.preventDefault();
    const problem = !description.trim()
      ? "Add a description."
      : !(Number(quantity) > 0)
        ? "Quantity must be more than 0."
        : cents === null
          ? "The line total isn't an amount. Use a format like 31.50."
          : !what
            ? "Choose what this line is, or mark it as not an ingredient."
            : ingredient && !(base > 0)
              ? `Enter how many ${ingredient.base_unit} of ${ingredient.name} this line bought.`
              : null;
    if (problem) return setError(problem);
    onSave({
      ingredient_id: ingredient?.id ?? null,
      description: description.trim(),
      quantity,
      unit: unit.trim(),
      line_total_cents: cents!,
      base_qty: ingredient ? String(base) : null,
    });
  }

  return (
    <dialog
      ref={dialog}
      onClose={onClose}
      aria-labelledby="line-title"
      className="m-auto w-[min(36rem,calc(100vw-2rem))] rounded-lg border border-line bg-surface p-0 text-fg backdrop:bg-black/50"
    >
      <form onSubmit={save} noValidate className="grid gap-5 p-6">
        <div>
          <h2 id="line-title" className="text-xl font-semibold">
            Check this line
          </h2>
          <p className="text-sm text-fg-muted">
            The receipt reads: {line.description}, {amount(Number(line.quantity))} {line.unit},{" "}
            {money(line.line_total_cents)} ({Math.round(Number(line.confidence) * 100)}% sure)
          </p>
        </div>
        <label className="grid gap-1.5 font-medium">
          Description
          <input className="field" value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <div className="grid grid-cols-3 gap-3">
          <label className="grid gap-1.5 font-medium">
            Quantity
            <input inputMode="decimal" className="field min-w-0" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
          </label>
          <label className="grid gap-1.5 font-medium">
            Unit
            <input className="field min-w-0" value={unit} onChange={(e) => setUnit(e.target.value)} />
          </label>
          <label className="grid gap-1.5 font-medium">
            Line total ($)
            <input inputMode="decimal" className="field min-w-0" value={total} onChange={(e) => setTotal(e.target.value)} />
          </label>
        </div>
        <label className="grid gap-1.5 font-medium">
          What is it?
          <select className="field" value={what} onChange={(e) => choose(e.target.value)}>
            <option value="" disabled>
              Choose an ingredient
            </option>
            {ingredients.map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
              </option>
            ))}
            <option value={NOT_INGREDIENT}>Not an ingredient (supplies, cleaning…)</option>
          </select>
        </label>
        {ingredient && (
          <div className="grid gap-1.5 rounded-md bg-surface-sunken p-4">
            <label className="grid gap-1.5 font-medium">
              How much {ingredient.name}, in {ingredient.base_unit}
              <input
                inputMode="decimal"
                className="field"
                value={baseQty}
                onChange={(e) => setBaseQty(e.target.value)}
                aria-describedby="per-unit"
              />
            </label>
            <p id="per-unit" className="text-sm text-fg-muted">
              {base > 0 && cents !== null
                ? `${amount(base)} ${ingredient.base_unit} for ${money(cents)}: ${money(
                    (cents / base) * (ingredient.base_unit === "each" ? 1 : 1000),
                  )} per ${ingredient.base_unit === "each" ? "item" : `1,000 ${ingredient.base_unit}`}`
                : `A "${unit}" can't be converted on its own. Enter the total ${ingredient.base_unit}, e.g. 3 packs of 1.6 kg = 4800.`}
            </p>
          </div>
        )}
        {error && (
          <p role="alert" className="flex gap-2 rounded-md bg-danger-bg p-3 text-danger">
            <CircleAlert aria-hidden className="mt-0.5 size-5 shrink-0" />
            {error}
          </p>
        )}
        <div className="flex flex-wrap justify-end gap-3">
          <button
            type="button"
            onClick={() => dialog.current?.close()}
            className="min-h-12 cursor-pointer rounded-md border border-line-strong px-5 font-semibold hover:bg-surface-sunken"
          >
            Cancel
          </button>
          <button type="submit" className="btn-primary px-6">
            Save line
          </button>
        </div>
      </form>
    </dialog>
  );
}
