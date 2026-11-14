"use client";

import { useSyncExternalStore } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

const OPTIONS = [
  { value: "system", label: "Match the device", icon: Monitor },
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
] as const;
type Theme = (typeof OPTIONS)[number]["value"];

const EVENT = "dineos-theme";
const read = (): Theme => {
  const saved = document.documentElement.dataset.theme;
  return saved === "light" || saved === "dark" ? saved : "system";
};
const subscribe = (notify: () => void) => {
  window.addEventListener(EVENT, notify);
  return () => window.removeEventListener(EVENT, notify);
};

/** The choice lives on <html data-theme> (tokens.css keys off it) and in localStorage; the
 * script in the root layout restores it before first paint. "system" removes both. */
export function setTheme(theme: Theme) {
  if (theme === "system") {
    delete document.documentElement.dataset.theme;
    localStorage.removeItem("theme");
  } else {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }
  window.dispatchEvent(new Event(EVENT));
}

export function ThemeToggle() {
  // The server can't know the saved choice, so it renders "system" and the client corrects it.
  const theme = useSyncExternalStore(subscribe, read, () => "system" as Theme);
  return (
    <div role="group" aria-label="Theme" className="flex w-fit rounded-md border border-line p-0.5">
      {OPTIONS.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          aria-pressed={theme === value}
          aria-label={label}
          title={label}
          onClick={() => setTheme(value)}
          className="grid size-7 cursor-pointer place-items-center rounded-sm text-fg-muted transition-colors hover:text-fg aria-pressed:bg-surface-sunken aria-pressed:text-fg"
        >
          <Icon aria-hidden className="size-3.5" />
        </button>
      ))}
    </div>
  );
}
