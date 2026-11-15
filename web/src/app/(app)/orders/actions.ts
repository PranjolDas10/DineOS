"use server";

import { redirect } from "next/navigation";

import { api, must } from "@/lib/api";

/** Rebuilds every order from the event log in the background, re-matching sold items to the
 * menu. Safe to run any number of times: the API's replay is idempotent. */
export async function rebuild() {
  must(await (await api()).POST("/v1/orders/replay"));
  redirect("/orders?rebuilt=1");
}

/** Puts a sold-but-unlisted item on the menu, then rebuilds so its past sales link to it.
 * `id` is made when the page renders, so a double click or a retry sends the same id and the
 * API answers 409 instead of creating the dish twice. */
export async function addToMenu(id: string, name: string, priceCents: number) {
  const client = await api(); // re-checks the session: a Server Action is a public endpoint
  const created = await client.POST("/v1/menu-items", { body: { id, name, price_cents: priceCents, portion_qty: 1 } });
  if (created.response.status !== 409) must(created);
  must(await client.POST("/v1/orders/replay"));
  redirect("/orders?rebuilt=1");
}
