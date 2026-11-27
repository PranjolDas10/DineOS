import Link from "next/link";
import { Bell, LogOut } from "lucide-react";

import { Mark } from "@/components/mark";
import { api, me as whoAmI } from "@/lib/api";

import { logout } from "../actions";
import { CommandMenu } from "./command-menu";
import { Nav } from "./nav";
import { ThemeToggle } from "./theme-toggle";

// Sidebar at laptop width (owner at night). On a phone: a slim top bar and a bottom tab bar in
// thumb reach; sign out and the theme live in the command menu there. Pages sit on the gray
// canvas and put their content in white panels.
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const [me, unread] = await Promise.all([
    whoAmI(),
    // The badge is a nicety: if alerts fail to load, show no count instead of breaking every page.
    // shortcut: counts a page of 100; add a count endpoint if a restaurant ever has more unread.
    api()
      .then((client) => client.GET("/v1/alerts", { params: { query: { unread: true, limit: 100 } } }))
      .then((result) => result.data?.items.length ?? 0),
  ]);
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-10 focus:rounded-md focus:bg-surface focus:p-3"
      >
        Skip to content
      </a>
      <header className="sticky top-0 z-20 flex items-center gap-x-4 border-b border-line bg-bg px-4 py-2.5 lg:h-dvh lg:flex-col lg:items-stretch lg:gap-y-5 lg:border-r lg:border-b-0 lg:px-3 lg:py-4">
        <p className="flex items-center gap-2.5 px-1.5 font-semibold tracking-tight">
          <Mark /> DineOS
        </p>
        <div className="ml-auto w-32 lg:ml-0 lg:w-auto">
          <CommandMenu />
        </div>
        <Link
          href="/alerts"
          className="relative -mx-2 grid size-11 place-items-center rounded-md text-fg-muted transition-colors hover:text-fg lg:hidden"
        >
          <Bell aria-hidden className="size-5" />
          <span className="sr-only">Alerts{unread > 0 && `, ${unread} new`}</span>
          {unread > 0 && (
            <span aria-hidden className="absolute top-1.5 right-1.5 size-2 rounded-full bg-danger ring-2 ring-bg" />
          )}
        </Link>
        <nav
          aria-label="Main"
          className="fixed inset-x-0 bottom-0 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] lg:static lg:border-0 lg:bg-transparent lg:pb-0"
        >
          <Nav counts={{ "/alerts": unread }} />
        </nav>
        <div className="hidden lg:mt-auto lg:grid lg:gap-3 lg:border-t lg:border-line lg:pt-3">
          <div className="hidden items-center gap-2.5 px-1.5 lg:flex">
            <span aria-hidden className="grid size-8 shrink-0 place-items-center rounded-md bg-accent-soft text-sm font-semibold text-accent-text">
              {me.restaurant.slice(0, 1).toUpperCase()}
            </span>
            <p className="min-w-0 text-sm">
              <span className="block truncate font-medium" title={me.restaurant}>
                {me.restaurant}
              </span>
              {me.email && (
                <span className="block truncate text-fg-muted" title={me.email}>
                  {me.email}
                </span>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2 lg:justify-between">
            <form action={logout}>
              <button
                type="submit"
                className="flex min-h-9 cursor-pointer items-center gap-2.5 rounded-md px-2.5 text-sm font-medium text-fg-muted transition-colors hover:bg-surface-sunken hover:text-fg"
              >
                <LogOut aria-hidden className="size-4" />
                Sign out
              </button>
            </form>
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main id="main" className="min-w-0 px-4 pt-6 pb-24 sm:px-8 lg:px-10 lg:py-8">
        {children}
      </main>
    </div>
  );
}
