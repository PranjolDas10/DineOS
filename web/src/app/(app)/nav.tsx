"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CalendarDays, ChartNoAxesColumn, CookingPot, ReceiptText } from "lucide-react";

const LINKS = [
  { href: "/", label: "Profit", icon: ChartNoAxesColumn },
  { href: "/receipts", label: "Receipts", icon: ReceiptText },
  { href: "/menu", label: "Menu costs", icon: CookingPot },
  { href: "/schedule", label: "Schedule", icon: CalendarDays },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <ul className="flex gap-1 lg:grid">
      {LINKS.map(({ href, label, icon: Icon }) => {
        const current = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <li key={href}>
            <Link
              href={href}
              aria-current={current ? "page" : undefined}
              className="relative flex min-h-11 items-center gap-3 rounded-md px-3 font-medium text-fg-muted hover:bg-surface-sunken hover:text-fg aria-[current=page]:bg-surface aria-[current=page]:text-fg aria-[current=page]:shadow-[inset_3px_0_0_var(--primary)]"
            >
              <Icon aria-hidden className="size-5" />
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
