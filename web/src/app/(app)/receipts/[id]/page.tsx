import type { Metadata } from "next";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";

import { api, must } from "@/lib/api";

import { Review } from "./review";

export const metadata: Metadata = { title: "Review receipt" };

export default async function ReviewPage({ params }: PageProps<"/receipts/[id]">) {
  const { id } = await params;
  const client = await api();
  const result = await client.GET("/v1/receipts/{receipt_id}", { params: { path: { receipt_id: id } } });
  const receipt = must(result);
  const version = Number(result.response.headers.get("etag")?.replace(/\D/g, ""));
  // shortcut: first 200 ingredients; search the API instead when a restaurant has more.
  const { items: ingredients } = must(await client.GET("/v1/ingredients", { params: { query: { limit: 200 } } }));

  return (
    <div className="mx-auto grid max-w-7xl gap-6 [&>*]:min-w-0">
      <Link href="/receipts" className="inline-flex min-h-8 w-fit items-center gap-1 rounded-sm text-sm font-medium text-fg-muted transition-colors hover:text-fg">
        <ChevronLeft aria-hidden className="size-4" />
        Receipts
      </Link>
      {receipt.status === "parsed" ? (
        <Review receipt={receipt} version={version} ingredients={ingredients} />
      ) : (
        <p className="text-fg-muted">This receipt isn&apos;t waiting for review (it&apos;s {receipt.status}).</p>
      )}
    </div>
  );
}
