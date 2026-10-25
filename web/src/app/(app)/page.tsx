import type { Metadata } from "next";
import Link from "next/link";
import { TriangleAlert } from "lucide-react";

import { api, must } from "@/lib/api";
import { dayRange, moneyWhole, percent } from "@/lib/format";

import { ChannelBars } from "./channel-bars";
import { DishTable } from "./dish-table";

export const metadata: Metadata = { title: "Profit" };

const RANGES = [7, 14, 28];

// Owner at night, and the recruiter's first screen: one sentence with the answer, then where
// each dollar went per channel, then dishes.
export default async function ProfitPage({ searchParams }: PageProps<"/">) {
  const asked = Number((await searchParams).days);
  const days = RANGES.includes(asked) ? asked : 7;
  // shortcut: "today" is the web server's date; use the restaurant's timezone once the API exposes it.
  const to = new Date();
  const from = new Date(to);
  from.setDate(to.getDate() - (days - 1));
  const [fromDay, toDay] = [from, to].map((d) => d.toLocaleDateString("en-CA"));

  const client = await api();
  const report = must(
    await client.GET("/v1/reports/profit", { params: { query: { from: fromDay, to: toDay } } }),
  );
  const sum = (key: "revenue_cents" | "commission_cents" | "food_cost_cents" | "profit_cents") =>
    report.channels.reduce((total, c) => total + c[key], 0);
  const [revenue, commission, food, profit] = [
    sum("revenue_cents"),
    sum("commission_cents"),
    sum("food_cost_cents"),
    sum("profit_cents"),
  ];
  const labor = report.labor_cents;

  return (
    <div className="mx-auto grid max-w-6xl gap-12 [&>*]:min-w-0">
      <section aria-labelledby="verdict" className="grid gap-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <p className="text-fg-muted">{dayRange(fromDay, toDay)}</p>
          <nav aria-label="Date range" className="flex rounded-md border border-line p-0.5">
            {RANGES.map((n) => (
              <Link
                key={n}
                href={n === 7 ? "/" : `/?days=${n}`}
                aria-current={n === days ? "page" : undefined}
                className="min-h-10 rounded-sm px-3 py-2 text-sm font-medium text-fg-muted hover:text-fg aria-[current=page]:bg-surface-sunken aria-[current=page]:text-fg"
              >
                {n} days
              </Link>
            ))}
          </nav>
        </div>
        {revenue === 0 ? (
          <h1 id="verdict" className="text-3xl font-semibold text-balance">
            No sales in these days yet. Import a sales export to see profit by channel.
          </h1>
        ) : (
          <h1 id="verdict" className="max-w-4xl text-3xl leading-tight font-semibold text-balance sm:text-[2.5rem]">
            {moneyWhole(revenue)} in food sales,{" "}
            {profit >= 0
              ? `${moneyWhole(profit)} left after food, commissions and labor.`
              : `${moneyWhole(-profit)} short after food, commissions and labor.`}
          </h1>
        )}
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-4">
          {[
            ["Food cost", percent(food, revenue), "of food sales"],
            ["Labor", percent(labor, revenue), `${moneyWhole(labor)} from the schedule`],
            ["Delivery commission", percent(commission, revenue), moneyWhole(commission)],
            ["Prime cost", percent(food + labor, revenue), "food + labor"],
          ].map(([term, value, note]) => (
            <div key={term} className="bg-surface p-4">
              <dt className="text-sm text-fg-muted">{term}</dt>
              <dd className="mt-1 text-2xl font-semibold">{value}</dd>
              <dd className="text-sm text-fg-muted">{note}</dd>
            </div>
          ))}
        </dl>
        {report.sales_with_unknown_food_cost > 0 && (
          <p className="flex gap-2 rounded-md bg-warn-bg p-3 text-warn">
            <TriangleAlert aria-hidden className="mt-0.5 size-5 shrink-0" />
            <span>
              {report.sales_with_unknown_food_cost} sales include items without a recipe cost, so
              food cost reads low.{" "}
              <Link href="/menu" className="font-semibold underline underline-offset-2">
                See which menu items
              </Link>
            </span>
          </p>
        )}
      </section>

      {report.channels.length > 0 && (
        <section aria-labelledby="channels" className="grid gap-4">
          <h2 id="channels" className="text-xl font-semibold">
            Where each dollar went, by channel
          </h2>
          <ChannelBars channels={report.channels} />
        </section>
      )}

      {report.dishes.length > 0 && (
        <section aria-labelledby="dishes" className="grid gap-4">
          <div>
            <h2 id="dishes" className="text-xl font-semibold">
              Dishes
            </h2>
            <p className="text-fg-muted">
              Most profitable first. Before labor and commission, which the books keep per channel.
            </p>
          </div>
          <DishTable dishes={report.dishes} />
        </section>
      )}
    </div>
  );
}
