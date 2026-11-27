import type { Metadata } from "next";
import Link from "next/link";
import { ChevronRight, CircleAlert, CircleCheck, LoaderCircle, TriangleAlert } from "lucide-react";

import { api, must } from "@/lib/api";
import { money } from "@/lib/format";

export const metadata: Metadata = { title: "Receipts" };

const STATUS = {
  parsed: { label: "Ready to review", icon: TriangleAlert, className: "bg-warn-bg text-warn" },
  uploaded: { label: "Reading receipt…", icon: LoaderCircle, className: "bg-surface-sunken text-fg-muted" },
  failed: { label: "Couldn't read", icon: CircleAlert, className: "bg-danger-bg text-danger" },
  confirmed: { label: "Saved", icon: CircleCheck, className: "bg-ok-bg text-ok" },
} as const;

const day = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });

// Owner at night: receipts scanned on the phone during the day, waiting to be checked.
export default async function ReceiptsPage({ searchParams }: PageProps<"/receipts">) {
  const { saved, secs } = await searchParams;
  const client = await api();
  const { items } = must(await client.GET("/v1/receipts", { params: { query: { limit: 100 } } }));
  const waiting = items.filter((r) => r.status === "parsed").length;

  return (
    <div className="rise mx-auto grid max-w-6xl gap-6 [&>*]:min-w-0 [&>*]:max-w-3xl">
      <div>
        <h1 className="text-2xl font-semibold">Receipts</h1>
        <p className="text-fg-muted">
          {waiting === 0
            ? "Nothing to review. Scan supplier receipts with the phone app and they appear here."
            : `${waiting} waiting for you. Checking a receipt updates ingredient prices, and food cost with them.`}
        </p>
      </div>
      {saved !== undefined && (
        <p role="status" className="flex gap-2 rounded-md bg-ok-bg p-3 text-sm font-medium text-ok">
          <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0" />
          Saved. {saved} ingredient {saved === "1" ? "price" : "prices"} updated, in{" "}
          {Math.floor(Number(secs) / 60)} min {Number(secs) % 60} s.
        </p>
      )}
      <ul className="panel divide-y divide-line overflow-hidden">
        {items.map((r) => {
          const status = STATUS[r.status as keyof typeof STATUS] ?? STATUS.uploaded;
          const content = (
            <>
              <span className="min-w-0 flex-1">
                <span className="block font-medium">{r.supplier_name ?? "Unknown supplier"}</span>
                <span className="block text-sm text-fg-muted">
                  {r.receipt_date ? day.format(new Date(`${r.receipt_date}T12:00`)) : "No date"}
                  {r.total_cents !== null && `, ${money(r.total_cents)}`}
                </span>
              </span>
              <span className={`badge ${status.className}`}>
                <status.icon aria-hidden className="size-3.5" />
                {status.label}
              </span>
            </>
          );
          return (
            <li key={r.id}>
              {r.status === "parsed" ? (
                <Link href={`/receipts/${r.id}`} className="flex min-h-16 items-center gap-4 px-5 py-3 transition-colors hover:bg-bg">
                  {content}
                  <ChevronRight aria-hidden className="size-4 text-fg-muted" />
                </Link>
              ) : (
                <div className="flex min-h-16 items-center gap-4 px-5 py-3 pr-13">{content}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
