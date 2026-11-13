"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bell, CalendarDays, ChartNoAxesColumn, CookingPot, ReceiptText, type LucideIcon } from "lucide-react";

export type Destination = { href: string; label: string; icon: LucideIcon; hint: string };

// One list feeds the sidebar and the command menu, so they can't drift apart.
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
      { href: "/alerts", label: "Alerts", icon: Bell, hint: "Price changes and overdue checklists" },
      { href: "/receipts", label: "Receipts", icon: ReceiptText, hint: "Review scanned supplier receipts" },
      { href: "/schedule", label: "Schedule", icon: CalendarDays, hint: "Shifts and labor for the week" },
    ],
  },
];

/** `counts` puts a number beside a link, e.g. unread alerts. */
export function Nav({ counts = {} }: { counts?: Record<string, number> }) {
  const pathname = usePathname();
  return (
    <div className="flex gap-1 overflow-x-auto lg:grid lg:gap-5 lg:overflow-visible">
      {GROUPS.map((group) => (
        <div key={group.title} className="contents lg:block">
          <p className="mb-1 hidden px-2.5 text-xs font-medium text-fg-muted lg:block">{group.title}</p>
          <ul className="flex gap-1 lg:grid lg:gap-0.5">
            {group.links.map(({ href, label, icon: Icon }) => {
              const current = href === "/" ? pathname === "/" : pathname.startsWith(href);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    aria-current={current ? "page" : undefined}
                    className="flex min-h-9 items-center gap-2.5 rounded-md px-2.5 text-sm font-medium whitespace-nowrap text-fg-muted transition-colors hover:bg-surface-sunken hover:text-fg aria-[current=page]:bg-surface-sunken aria-[current=page]:text-fg"
                  >
                    <Icon aria-hidden className="size-4" />
                    {label}
                    {counts[href] > 0 && (
                      <span className="ml-auto rounded-full bg-primary px-1.5 text-xs leading-5 font-semibold text-on-primary">
                        {counts[href]}
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
