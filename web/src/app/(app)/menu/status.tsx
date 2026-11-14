import { CircleCheck, CircleHelp, TriangleAlert } from "lucide-react";

import type { Schemas } from "@/lib/api";

// shortcut: fixed 30% target, the common rule of thumb; make it owner-editable when they ask.
export const TARGET = 30;

type Costed = Pick<Schemas["FoodCostItem"], "food_cost_pct" | "recipe_id" | "unpriced_ingredient_ids">;

export function Status({ item }: { item: Costed }) {
  if (item.food_cost_pct === null) {
    const why = !item.recipe_id
      ? "No recipe"
      : item.unpriced_ingredient_ids.length
        ? `${item.unpriced_ingredient_ids.length} unpriced ingredient${item.unpriced_ingredient_ids.length > 1 ? "s" : ""}`
        : "Recipe has no lines";
    return (
      <span className="inline-flex items-center gap-1.5 text-fg-muted">
        <CircleHelp aria-hidden className="size-4" />
        {why}
      </span>
    );
  }
  const pct = Number(item.food_cost_pct);
  const high = pct > TARGET;
  return (
    <span className={`inline-flex items-center gap-2 font-medium ${high ? "text-warn" : "text-ok"}`}>
      {/* Meter runs 0 to twice the target, so the tick in the middle is the target itself. */}
      <span aria-hidden className="relative hidden h-1.5 w-20 rounded-full bg-surface-sunken sm:block">
        <span
          className="absolute inset-y-0 left-0 rounded-full bg-current"
          style={{ width: `${Math.min(pct / (TARGET * 2), 1) * 100}%` }}
        />
        <span className="absolute -inset-y-0.5 left-1/2 w-px bg-fg-muted" />
      </span>
      {high ? <TriangleAlert aria-hidden className="size-4" /> : <CircleCheck aria-hidden className="size-4" />}
      {pct.toFixed(1)}%<span className="sr-only">{high ? ", over target" : ", under target"}</span>
    </span>
  );
}
