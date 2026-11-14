import type { Schemas } from "@/lib/api";
import { money, moneyWhole } from "@/lib/format";

type Day = Schemas["DayProfit"];

const weekday = new Intl.DateTimeFormat("en-US", { weekday: "short" });
const monthDay = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const at = (date: string) => new Date(`${date}T12:00`);

/** One column per day: its height is the day's sales, the green part is what was left after
 * food, commission and labor. Plain HTML, no chart library and no client JavaScript: the tooltip
 * is CSS (hover or keyboard focus), and each column also has the same numbers as screen-reader text. */
export function DailyChart({ days }: { days: Day[] }) {
  const top = Math.max(...days.map((d) => d.revenue_cents), 1);
  // Label every day for a week; for longer ranges only Mondays, so labels never collide.
  const labelled = (d: Day) => days.length <= 7 || at(d.date).getDay() === 1;

  return (
    <div>
      <ul className="flex h-52 items-end gap-[3px] sm:gap-1.5" aria-label="Sales and profit per day">
        {days.map((d, i) => {
          const profit = Math.max(d.profit_cents, 0);
          const loss = d.profit_cents < 0;
          const edge = i < 2 ? "left-0" : i > days.length - 3 ? "right-0" : "left-1/2 -translate-x-1/2";
          return (
            <li
              key={d.date}
              tabIndex={0}
              className="group relative flex h-full min-w-0 flex-1 flex-col justify-end rounded-sm outline-offset-4"
            >
              <div
                className="grow-in mx-auto flex min-h-px w-full max-w-9 flex-col gap-px overflow-hidden rounded-sm transition-opacity group-hover:opacity-80"
                style={{ height: `${(Math.max(d.revenue_cents, 0) / top) * 100}%`, animationDelay: `${Math.min(i * 25, 400)}ms` }}
              >
                {profit > 0 && <div className="bg-chart-profit" style={{ flexGrow: profit, flexBasis: 0 }} />}
                <div
                  className={loss ? "bg-chart-loss" : "bg-chart-labor"}
                  style={{ flexGrow: Math.max(d.revenue_cents - profit, 1), flexBasis: 0 }}
                />
              </div>
              <span className="sr-only">
                {weekday.format(at(d.date))}, {monthDay.format(at(d.date))}: {money(d.revenue_cents)} sales,{" "}
                {loss ? `${money(-d.profit_cents)} loss` : `${money(d.profit_cents)} profit`}
              </span>
              <p
                aria-hidden
                className={`panel pointer-events-none absolute bottom-full z-10 mb-2 hidden px-3 py-2 text-sm whitespace-nowrap shadow-pop group-hover:block group-focus-visible:block ${edge}`}
              >
                <span className="block font-medium">
                  {weekday.format(at(d.date))}, {monthDay.format(at(d.date))}
                </span>
                <span className="block text-fg-muted">{money(d.revenue_cents)} sales</span>
                <span className={`block ${loss ? "text-danger" : "text-ok"}`}>
                  {loss ? `${money(-d.profit_cents)} loss` : `${money(d.profit_cents)} profit`}
                </span>
              </p>
            </li>
          );
        })}
      </ul>
      <ul aria-hidden className="mt-2 flex gap-[3px] text-xs text-fg-muted sm:gap-1.5">
        {days.map((d) => (
          <li key={d.date} className="min-w-0 flex-1 text-center whitespace-nowrap">
            {labelled(d) && (days.length <= 7 ? weekday.format(at(d.date)) : monthDay.format(at(d.date)))}
          </li>
        ))}
      </ul>
      <ul className="mt-4 flex flex-wrap gap-x-5 gap-y-1 text-sm text-fg-muted">
        <li className="flex items-center gap-2">
          <span aria-hidden className="size-2.5 rounded-[3px] bg-chart-profit" />
          Profit
        </li>
        <li className="flex items-center gap-2">
          <span aria-hidden className="size-2.5 rounded-[3px] bg-chart-labor" />
          Food, commission and labor
        </li>
        <li className="ml-auto">Best day {moneyWhole(top)} in sales</li>
      </ul>
    </div>
  );
}

/** A tiny trend line for a KPI card. Decorative: the card states the number and its change. */
export function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const [low, high] = [Math.min(...values), Math.max(...values)];
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * 100},${26 - ((v - low) / (high - low || 1)) * 24}`)
    .join(" ");
  return (
    <svg aria-hidden viewBox="0 0 100 28" preserveAspectRatio="none" className="h-7 w-full text-fg-muted">
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
