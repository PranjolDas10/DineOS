import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowRight, ChevronLeft, CircleHelp } from "lucide-react";

import { api, must } from "@/lib/api";
import { amount, money } from "@/lib/format";

import { KINDS } from "../matrix";
import { perUnit } from "../price-watch";
import { Status, TARGET } from "../status";
import { WhatIf } from "./what-if";

export const metadata: Metadata = { title: "Dish cost" };

/** "175 g", "1.2 kg", "2 each": the amount of an ingredient in one plate. */
function quantity(qty: string, unit: string) {
  const n = Number(qty);
  if (unit === "each") return `${amount(n)} each`;
  return n >= 1000 ? `${amount(n / 1000)} ${unit === "g" ? "kg" : "l"}` : `${amount(n)} ${unit}`;
}

// Owner at night: one dish, opened from Menu costs. Where does the money in this plate go,
// did prices move it lately, and what would a different menu price do?
export default async function DishPage({ params }: PageProps<"/menu/[id]">) {
  const { id } = await params;
  const client = await api();
  const [result, watch, matrix] = await Promise.all([
    client.GET("/v1/menu-items/{item_id}/cost", { params: { path: { item_id: id } } }),
    client.GET("/v1/reports/margin-watch").then(must),
    client.GET("/v1/reports/menu-matrix").then(must),
  ]);
  if ([404, 422].includes(result.response.status)) notFound(); // unknown id, or not an id at all
  const dish = must(result);
  const moved = watch.dishes.find((d) => d.menu_item_id === dish.menu_item_id);
  const placed = matrix.dishes.find((d) => d.menu_item_id === dish.menu_item_id);
  const sold = Number(placed?.units_sold ?? 0);
  const unpriced = [...new Set(dish.ingredients.filter((i) => i.cost_cents === null).map((i) => i.name))];
  // The headline is per ingredient: butter used directly and butter in the gravy count once.
  const shares = new Map<string, number>();
  for (const i of dish.ingredients) {
    if (i.share_pct !== null) shares.set(i.name, (shares.get(i.name) ?? 0) + Number(i.share_pct));
  }
  const [top] = [...shares].sort((a, b) => b[1] - a[1]);

  return (
    <div className="rise mx-auto grid max-w-6xl gap-6 [&>*]:min-w-0">
      <div className="grid gap-2">
        <Link href="/menu" className="inline-flex min-h-8 w-fit items-center gap-1 rounded-sm text-sm font-medium text-fg-muted transition-colors hover:text-fg">
          <ChevronLeft aria-hidden className="size-4" />
          Menu costs
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{dish.name}</h1>
          {placed?.kind && <span className="badge border border-line text-fg">{KINDS[placed.kind].title.replace(/s$/, "")}</span>}
        </div>
        <p className="max-w-[65ch] text-fg-muted">
          {dish.recipe_name ? `One plate of ${dish.recipe_name}, at today's ingredient prices.` : "No recipe is linked to this dish yet."}{" "}
          {sold > 0 && `${amount(sold)} sold in the last ${matrix.days} days.`}
        </p>
      </div>

      <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[
          ["Menu price", money(dish.price_cents)],
          ["Cost to make", dish.cost_cents === null ? "Unknown" : money(dish.cost_cents)],
          ["Keeps per plate", dish.margin_cents === null ? "–" : money(dish.margin_cents)],
        ].map(([term, value]) => (
          <div key={term} className="panel p-5">
            <dt className="eyebrow">{term}</dt>
            <dd className="text-2xl font-semibold tracking-tight tabular-nums">{value}</dd>
          </div>
        ))}
        <div className="panel p-5">
          <dt className="eyebrow">Food cost, target {TARGET}%</dt>
          <dd className="pt-1.5">
            {dish.food_cost_pct === null ? (
              <span className="text-2xl font-semibold tracking-tight">–</span>
            ) : (
              <Status item={{ food_cost_pct: dish.food_cost_pct, recipe_id: null, unpriced_ingredient_ids: [] }} />
            )}
          </dd>
        </div>
      </dl>

      {dish.cost_cents === null && (
        <section aria-labelledby="unknown" className="panel flex gap-3 p-5">
          <CircleHelp aria-hidden className="mt-0.5 size-5 shrink-0 text-fg-muted" />
          <div>
            <h2 id="unknown" className="font-semibold">
              This dish can&apos;t be costed yet
            </h2>
            <p className="text-fg-muted">
              {!dish.recipe_name
                ? "Link a recipe to it and the cost appears here."
                : unpriced.length
                  ? `No price yet for ${unpriced.join(", ")}. Check a receipt that includes ${unpriced.length === 1 ? "it" : "them"} and the cost fills in.`
                  : `${dish.empty_recipes.join(", ")} ${dish.empty_recipes.length === 1 ? "has" : "have"} no ingredients entered yet.`}
            </p>
          </div>
        </section>
      )}

      {dish.ingredients.length > 0 && (
        <section aria-labelledby="plate" className="panel">
          <div className="border-b border-line px-5 py-4">
            <p className="eyebrow">Down to raw ingredients</p>
            <h2 id="plate" className="text-xl font-semibold text-balance">
              {top
                ? `${top[0]} is ${top[1].toFixed(0)}% of what this plate costs.`
                : "What goes into a plate"}
            </h2>
            <p className="text-sm text-fg-muted">
              Sub-recipes are opened up, so an ingredient is listed once for each way it reaches the plate.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Ingredient</th>
                  <th scope="col" className="num">In a plate</th>
                  <th scope="col" className="num max-sm:hidden">You pay</th>
                  <th scope="col" className="num">Cost</th>
                  <th scope="col" className="max-sm:hidden">Share of plate</th>
                </tr>
              </thead>
              <tbody>
                {dish.ingredients.map((i) => (
                  <tr key={`${i.ingredient_id} ${i.via}`}>
                    <th scope="row">
                      {i.name}
                      {i.via && <span className="block text-sm font-normal text-fg-muted">in {i.via}</span>}
                    </th>
                    <td className="num tabular-nums">{quantity(i.qty, i.base_unit)}</td>
                    <td className="num tabular-nums max-sm:hidden">{i.unit_cents === null ? "No price yet" : perUnit(i.unit_cents, i.base_unit)}</td>
                    <td className="num tabular-nums">
                      {i.cost_cents === null ? "Unknown" : i.cost_cents === 0 ? "under 1¢" : money(i.cost_cents)}
                      {i.share_pct !== null && <span className="block text-sm text-fg-muted sm:hidden">{Number(i.share_pct).toFixed(0)}%</span>}
                    </td>
                    <td className="w-1/4 min-w-36 max-sm:hidden">
                      {i.share_pct !== null && (
                        <span className="flex items-center gap-2">
                          <span aria-hidden className="h-1.5 flex-1 rounded-full bg-surface-sunken">
                            <span
                              className="grow-across block h-full rounded-full bg-chart-food"
                              style={{ width: `${Math.max(Number(i.share_pct), 1)}%` }}
                            />
                          </span>
                          <span className="w-12 text-right text-sm text-fg-muted tabular-nums">{Number(i.share_pct).toFixed(1)}%</span>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {moved && (
        <section aria-labelledby="moved" className="panel p-5">
          <p className="eyebrow">Price watch, last {watch.days} days</p>
          <h2 id="moved" className="text-xl font-semibold text-balance">
            Costs {money(moved.cost_before_cents)}
            <ArrowRight aria-hidden className="mx-1.5 inline size-4" />
            <span className="sr-only">to</span>
            {money(moved.cost_after_cents)} to make since ingredient prices changed.
          </h2>
          <p className="flex flex-wrap items-center gap-1.5 pt-2 text-sm">
            {moved.drivers
              .filter((x) => x.delta_cents !== 0)
              .map((x) => (
                <span key={x.ingredient_id} className="badge bg-surface-sunken text-fg-muted">
                  {x.name} {x.delta_cents > 0 ? "+" : "−"}
                  {money(Math.abs(x.delta_cents))}
                </span>
              ))}
            <span className="text-fg-muted">
              {moved.weekly_impact_cents === 0
                ? "No change a week at the pace it sold."
                : `${moved.weekly_impact_cents > 0 ? "About" : "Saves about"} ${money(Math.abs(moved.weekly_impact_cents))} ${moved.weekly_impact_cents > 0 ? "more " : ""}a week at the pace it sold.`}
            </span>
          </p>
        </section>
      )}

      {/* A free dish has no food cost % to steer by, so there is nothing to calculate. */}
      {dish.cost_cents !== null && dish.cost_cents > 0 && dish.price_cents > 0 && (
        <WhatIf priceCents={dish.price_cents} costCents={dish.cost_cents} weeklyPlates={(sold * 7) / matrix.days} days={matrix.days} target={TARGET} />
      )}
    </div>
  );
}
