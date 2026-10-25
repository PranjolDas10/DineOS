import type { Metadata } from "next";
import { CircleCheck, CircleHelp, TriangleAlert } from "lucide-react";

import { api, must, type Schemas } from "@/lib/api";
import { money } from "@/lib/format";

export const metadata: Metadata = { title: "Menu costs" };

// shortcut: fixed 30% target, the common rule of thumb; make it owner-editable when they ask.
const TARGET = 30;

// Owner at night: which dishes cost too much to make, and which have no cost at all yet.
export default async function MenuCostsPage() {
  const client = await api();
  const { items } = must(await client.GET("/v1/reports/food-cost"));
  // Worst first: unknown cost, then highest food cost %.
  const rows = items.toSorted(
    (a, b) => Number(b.food_cost_pct ?? Infinity) - Number(a.food_cost_pct ?? Infinity),
  );
  const unknown = items.filter((i) => i.cost_cents === null).length;
  const over = items.filter((i) => Number(i.food_cost_pct) > TARGET).length;

  return (
    <div className="mx-auto grid max-w-6xl gap-8 [&>*]:min-w-0">
      <div className="grid gap-2">
        <h1 className="text-3xl font-semibold text-balance">Menu costs</h1>
        <p className="max-w-[65ch] text-fg-muted">
          What each dish costs to make at today&apos;s ingredient prices, against a {TARGET}% food cost
          target. {over === 0 ? "Every costed dish is under target." : `${over} over target.`}{" "}
          {unknown > 0 && `${unknown} can't be costed yet.`}
        </p>
      </div>

      {rows.length === 0 ? (
        <p className="text-fg-muted">No menu items yet. Add dishes and their recipes to see costs.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Dish</th>
                <th scope="col" className="num">Price</th>
                <th scope="col" className="num">Cost to make</th>
                <th scope="col" className="num">Margin</th>
                <th scope="col" className="num">Food cost</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((item) => (
                <tr key={item.menu_item_id}>
                  <th scope="row">{item.name}</th>
                  <td className="num">{money(item.price_cents)}</td>
                  <td className="num">{item.cost_cents === null ? "Unknown" : money(item.cost_cents)}</td>
                  <td className="num">{item.margin_cents === null ? "–" : money(item.margin_cents)}</td>
                  <td className="num">
                    <Status item={item} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Status({ item }: { item: Schemas["FoodCostItem"] }) {
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
    <span className={`inline-flex items-center gap-1.5 font-semibold ${high ? "text-warn" : "text-ok"}`}>
      {high ? <TriangleAlert aria-hidden className="size-4" /> : <CircleCheck aria-hidden className="size-4" />}
      {pct.toFixed(1)}%<span className="sr-only">{high ? ", over target" : ", under target"}</span>
    </span>
  );
}
