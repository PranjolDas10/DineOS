import type { Metadata } from "next";
import Link from "next/link";
import { ArrowDownRight, ArrowUpRight, TriangleAlert } from "lucide-react";

import { api, me, must, type Schemas } from "@/lib/api";
import { dayRange, moneyWhole, percent } from "@/lib/format";
import { addDays } from "@/lib/time";

import { ChannelBars } from "./channel-bars";
import { DailyChart, Sparkline } from "./daily-chart";
import { DishTable } from "./dish-table";

export const metadata: Metadata = { title: "Profit" };

const RANGES = [7, 14, 28];

type Totals = { revenue: number; food: number; commission: number; labor: number; profit: number };
const totals = (report: Schemas["ProfitReport"]): Totals =>
  report.daily.reduce(
    (t, d) => ({
      revenue: t.revenue + d.revenue_cents,
      food: t.food + d.food_cost_cents,
      commission: t.commission + d.commission_cents,
      labor: t.labor + d.labor_cents,
      profit: t.profit + d.profit_cents,
    }),
    { revenue: 0, food: 0, commission: 0, labor: 0, profit: 0 },
  );
const share = (part: number, whole: number) => (whole ? (part / whole) * 100 : 0);

// Owner at night, and the recruiter's first screen: the answer first (what was left), then the
// trend, then where each dollar went per channel, then dishes.
export default async function ProfitPage({ searchParams }: PageProps<"/">) {
  const asked = Number((await searchParams).days);
  const days = RANGES.includes(asked) ? asked : 7;
  const client = await api();
  // "Today" is the restaurant's local date, not the web server's.
  const to = (await me()).today;
  const from = addDays(to, -(days - 1));
  const range = (a: string, b: string) => ({ params: { query: { from: a, to: b } } });

  // The same window one period earlier, for the "vs previous" changes.
  const [report, before] = await Promise.all([
    client.GET("/v1/reports/profit", range(from, to)).then(must),
    client.GET("/v1/reports/profit", range(addDays(from, -days), addDays(from, -1))).then(must),
  ]);
  const now = totals(report);
  const prev = totals(before);
  // Compare only like with like: if the earlier window is mostly empty (data starts partway
  // through it), "+1750%" would be true and meaningless.
  const selling = (r: Schemas["ProfitReport"]) => r.daily.filter((d) => d.revenue_cents > 0).length;
  const compare = selling(before) * 2 >= selling(report) && prev.revenue > 0;

  const kpis = [
    {
      label: "Sales",
      value: moneyWhole(now.revenue),
      change: compare ? share(now.revenue - prev.revenue, prev.revenue) : null,
      unit: "%",
      upIsGood: true,
      series: report.daily.map((d) => d.revenue_cents),
    },
    ...(
      [
        ["Food cost", (t: Totals) => t.food, (d) => d.food_cost_cents],
        ["Labor", (t: Totals) => t.labor, (d) => d.labor_cents],
        ["Prime cost", (t: Totals) => t.food + t.labor, (d) => d.food_cost_cents + d.labor_cents],
      ] as [string, (t: Totals) => number, (d: Schemas["DayProfit"]) => number][]
    ).map(([label, pick, perDay]) => ({
      label,
      value: percent(pick(now), now.revenue),
      change: compare ? share(pick(now), now.revenue) - share(pick(prev), prev.revenue) : null,
      unit: " pts",
      upIsGood: false,
      // A closed day has no ratio; plotting it as 0% would draw a dip that never happened.
      series: report.daily.filter((d) => d.revenue_cents > 0).map((d) => share(perDay(d), d.revenue_cents)),
    })),
  ];

  return (
    <div className="rise mx-auto grid max-w-6xl gap-6 [&>*]:min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Profit</h1>
          <p className="text-fg-muted">{dayRange(from, to)}</p>
        </div>
        <nav aria-label="Date range" className="flex rounded-md border border-line bg-surface p-0.5">
          {RANGES.map((n) => (
            <Link
              key={n}
              href={n === 7 ? "/" : `/?days=${n}`}
              aria-current={n === days ? "page" : undefined}
              className="flex min-h-8 items-center rounded-sm px-3 text-sm font-medium text-fg-muted transition-colors hover:text-fg aria-[current=page]:bg-surface-sunken aria-[current=page]:text-fg"
            >
              {n} days
            </Link>
          ))}
        </nav>
      </div>

      {now.revenue === 0 ? (
        <section className="panel grid justify-items-start gap-2 p-8">
          <h2 className="text-xl font-semibold">No sales in these days yet</h2>
          <p className="max-w-[60ch] text-fg-muted">
            Import a sales export from the point of sale and this page shows what was left after food,
            delivery commissions and labor, by channel and by dish.
          </p>
        </section>
      ) : (
        <>
          <section aria-labelledby="verdict" className="panel grid gap-8 p-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] lg:p-8">
            <div className="grid content-start gap-3">
              <h2 id="verdict" className="eyebrow">
                {now.profit >= 0 ? "Left after food, commissions and labor" : "Short after food, commissions and labor"}
              </h2>
              <p className={`text-5xl font-semibold tracking-tighter sm:text-6xl ${now.profit < 0 ? "text-danger" : ""}`}>
                {moneyWhole(Math.abs(now.profit))}
              </p>
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
                {/* A percentage change from exactly $0 is undefined, so it is left out. */}
                {compare && prev.profit !== 0 && (
                  <Change value={share(now.profit - prev.profit, Math.abs(prev.profit))} unit="%" upIsGood />
                )}
                <span className="text-fg-muted">
                  {percent(now.profit, now.revenue)} of {moneyWhole(now.revenue)} in food sales
                  {compare && `, against ${moneyWhole(prev.profit)} the ${days} days before`}
                </span>
              </p>
              {report.sales_with_unknown_food_cost > 0 && (
                <p className="mt-2 flex gap-2 rounded-md bg-warn-bg p-3 text-sm text-warn">
                  <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
                  <span>
                    {report.sales_with_unknown_food_cost} sales include items without a recipe cost, so food
                    cost reads low.{" "}
                    <Link href="/menu" className="font-semibold underline underline-offset-2">
                      See which menu items
                    </Link>
                  </span>
                </p>
              )}
            </div>
            <DailyChart days={report.daily} />
          </section>

          <dl className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {kpis.map((k) => (
              <div key={k.label} className="panel grid gap-1 p-5">
                <dt className="eyebrow">{k.label}</dt>
                <dd className="text-2xl font-semibold tracking-tight">{k.value}</dd>
                <dd className="min-h-6 text-sm">
                  {k.change === null ? (
                    <span className="text-fg-muted">No earlier period to compare</span>
                  ) : (
                    <Change value={k.change} unit={k.unit} upIsGood={k.upIsGood} />
                  )}
                </dd>
                <dd className="mt-2">
                  <Sparkline values={k.series} />
                </dd>
              </div>
            ))}
          </dl>
        </>
      )}

      {report.channels.length > 0 && (
        <section aria-labelledby="channels" className="panel">
          <div className="border-b border-line px-5 py-4">
            <h2 id="channels" className="font-semibold">
              Where each dollar went, by channel
            </h2>
            <p className="text-sm text-fg-muted">
              Delivery commission of {moneyWhole(now.commission)} was {percent(now.commission, now.revenue)} of all
              food sales.
            </p>
          </div>
          <div className="p-5">
            <ChannelBars channels={report.channels} />
          </div>
        </section>
      )}

      {report.dishes.length > 0 && (
        <section aria-labelledby="dishes" className="panel overflow-hidden">
          <div className="border-b border-line px-5 py-4">
            <h2 id="dishes" className="font-semibold">
              Dishes
            </h2>
            <p className="text-sm text-fg-muted">
              Most profitable first. Before labor and commission, which the books keep per channel.
            </p>
          </div>
          <DishTable dishes={report.dishes} />
        </section>
      )}
    </div>
  );
}

/** A change against the previous period: arrow, sign and words, so color is never the only cue. */
function Change({ value, unit, upIsGood }: { value: number; unit: string; upIsGood: boolean }) {
  const flat = Math.abs(value) < 0.05;
  const good = value > 0 === upIsGood;
  const Icon = value > 0 ? ArrowUpRight : ArrowDownRight;
  if (flat) return <span className="text-fg-muted">No change</span>;
  return (
    <span className={`inline-flex items-center gap-1 font-medium ${good ? "text-ok" : "text-danger"}`}>
      <Icon aria-hidden className="size-4" />
      {value > 0 ? "+" : "−"}
      {Math.abs(value).toFixed(1)}
      {unit}
      <span className="sr-only">{good ? ", better" : ", worse"} than the previous period</span>
    </span>
  );
}
