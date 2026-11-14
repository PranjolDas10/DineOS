"use client";

import { useState } from "react";

import { money, moneyWhole } from "@/lib/format";

/** The lowest price, on a 25¢ step, that brings food cost to the target or under. */
export function priceForTarget(costCents: number, target: number) {
  return Math.ceil((costCents * 100) / target / 25) * 25;
}

// Owner at night, deciding a menu reprint: drag a price and see what a plate keeps. Nothing
// is saved; it is a calculator. Pure arithmetic on numbers the page already has, so it works
// instantly and offline. A native range input gives keyboard, touch and screen reader support.
export function WhatIf({
  priceCents,
  costCents,
  weeklyPlates,
  target,
}: {
  priceCents: number;
  costCents: number;
  weeklyPlates: number;
  target: number;
}) {
  const [price, setPrice] = useState(priceCents);
  const atTarget = priceForTarget(costCents, target);
  // Selling under cost isn't a pricing question (unless that is today's price).
  const min = Math.min(Math.ceil(costCents / 25) * 25, priceCents);
  const max = Math.max(priceCents * 2, atTarget + 200);
  const keeps = price - costCents;
  const delta = price - priceCents;
  const pct = (costCents / price) * 100;
  // ponytail: assumes the same plates sell at any price. Real demand drops as price rises;
  // model that only once there are sales at more than one price to fit it to.
  const weekly = Math.round(delta * weeklyPlates);

  return (
    <section aria-labelledby="what-if" className="panel">
      <div className="border-b border-line px-5 py-4">
        <p className="eyebrow">Try a price</p>
        <h2 id="what-if" className="text-xl font-semibold">
          What would a different menu price do?
        </h2>
        <p className="text-sm text-fg-muted">A calculator: nothing here changes your menu.</p>
      </div>
      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:gap-8">
        <div className="grid content-start gap-3">
          <label htmlFor="what-if-price" className="flex items-baseline justify-between gap-3 font-medium">
            Menu price
            <output htmlFor="what-if-price" className="text-2xl font-semibold tracking-tight tabular-nums">
              {money(price)}
            </output>
          </label>
          <input
            id="what-if-price"
            type="range"
            min={min}
            max={max}
            step={25}
            value={price}
            onChange={(e) => setPrice(Number(e.target.value))}
            aria-valuetext={money(price)}
            className="h-11 w-full cursor-pointer accent-(--primary)"
          />
          <div className="flex flex-wrap gap-2">
            <button type="button" className="btn-secondary" onClick={() => setPrice(Math.max(atTarget, min))} disabled={price === atTarget}>
              {money(atTarget)} hits {target}%
            </button>
            <button type="button" className="btn-secondary" onClick={() => setPrice(priceCents)} disabled={delta === 0}>
              Back to {money(priceCents)}
            </button>
          </div>
        </div>
        <dl aria-live="polite" className="grid grid-cols-2 content-start gap-x-4 gap-y-4">
          <div>
            <dt className="eyebrow">Keeps per plate</dt>
            <dd className="text-xl font-semibold tabular-nums">{money(keeps)}</dd>
          </div>
          <div>
            <dt className="eyebrow">Food cost</dt>
            <dd className={`text-xl font-semibold tabular-nums ${pct > target ? "text-warn" : ""}`}>
              {pct.toFixed(1)}%<span className="text-sm font-normal text-fg-muted"> {pct > target ? "over" : "under"} target</span>
            </dd>
          </div>
          <div className="col-span-2 border-t border-line pt-4">
            <dt className="eyebrow">A week, if it sells the same {Math.round(weeklyPlates)} plates</dt>
            <dd className={`text-xl font-semibold tabular-nums ${weekly > 0 ? "text-ok" : weekly < 0 ? "text-danger" : ""}`}>
              {weekly === 0 ? "No change" : `${weekly > 0 ? "+" : "−"}${moneyWhole(Math.abs(weekly))} kept`}
            </dd>
            <dd className="text-sm text-fg-muted">A higher price usually sells a few fewer plates, so read this as the best case.</dd>
          </div>
        </dl>
      </div>
    </section>
  );
}
