import type { Metadata } from "next";
import Link from "next/link";
import { ChevronDown, ChevronLeft, ChevronRight, CircleAlert, CircleCheck, CircleHelp, Inbox, LoaderCircle } from "lucide-react";

import { api, me, must } from "@/lib/api";
import { amount, channelName, money, moneyWhole } from "@/lib/format";
import { addDays, dayLabel, zoned, zonedToUtc } from "@/lib/time";

import { addToMenu, rebuild } from "./actions";

export const metadata: Metadata = { title: "Orders" };

const UNMATCHED_DAYS = 28;
const IMPORT_STATUS = {
  uploaded: { label: "Importing…", icon: LoaderCircle, className: "bg-surface-sunken text-fg-muted" },
  imported: { label: "Imported", icon: CircleCheck, className: "bg-ok-bg text-ok" },
  failed: { label: "Couldn't import", icon: CircleAlert, className: "bg-danger-bg text-danger" },
} as const;

/** A UUIDv7 (48-bit millisecond time, then random bits), like every id the API makes: ids
 * sort by creation time, which is what keeps cursor pagination in a stable order. */
function uuidv7() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const now = Date.now();
  for (let i = 0; i < 6; i++) bytes[i] = Math.floor(now / 2 ** (8 * (5 - i))) % 256; // big-endian ms
  bytes[6] = 0x70 | (bytes[6] & 0x0f); // version 7
  bytes[8] = 0x80 | (bytes[8] & 0x3f); // RFC variant
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

const one = (v: string | string[] | undefined) => (typeof v === "string" ? v : undefined);

// Owner at night: every channel's orders for one day in one list. Did the delivery apps and
// the till agree with what the kitchen felt? And which sales is the profit report blind to?
export default async function OrdersPage({ searchParams }: PageProps<"/orders">) {
  const params = await searchParams;
  const { timezone: tz, today } = await me();
  const asked = one(params.day);
  const day = asked && /^\d{4}-\d{2}-\d{2}$/.test(asked) && asked <= today ? asked : today;
  const openId = one(params.order);
  const stamp = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZone: tz });
  const at = (d: string) => zonedToUtc(d, "00:00", tz).toISOString();

  const client = await api();
  const [{ items: orders }, unmatched, imports, open] = await Promise.all([
    client.GET("/v1/orders", { params: { query: { start: at(day), end: at(addDays(day, 1)) } } }).then(must),
    client.GET("/v1/orders/unmatched", { params: { query: { since: at(addDays(today, -UNMATCHED_DAYS)) } } }).then(must),
    client.GET("/v1/imports", { params: { query: { limit: 5 } } }).then(must),
    // A stale or mistyped order id just shows the list with nothing open.
    openId ? client.GET("/v1/orders/{order_id}", { params: { path: { order_id: openId } } }).then((r) => r.data) : undefined,
  ]);

  const sales = orders.reduce((sum, o) => sum + o.subtotal_cents, 0);
  const byChannel = new Map<string, { count: number; cents: number }>();
  for (const o of orders) {
    const c = byChannel.get(o.channel) ?? { count: 0, cents: 0 };
    byChannel.set(o.channel, { count: c.count + 1, cents: c.cents + o.subtotal_cents });
  }
  const channels = [...byChannel].map(([channel, c]) => ({ channel, ...c })).sort((a, b) => b.cents - a.cents);
  // Orders per local hour, from the first busy hour to the last.
  const perHour = new Map<number, number>();
  for (const o of orders) {
    const h = Number(zoned(o.placed_at, tz).time.slice(0, 2));
    perHour.set(h, (perHour.get(h) ?? 0) + 1);
  }
  const hours = perHour.size ? Array.from({ length: Math.max(...perHour.keys()) - Math.min(...perHour.keys()) + 1 }, (_, i) => Math.min(...perHour.keys()) + i) : [];
  const peak = Math.max(...perHour.values(), 1);
  const busiest = [...perHour].sort((a, b) => b[1] - a[1])[0];
  const unmatchedCents = unmatched.items.reduce((sum, i) => sum + i.sales_cents, 0);
  const href = (d: string, order?: string) => `/orders?day=${d}${order ? `&order=${order}` : ""}`;

  return (
    <div className="rise mx-auto grid max-w-6xl gap-6 [&>*]:min-w-0">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Orders</h1>
          <p className="max-w-[65ch] text-fg-muted">Dine-in, takeout and every delivery app in one list, a day at a time.</p>
        </div>
        <nav aria-label="Day" className="flex items-center gap-2">
          <Link href={href(addDays(day, -1))} className="grid size-9 place-items-center rounded-md border border-line-strong bg-surface transition-colors hover:bg-surface-sunken">
            <ChevronLeft aria-hidden className="size-4" />
            <span className="sr-only">Previous day</span>
          </Link>
          <p className="min-w-28 text-center font-medium tabular-nums">{day === today ? "Today" : dayLabel(day)}</p>
          {day < today ? (
            <>
              <Link href={href(addDays(day, 1))} className="grid size-9 place-items-center rounded-md border border-line-strong bg-surface transition-colors hover:bg-surface-sunken">
                <ChevronRight aria-hidden className="size-4" />
                <span className="sr-only">Next day</span>
              </Link>
              <Link href="/orders" className="btn-secondary min-h-9 text-sm">
                Today
              </Link>
            </>
          ) : (
            <span role="link" aria-disabled="true" className="grid size-9 place-items-center rounded-md border border-line text-fg-muted opacity-50">
              <ChevronRight aria-hidden className="size-4" />
              <span className="sr-only">Next day</span>
            </span>
          )}
        </nav>
      </div>

      {one(params.rebuilt) !== undefined && (
        <p role="status" className="flex gap-2 rounded-md bg-ok-bg p-3 text-sm font-medium text-ok">
          <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0" />
          Rebuilding orders from the log in the background. Reload in a moment to see the result.
        </p>
      )}

      {unmatched.items.length > 0 && (
        <section aria-labelledby="unmatched" className="panel">
          <div className="flex gap-3 border-b border-line px-5 py-4">
            <CircleHelp aria-hidden className="mt-1 size-5 shrink-0 text-warn" />
            <div>
              <p className="eyebrow">Not on the menu, last {UNMATCHED_DAYS} days</p>
              <h2 id="unmatched" className="text-xl font-semibold text-balance">
                {moneyWhole(unmatchedCents)} of sales {unmatched.items.length === 1 ? "is" : "are"} from{" "}
                {unmatched.items.length === 1 ? "an item" : `${unmatched.items.length} items`} the menu doesn&apos;t have.
              </h2>
              <p className="max-w-[70ch] text-sm text-fg-muted">
                The till sold {unmatched.items.length === 1 ? "it" : "them"} under a name no menu item has, so the profit report counts the sale
                with no food cost. Add the item and its past sales link up.
              </p>
            </div>
          </div>
          <ul className="divide-y divide-line">
            {unmatched.items.map((i) => {
              // What it usually sold for: the best guess at its menu price.
              const price = Math.round(i.sales_cents / Number(i.quantity));
              return (
                <li key={i.name} className="flex flex-wrap items-center justify-between gap-x-6 gap-y-2 px-5 py-3">
                  <p className="min-w-0">
                    <span className="block font-medium">{i.name}</span>
                    <span className="block text-sm text-fg-muted tabular-nums">
                      {amount(Number(i.quantity))} sold in {i.orders} {i.orders === 1 ? "order" : "orders"}, {money(i.sales_cents)}. Last on{" "}
                      {stamp.format(new Date(i.last_sold_at))}.
                    </span>
                  </p>
                  {/* No price to suggest for a line that was all refunds or zero quantity. */}
                  {Number.isFinite(price) && price >= 0 && (
                  <form action={addToMenu.bind(null, uuidv7(), i.name, price)}>
                    <button type="submit" className="btn-secondary min-h-9 text-sm">
                      Add to menu at {money(price)}
                    </button>
                  </form>
                  )}
                </li>
              );
            })}
          </ul>
          <form action={rebuild} className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-5 py-3">
            <p className="text-sm text-fg-muted">Renamed a dish instead? Rebuild to match old sales to the new name.</p>
            <button type="submit" className="btn-secondary min-h-9 text-sm">
              Rebuild orders
            </button>
          </form>
        </section>
      )}

      {orders.length === 0 ? (
        <section className="panel grid justify-items-center gap-2 p-10 text-center">
          <Inbox aria-hidden className="size-6 text-fg-muted" />
          <h2 className="font-semibold">No orders on {day === today ? "today yet" : dayLabel(day)}</h2>
          <p className="max-w-[45ch] text-fg-muted">Orders appear here when a sales export from the till or a delivery app is imported.</p>
        </section>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] [&>*]:min-w-0">
            <section aria-labelledby="by-channel" className="panel p-5">
              <p className="eyebrow">Sales before tax and tips</p>
              <h2 id="by-channel" className="text-2xl font-semibold tracking-tight tabular-nums">
                {money(sales)} <span className="text-base font-normal text-fg-muted">from {orders.length} orders</span>
              </h2>
              <ul className="grid gap-3 pt-4">
                {channels.map((c) => (
                  <li key={c.channel}>
                    <p className="flex items-baseline justify-between gap-3 text-sm">
                      <span className="font-medium">{channelName(c.channel)}</span>
                      <span className="text-fg-muted tabular-nums">
                        {c.count} {c.count === 1 ? "order" : "orders"}, {money(c.cents)}
                      </span>
                    </p>
                    <span aria-hidden className="mt-1 block h-1.5 rounded-full bg-surface-sunken">
                      <span className="grow-across block h-full rounded-full bg-chart-food" style={{ width: `${sales ? (c.cents / sales) * 100 : 0}%` }} />
                    </span>
                  </li>
                ))}
              </ul>
            </section>

            <section aria-labelledby="rhythm" className="panel grid grid-rows-[auto_1fr] p-5">
              <div>
                <p className="eyebrow">Orders by hour</p>
                <h2 id="rhythm" className="text-xl font-semibold">
                  Busiest from {busiest[0]}:00, with {busiest[1]} {busiest[1] === 1 ? "order" : "orders"}.
                </h2>
              </div>
              {/* Decorative: the heading carries the finding, the list below has every order. */}
              <div aria-hidden className="flex min-h-28 items-end gap-1.5 pt-4">
                {hours.map((h) => {
                  const n = perHour.get(h) ?? 0;
                  return (
                    <div key={h} className="flex h-full min-w-0 flex-1 flex-col justify-end gap-1 text-center">
                      <span className="text-xs text-fg-muted tabular-nums">{n || ""}</span>
                      <span className={`grow-in rounded-sm ${h === busiest[0] ? "bg-chart-food" : "bg-chart-labor"}`} style={{ height: `${(n / peak) * 70}%`, minHeight: n ? 2 : 0 }} />
                      <span className="text-xs text-fg-muted tabular-nums">{h}</span>
                    </div>
                  );
                })}
              </div>
            </section>
          </div>

          <div className="panel overflow-x-auto">
            <table className="data-table">
              <caption className="sr-only">Orders on {dayLabel(day)}, newest first. Open one to see its items.</caption>
              <thead>
                <tr>
                  <th scope="col">Time</th>
                  <th scope="col">Channel</th>
                  <th scope="col" className="max-sm:hidden">Order</th>
                  <th scope="col" className="num">Total</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o) => {
                  const isOpen = open?.id === o.id;
                  return [
                    <tr key={o.id} id={o.id}>
                      <th scope="row" className="tabular-nums">
                        <Link
                          href={isOpen ? href(day) : href(day, o.id)}
                          scroll={false}
                          aria-expanded={isOpen}
                          className="link inline-flex items-center gap-1.5"
                        >
                          <ChevronDown aria-hidden className={`size-4 text-fg-muted transition-transform ${isOpen ? "" : "-rotate-90"}`} />
                          {zoned(o.placed_at, tz).time}
                          <span className="sr-only">, order {o.external_id}</span>
                        </Link>
                      </th>
                      <td>{channelName(o.channel)}</td>
                      <td className="text-fg-muted tabular-nums max-sm:hidden">{o.external_id}</td>
                      <td className="num tabular-nums">{money(o.total_cents)}</td>
                    </tr>,
                    isOpen && (
                      <tr key={`${o.id}-items`} className="bg-bg">
                        <td colSpan={4}>
                          <ul className="grid max-w-xl gap-1.5 text-sm sm:pl-6">
                            {open.items.map((item, n) => (
                              <li key={n} className="flex flex-wrap items-baseline justify-between gap-x-4">
                                <span>
                                  <span className="text-fg-muted tabular-nums">{amount(Number(item.quantity))} ×</span> {item.name}
                                  {item.menu_item_id === null && (
                                    <span className="badge ml-2 bg-warn-bg text-warn">
                                      <CircleHelp aria-hidden className="size-3.5" />
                                      Not on the menu
                                    </span>
                                  )}
                                </span>
                                <span className="tabular-nums">{money(item.line_total_cents)}</span>
                              </li>
                            ))}
                            <li className="flex justify-between gap-4 border-t border-line pt-1.5 text-fg-muted tabular-nums">
                              <span>
                                Tax {money(open.tax_cents)}, tip {money(open.tip_cents)}
                              </span>
                              <span className="font-medium text-fg">{money(open.total_cents)}</span>
                            </li>
                          </ul>
                        </td>
                      </tr>
                    ),
                  ];
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {imports.items.length > 0 && (
        <section aria-labelledby="imports" className="panel">
          <h2 id="imports" className="border-b border-line px-5 py-4 font-semibold">
            Latest imports
          </h2>
          <ul className="divide-y divide-line">
            {imports.items.map((i) => {
              const status = IMPORT_STATUS[i.status as keyof typeof IMPORT_STATUS] ?? IMPORT_STATUS.uploaded;
              return (
                <li key={i.id} className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 px-5 py-3">
                  <p className="min-w-0">
                    <span className="block font-medium">{stamp.format(new Date(i.created_at))}</span>
                    <span className="block text-sm text-fg-muted">
                      {i.status === "failed"
                        ? i.error
                        : i.status === "imported"
                          ? // Duplicates are the point: the same export imported twice changes nothing.
                            `${i.orders_new} new, ${i.orders_updated} corrected, ${i.duplicates} already here`
                          : "Reading the file"}
                    </span>
                  </p>
                  <span className={`badge ${status.className}`}>
                    <status.icon aria-hidden className="size-3.5" />
                    {status.label}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
