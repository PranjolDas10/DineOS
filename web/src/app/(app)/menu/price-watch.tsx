import Link from "next/link";
import { ArrowDownRight, ArrowRight, ArrowUpRight } from "lucide-react";

import type { Schemas } from "@/lib/api";
import { money, moneyWhole } from "@/lib/format";

type Watch = Schemas["MarginWatch"];

/** Prices are stored per gram or millilitre; people think per kilo, litre or item. */
export function perUnit(unitCents: string, baseUnit: string) {
  const each = baseUnit === "each";
  return `${money(Number(unitCents) * (each ? 1 : 1000))} ${each ? "each" : baseUnit === "g" ? "a kg" : "a litre"}`;
}

/** Up is bad for a cost, so red; the arrow and the sign say the direction without color. */
function Move({ pct }: { pct: number }) {
  const up = pct > 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  return (
    <span className={`badge ${up ? "bg-danger-bg text-danger" : "bg-ok-bg text-ok"}`}>
      <Icon aria-hidden className="size-3.5" />
      {up ? "+" : "−"}
      {Math.abs(pct).toFixed(1)}%
    </span>
  );
}

// Owner at night: a receipt changed a price last week. Which dishes did that hit, by how much,
// and what would it take to stand still? Every number comes from the price history and the
// recipes; nothing here is an estimate except "a week at the pace it sold".
export function PriceWatch({ watch }: { watch: Watch }) {
  if (watch.ingredients.length === 0) return null;
  const weekly = watch.weekly_impact_cents;

  return (
    <section aria-labelledby="price-watch" className="panel">
      <div className="border-b border-line px-5 py-4">
        <p className="eyebrow">Price watch, last {watch.days} days</p>
        <h2 id="price-watch" className="text-xl font-semibold text-balance">
          {weekly > 0
            ? `Ingredient prices are costing about ${moneyWhole(weekly)} more a week.`
            : weekly < 0
              ? `Ingredient prices are saving about ${moneyWhole(-weekly)} a week.`
              : "Ingredient prices moved, with no change at current sales."}
        </h2>
        <p className="text-sm text-fg-muted">
          From {watch.ingredients.length} price {watch.ingredients.length === 1 ? "change" : "changes"} on checked
          receipts, at the pace each dish sold.
        </p>
      </div>

      <div className="grid lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <div className="border-b border-line p-5 lg:border-r lg:border-b-0">
          <h3 className="eyebrow pb-2">What changed</h3>
          <ul className="grid gap-3">
            {watch.ingredients.map((i) => (
              <li key={i.ingredient_id} className="flex items-start justify-between gap-3">
                <p className="min-w-0">
                  <span className="block font-medium">{i.name}</span>
                  <span className="flex flex-wrap items-center gap-x-1.5 text-sm text-fg-muted">
                    {perUnit(i.unit_cents_before, i.base_unit)}
                    <ArrowRight aria-hidden className="size-3.5" />
                    <span className="sr-only">to</span>
                    <span className="text-fg">{perUnit(i.unit_cents_after, i.base_unit)}</span>
                  </span>
                  <span className="block text-sm text-fg-muted">
                    {i.dishes_affected === 0
                      ? "In no dish on the menu"
                      : `In ${i.dishes_affected} ${i.dishes_affected === 1 ? "dish" : "dishes"}`}
                  </span>
                </p>
                {i.change_pct !== null && <Move pct={Number(i.change_pct)} />}
              </li>
            ))}
          </ul>
        </div>

        <div className="p-5">
          <h3 className="eyebrow pb-2">What it did to your dishes</h3>
          <ul className="grid divide-y divide-line">
            {watch.dishes.map((d) => {
              const delta = d.cost_after_cents - d.cost_before_cents;
              return (
                <li key={d.menu_item_id} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1 py-3 first:pt-0 last:pb-0">
                  <p className="font-medium">
                    <Link href={`/menu/${d.menu_item_id}`} className="link">
                      {d.name}
                    </Link>
                  </p>
                  <p className={`text-right font-medium ${d.weekly_impact_cents > 0 ? "text-danger" : d.weekly_impact_cents < 0 ? "text-ok" : "text-fg-muted"}`}>
                    {d.weekly_impact_cents === 0
                      ? "No change a week"
                      : `${d.weekly_impact_cents > 0 ? "+" : "−"}${money(Math.abs(d.weekly_impact_cents))} a week`}
                  </p>
                  <p className="col-span-2 text-sm text-fg-muted">
                    Costs {money(d.cost_before_cents)}
                    <ArrowRight aria-hidden className="mx-1 inline size-3.5" />
                    <span className="sr-only">to</span>
                    <span className="text-fg">{money(d.cost_after_cents)}</span> to make, food cost{" "}
                    {d.food_cost_pct_before ?? "–"}%
                    <ArrowRight aria-hidden className="mx-1 inline size-3.5" />
                    <span className="sr-only">to</span>
                    <span className="text-fg">{d.food_cost_pct_after ?? "–"}%</span>. {Number(d.units_sold).toFixed(0)} sold.
                  </p>
                  <p className="col-span-2 flex flex-wrap gap-1.5 text-sm">
                    {d.drivers
                      .filter((x) => x.delta_cents !== 0)
                      .map((x) => (
                        <span key={x.ingredient_id} className="badge bg-surface-sunken text-fg-muted">
                          {x.name} {x.delta_cents > 0 ? "+" : "−"}
                          {money(Math.abs(x.delta_cents))}
                        </span>
                      ))}
                    {delta > 0 && (
                      <span className="badge border border-line text-fg">
                        {money(d.price_cents + delta)} keeps your margin
                      </span>
                    )}
                  </p>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </section>
  );
}
