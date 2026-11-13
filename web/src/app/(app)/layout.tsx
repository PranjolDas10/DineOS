import { LogOut } from "lucide-react";

import { Mark } from "@/components/mark";
import { api, me as whoAmI, must } from "@/lib/api";

import { logout } from "../actions";
import { CommandMenu } from "./command-menu";
import { Nav } from "./nav";
import { ThemeToggle } from "./theme-toggle";

// Sidebar at laptop width (owner at night), a top bar below it. Pages sit on the gray canvas
// and put their content in white panels.
export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const [me, unread] = await Promise.all([
    whoAmI(),
    api()
      .then((client) => client.GET("/v1/alerts", { params: { query: { unread: true, limit: 100 } } }))
      .then(must),
  ]);
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-10 focus:rounded-md focus:bg-surface focus:p-3"
      >
        Skip to content
      </a>
      <header className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-line bg-bg px-4 py-3 lg:sticky lg:top-0 lg:h-dvh lg:flex-col lg:flex-nowrap lg:items-stretch lg:gap-y-5 lg:border-r lg:border-b-0 lg:px-3 lg:py-4">
        <p className="flex items-center gap-2.5 px-1.5 font-semibold tracking-tight">
          <Mark /> DineOS
        </p>
        <div className="ml-auto w-36 lg:ml-0 lg:w-auto">
          <CommandMenu />
        </div>
        <nav aria-label="Main" className="order-last w-full lg:order-none lg:w-auto">
          <Nav counts={{ "/alerts": unread.items.length }} />
        </nav>
        <div className="flex items-center gap-2 lg:mt-auto lg:grid lg:gap-3 lg:border-t lg:border-line lg:pt-3">
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
      <main id="main" className="min-w-0 px-4 py-6 sm:px-8 lg:px-10 lg:py-8">
        {children}
      </main>
    </div>
  );
}
