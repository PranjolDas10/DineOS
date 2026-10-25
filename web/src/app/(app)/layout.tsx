import { LogOut } from "lucide-react";

import { Mark } from "@/components/mark";

import { logout } from "../actions";
import { Nav } from "./nav";

// Sidebar at laptop width (owner at night), a top bar below it.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-10 focus:rounded-md focus:bg-surface focus:p-3"
      >
        Skip to content
      </a>
      <header className="flex flex-wrap items-center gap-x-6 gap-y-2 border-b border-line bg-bg px-4 py-3 lg:sticky lg:top-0 lg:h-dvh lg:flex-col lg:flex-nowrap lg:items-stretch lg:border-r lg:border-b-0 lg:px-3 lg:py-6">
        <p className="flex items-center gap-2 px-3 text-lg font-semibold">
          <Mark /> DineOS
        </p>
        <nav aria-label="Main" className="order-last w-full lg:order-none lg:mt-6 lg:w-auto">
          <Nav />
        </nav>
        <form action={logout} className="ml-auto lg:mt-auto lg:ml-0">
          <button
            type="submit"
            className="flex min-h-11 w-full cursor-pointer items-center gap-3 rounded-md px-3 font-medium text-fg-muted hover:bg-surface-sunken hover:text-fg"
          >
            <LogOut aria-hidden className="size-5" />
            Sign out
          </button>
        </form>
      </header>
      <main id="main" className="min-w-0 px-4 py-8 sm:px-8 lg:px-12 lg:py-10">
        {children}
      </main>
    </div>
  );
}
