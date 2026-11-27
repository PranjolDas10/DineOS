import type { Metadata } from "next";
import Link from "next/link";
import { ArrowRight, BellOff, CheckCheck, ClipboardList, Tags, type LucideIcon } from "lucide-react";

import { api, must } from "@/lib/api";

import { markAllRead } from "./actions";

export const metadata: Metadata = { title: "Alerts" };

// Where each kind of alert sends the owner, and its icon. Unknown kinds still list, without a link.
const KINDS: Record<string, { icon: LucideIcon; href?: string; action?: string }> = {
  price_change: { icon: Tags, href: "/menu", action: "See the dishes" },
  checklist_overdue: { icon: ClipboardList },
};

const when = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

// Owner at night: what happened today that needs a look. Newest first, unread marked.
export default async function AlertsPage() {
  const client = await api();
  const { items } = must(await client.GET("/v1/alerts", { params: { query: { limit: 100 } } }));
  const unread = items.filter((a) => a.read_at === null).length;

  return (
    <div className="rise mx-auto grid max-w-6xl gap-6 [&>*]:min-w-0 [&>*]:max-w-3xl">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Alerts</h1>
          <p className="text-fg-muted">
            {unread === 0 ? "Nothing new." : `${unread} new.`} Price changes from checked receipts and overdue
            checklists land here.
          </p>
        </div>
        {unread > 0 && (
          <form action={markAllRead}>
            <button type="submit" className="btn-secondary min-h-9 text-sm">
              <CheckCheck aria-hidden className="size-4" />
              Mark all read
            </button>
          </form>
        )}
      </div>

      {items.length === 0 ? (
        <section className="panel grid justify-items-center gap-2 p-10 text-center">
          <BellOff aria-hidden className="size-6 text-fg-muted" />
          <h2 className="font-semibold">No alerts yet</h2>
          <p className="max-w-[45ch] text-fg-muted">
            When a checked receipt moves an ingredient price by 5% or more, it shows up here.
          </p>
        </section>
      ) : (
        <ul className="panel divide-y divide-line overflow-hidden">
          {items.map((a) => {
            const kind = KINDS[a.kind] ?? { icon: Tags };
            const isNew = a.read_at === null;
            return (
              <li key={a.id} className="flex gap-4 px-5 py-4">
                <span className={`grid size-9 shrink-0 place-items-center rounded-md ${isNew ? "bg-accent-soft text-accent-text" : "bg-surface-sunken text-fg-muted"}`}>
                  <kind.icon aria-hidden className="size-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="flex flex-wrap items-baseline gap-x-2">
                    <span className={isNew ? "font-semibold" : "font-medium text-fg-muted"}>{a.title}</span>
                    {isNew && <span className="badge bg-accent-soft text-accent-text">New</span>}
                  </p>
                  <p className="text-sm text-fg-muted">{a.body}</p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-3 text-sm text-fg-muted">
                    <time dateTime={a.created_at}>{when.format(new Date(a.created_at))}</time>
                    {kind.href && (
                      <Link href={kind.href} className="inline-flex items-center gap-1 font-medium text-accent-text">
                        {kind.action}
                        <ArrowRight aria-hidden className="size-3.5" />
                      </Link>
                    )}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
