import type { Schemas } from "@/lib/api";
import { money, percent } from "@/lib/format";

export function DishTable({ dishes }: { dishes: Schemas["DishProfit"][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th scope="col">Dish</th>
            <th scope="col" className="num">Sales</th>
            <th scope="col" className="num">Food cost</th>
            <th scope="col" className="num">Food cost %</th>
            <th scope="col" className="num">Gross profit</th>
          </tr>
        </thead>
        <tbody>
          {dishes.toSorted((a, b) => Number(b.food_cost_cents > 0) - Number(a.food_cost_cents > 0)).map((d) => {
            // The ledger never books an unknown cost as $0, so a dish with sales and no food cost
            // had no recipe cost when it was sold.
            const known = d.food_cost_cents > 0;
            return (
            <tr key={d.menu_item_id ?? "unmapped"}>
              <th scope="row">
                {d.name}
                {!known && (
                  <span className="block text-sm font-normal text-fg-muted">
                    {d.menu_item_id ? "No recipe cost yet" : "Sold items not on the menu yet"}
                  </span>
                )}
              </th>
              <td className="num">{money(d.revenue_cents)}</td>
              <td className="num">{known ? money(d.food_cost_cents) : "Unknown"}</td>
              <td className="num">{known ? percent(d.food_cost_cents, d.revenue_cents) : "–"}</td>
              <td className="num font-semibold">{known ? money(d.gross_profit_cents) : "–"}</td>
            </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
