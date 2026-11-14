import type { Metadata } from "next";
import { CircleCheck, CircleHelp, TriangleAlert } from "lucide-react";

import { api, must, type Schemas } from "@/lib/api";
import { money } from "@/lib/format";

import { MenuMatrix } from "./matrix";
import { PriceWatch } from "./price-watch";

export const metadata: Metadata = { title: "Menu costs" };

// shortcut: fixed 30% target, the common rule of thumb; make it owner-editable when they ask.
const TARGET = 30;

// Owner at night: which dishes cost too much to make, and which have no cost at all yet.
export default async function MenuCostsPage() {
  const client = await api();
  const [{ items }, watch, matrix] = await Promise.all([
    client.GET("/v1/reports/food-cost").then(must),
    client.GET("/v1/reports/margin-watch").then(must),
    client.GET("/v1/reports/menu-matrix").then(must),
  ]);
  // Worst first: unknown cost, then highest food cost %.
  const rows = items.toSorted(
    (a, b) => Number(b.food_cost_pct ?? Infinity) - Number(a.food_cost_pct ?? Infinity),
  );
  const unknown = items.filter((i) => i.cost_cents === null).length;
  const over = items.filter((i) => Number(i.food_cost_pct) > TARGET).length;

  const costed = items.length - unknown;

  return (
    <div className="rise mx-auto grid max-w-6xl gap-6 [&>*]:min-w-0">
      <div>
        <h1 className="text-2xl font-semibold">Menu costs</h1>
        <p className="max-w-[65ch] text-fg-muted">
          What each dish costs to make at today&apos;s ingredient prices, against a {TARGET}% food cost target.
        </p>
      </div>

      {rows.length === 0 ? (
        <section className="panel p-8">
          <h2 className="text-xl font-semibold">No menu items yet</h2>
          <p className="text-fg-muted">Add dishes and their recipes to see what each one costs to make.</p>
        </section>
      ) : (
        <>
          <dl className="grid gap-4 sm:grid-cols-3">
            {[
              ["Under target", costed - over, `of ${costed} costed dishes`],
              ["Over target", over, over === 0 ? "Every costed dish is under target" : `above ${TARGET}% food cost`],
              ["Can't be costed yet", unknown, unknown === 0 ? "Every dish has a full recipe" : "missing a recipe or a price"],
            ].map(([term, value, note]) => (
              <div key={term} className="panel p-5">
                <dt className="eyebrow">{term}</dt>
                <dd className="text-2xl font-semibold tracking-tight">{value}</dd>
                <dd className="text-sm text-fg-muted">{note}</dd>
              </div>
            ))}
          </dl>
          <PriceWatch watch={watch} />
          <MenuMatrix matrix={matrix} />
          <div className="panel overflow-x-auto">
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
        </>
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
