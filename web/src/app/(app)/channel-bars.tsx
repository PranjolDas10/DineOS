import { TrendingDown } from "lucide-react";

import type { Schemas } from "@/lib/api";
import { channelName, money, moneyWhole, percent } from "@/lib/format";

type Channel = Schemas["ChannelProfit"];

const SEGMENTS = [
  { key: "food_cost_cents", label: "Food", className: "bg-chart-food" },
  { key: "commission_cents", label: "Commission", className: "bg-chart-commission" },
  { key: "labor_cents", label: "Labor", className: "bg-chart-labor" },
] as const;

/** One bar per channel, split into what the sales paid for. Bars share one scale, so a delivery
 * channel's smaller profit slice is visible next to dine-in. The table below has the same numbers. */
export function ChannelBars({ channels }: { channels: Channel[] }) {
  const costs = (c: Channel) => c.food_cost_cents + c.commission_cents + c.labor_cents;
  const scale = Math.max(...channels.map((c) => Math.max(c.revenue_cents, costs(c))), 1);

  return (
    <div className="grid gap-6">
      <ul aria-label="Legend" className="flex flex-wrap gap-x-5 gap-y-1 text-sm text-fg-muted">
        {[...SEGMENTS, { label: "Profit", className: "bg-chart-profit" }].map((s) => (
          <li key={s.label} className="flex items-center gap-2">
            <span aria-hidden className={`size-3 rounded-sm ${s.className}`} />
            {s.label}
          </li>
        ))}
        <li className="flex items-center gap-2">
          <span aria-hidden className="h-4 w-0.5 bg-fg" />
          Sales, where costs pass it
        </li>
      </ul>

      <ul className="grid gap-5">
        {channels.map((c) => {
          const loss = c.profit_cents < 0;
          const parts = [
            ...SEGMENTS.map((s) => ({ ...s, cents: c[s.key] })),
            { key: "profit", label: "Profit", className: "bg-chart-profit", cents: Math.max(c.profit_cents, 0) },
          ].filter((p) => p.cents > 0);
          return (
            <li
              key={c.channel}
              className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-6 gap-y-2 md:grid-cols-[9rem_minmax(0,1fr)_10rem]"
            >
              <p>
                <span className="font-semibold">{channelName(c.channel)}</span>
                <span className="block text-sm text-fg-muted">{moneyWhole(c.revenue_cents)} sales</span>
              </p>
              <p className="text-right md:order-last">
                {loss ? (
                  <span className="inline-flex items-center gap-1.5 font-semibold text-danger">
                    <TrendingDown aria-hidden className="size-4" />
                    {moneyWhole(-c.profit_cents)} loss
                  </span>
                ) : (
                  <span className="font-semibold">{moneyWhole(c.profit_cents)} profit</span>
                )}
                <span className="block text-sm text-fg-muted">
                  {percent(c.profit_cents, c.revenue_cents)} of sales
                </span>
              </p>
              <div className="relative col-span-2 md:col-span-1">
                <div
                  className="grow-across flex h-6 gap-0.5 overflow-hidden rounded-sm"
                  style={{ width: `${(Math.max(c.revenue_cents, costs(c)) / scale) * 100}%` }}
                >
                  {parts.map((p) => (
                    <div
                      key={p.key}
                      title={`${p.label} ${money(p.cents)}`}
                      className={p.className}
                      style={{ flexGrow: p.cents, flexBasis: 0 }}
                    />
                  ))}
                </div>
                {loss && (
                  <div
                    aria-hidden
                    className="absolute -top-1 -bottom-1 w-0.5 bg-fg"
                    style={{ left: `${(c.revenue_cents / scale) * 100}%` }}
                  />
                )}
                <p className="sr-only">
                  {parts.map((p) => `${p.label} ${money(p.cents)}`).join(", ")}
                </p>
              </div>
            </li>
          );
        })}
      </ul>

      <details className="group">
        <summary className="w-fit cursor-pointer rounded-sm py-1 text-sm font-medium text-accent-text">
          Show the numbers as a table
        </summary>
        <div className="mt-3 overflow-x-auto rounded-md border border-line">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Channel</th>
                {["Sales", "Food", "Commission", "Labor", "Profit"].map((h) => (
                  <th key={h} scope="col" className="num">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {channels.map((c) => (
                <tr key={c.channel}>
                  <th scope="row">{channelName(c.channel)}</th>
                  {[c.revenue_cents, c.food_cost_cents, c.commission_cents, c.labor_cents, c.profit_cents].map(
                    (v, i) => (
                      <td key={i} className="num">
                        {money(v)}
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
