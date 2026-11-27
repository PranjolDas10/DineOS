"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, CalendarDays, ChartNoAxesColumn, CookingPot, Inbox, ReceiptText, type LucideIcon } from "lucide-react";

export type Destination = { href: string; label: string; icon: LucideIcon; hint: string; tab?: false };

// One list feeds the sidebar and the command menu, so they can't drift apart. `tab: false` keeps a
// link out of the phone's bottom bar (five tabs at most); the top bar carries it there instead.
export const GROUPS: { title: string; links: Destination[] }[] = [
  {
    title: "Insights",
    links: [
      { href: "/", label: "Profit", icon: ChartNoAxesColumn, hint: "Sales, costs and what is left" },
      { href: "/menu", label: "Menu costs", icon: CookingPot, hint: "Food cost of every dish" },
    ],
  },
  {
    title: "Operations",
    links: [
      { href: "/alerts", label: "Alerts", icon: Bell, hint: "Price changes and overdue checklists", tab: false },
      { href: "/orders", label: "Orders", icon: Inbox, hint: "Every channel's orders, day by day" },
      { href: "/receipts", label: "Receipts", icon: ReceiptText, hint: "Review scanned supplier receipts" },
      { href: "/schedule", label: "Schedule", icon: CalendarDays, hint: "Shifts and labor for the week" },
    ],
  },
];

/** `counts` puts a number beside a link, e.g. unread alerts. */
export function Nav({ counts = {} }: { counts?: Record<string, number> }) {
  const pathname = usePathname();
  return (
    <div className="flex justify-around lg:grid lg:justify-normal lg:gap-5">
      {GROUPS.map((group) => (
        <div key={group.title} className="contents lg:block">
          <p className="mb-1 hidden px-2.5 text-xs font-medium text-fg-muted lg:block">{group.title}</p>
          <ul className="contents lg:grid lg:gap-0.5">
            {group.links.map(({ href, label, icon: Icon, tab }) => {
              const current = href === "/" ? pathname === "/" : pathname.startsWith(href);
              return (
                <li key={href} className={`min-w-0 flex-1 lg:flex-none ${tab === false ? "max-lg:hidden" : ""}`}>
                  <Link
                    href={href}
                    aria-current={current ? "page" : undefined}
                    className="relative flex min-h-14 flex-col items-center justify-center gap-1 px-1 text-[0.6875rem] font-medium whitespace-nowrap text-fg-muted transition-colors hover:text-fg aria-[current=page]:text-fg lg:min-h-9 lg:flex-row lg:justify-start lg:gap-2.5 lg:rounded-md lg:px-2.5 lg:text-sm lg:hover:bg-surface-sunken lg:aria-[current=page]:bg-surface-sunken"
                  >
                    <Icon aria-hidden className="size-5 lg:size-4" />
                    {label}
                    {counts[href] > 0 && (
                      <span className="absolute top-1.5 left-1/2 ml-1.5 rounded-full bg-primary px-1.5 text-[0.6875rem] leading-4 font-semibold text-on-primary lg:static lg:ml-auto lg:text-xs lg:leading-5">
                        {counts[href] >= 100 ? "99+" : counts[href]}
                        <span className="sr-only"> new</span>
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

/** Alerts on a phone: the bottom bar holds five tabs, so alerts get a bell in the top bar. */
export function AlertsBell({ unread }: { unread: number }) {
  const pathname = usePathname();
  return (
    <Link
      href="/alerts"
      aria-current={pathname.startsWith("/alerts") ? "page" : undefined}
      className="relative -mx-2 grid size-11 place-items-center rounded-md text-fg-muted transition-colors hover:text-fg aria-[current=page]:text-fg lg:hidden"
    >
      <Bell aria-hidden className="size-5" />
      <span className="sr-only">Alerts{unread > 0 && `, ${unread >= 100 ? "99+" : unread} new`}</span>
      {unread > 0 && <span aria-hidden className="absolute top-1.5 right-1.5 size-2 rounded-full bg-danger ring-2 ring-bg" />}
    </Link>
  );
}
