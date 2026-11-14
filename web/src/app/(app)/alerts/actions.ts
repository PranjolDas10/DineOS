"use server";

import { revalidatePath } from "next/cache";

import { api, must } from "@/lib/api";

/** Marks every unread alert read. The API call is idempotent, so a double click is harmless. */
export async function markAllRead() {
  const client = await api(); // re-checks the session: a Server Action is a public endpoint
  const { items } = must(await client.GET("/v1/alerts", { params: { query: { unread: true, limit: 200 } } }));
  await Promise.all(
    items.map((a) => client.POST("/v1/alerts/{alert_id}/read", { params: { path: { alert_id: a.id } } })),
  );
  revalidatePath("/", "layout"); // the sidebar count lives in the layout
}
