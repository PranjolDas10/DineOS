"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut, Moon, Search, Sun, type LucideIcon } from "lucide-react";

import { logout } from "../actions";
import { GROUPS } from "./nav";
import { setTheme } from "./theme-toggle";

type Command = { label: string; hint: string; icon: LucideIcon; run: () => void };

/** Ctrl/Cmd+K: jump to any page or run an action without the mouse. A native <dialog> gives
 * the focus trap, Esc and the inert page; the list is a filtered array with a roving highlight. */
export function CommandMenu() {
  const router = useRouter();
  const dialog = useRef<HTMLDialogElement>(null);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  const open = () => {
    setQuery("");
    setActive(0);
    dialog.current?.showModal();
  };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (dialog.current?.open) dialog.current.close();
        else open();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const commands: Command[] = [
    ...GROUPS.flatMap((g) => g.links).map((l) => ({
      label: l.label,
      hint: l.hint,
      icon: l.icon,
      run: () => router.push(l.href),
    })),
    { label: "Light theme", hint: "Switch the dashboard to light", icon: Sun, run: () => setTheme("light") },
    { label: "Dark theme", hint: "Switch the dashboard to dark", icon: Moon, run: () => setTheme("dark") },
    { label: "Sign out", hint: "End this session", icon: LogOut, run: () => void logout() },
  ];
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = commands.filter((c) => words.every((w) => `${c.label} ${c.hint}`.toLowerCase().includes(w)));
  const run = (command: Command | undefined) => {
    if (!command) return;
    dialog.current?.close();
    command.run();
  };

  return (
    <>
      <button
        type="button"
        onClick={open}
        className="flex min-h-9 w-full cursor-pointer items-center gap-2 rounded-md border border-line bg-surface px-2.5 text-sm text-fg-muted transition-colors hover:border-line-strong hover:text-fg"
      >
        <Search aria-hidden className="size-4" />
        <span className="flex-1 text-left">Search</span>
        <kbd className="kbd">Ctrl K</kbd>
      </button>
      <dialog
        ref={dialog}
        aria-label="Command menu"
        onClick={(e) => e.target === e.currentTarget && e.currentTarget.close()}
        className="panel m-auto mt-[18vh] w-[min(36rem,calc(100vw-2rem))] p-0 text-fg shadow-pop"
      >
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search aria-hidden className="size-4 text-fg-muted" />
          <input
            role="combobox"
            aria-expanded
            aria-controls="command-list"
            aria-activedescendant={shown[active] ? `command-${active}` : undefined}
            aria-label="Search pages and actions"
            placeholder="Where to?"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown" || e.key === "ArrowUp") {
                e.preventDefault();
                const step = e.key === "ArrowDown" ? 1 : -1;
                setActive((i) => (i + step + shown.length) % Math.max(shown.length, 1));
              } else if (e.key === "Enter") {
                e.preventDefault();
                run(shown[active]);
              }
            }}
            className="min-h-12 flex-1 bg-transparent outline-none placeholder:text-fg-muted"
          />
          <kbd className="kbd">Esc</kbd>
        </div>
        <ul id="command-list" role="listbox" aria-label="Results" className="max-h-80 overflow-y-auto p-1.5">
          {shown.map((command, i) => (
            <li
              key={command.label}
              id={`command-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseMove={() => setActive(i)}
              onClick={() => run(command)}
              className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md px-2.5 aria-selected:bg-surface-sunken"
            >
              <command.icon aria-hidden className="size-4 text-fg-muted" />
              <span className="font-medium">{command.label}</span>
              <span className="ml-auto text-sm text-fg-muted">{command.hint}</span>
            </li>
          ))}
        </ul>
        {shown.length === 0 && <p className="px-4 pb-6 text-center text-fg-muted">Nothing matches “{query}”.</p>}
      </dialog>
    </>
  );
}
