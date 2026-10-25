"use server";

import { redirect } from "next/navigation";

import { api, type Schemas } from "@/lib/api";

/** Saves the owner's decisions. Returns an error message, or redirects to the list on success. */
export async function confirmReceipt(
  id: string,
  version: number,
  body: Schemas["ConfirmIn"],
  seconds: number,
): Promise<string> {
  const client = await api(); // re-checks the session: a Server Action is a public endpoint
  const { error, response } = await client.POST("/v1/receipts/{receipt_id}/confirm", {
    params: { path: { receipt_id: id }, header: { "if-match": `"${version}"` } },
    body,
  });
  if (response.status === 412) {
    return "This receipt changed since you opened it. Reload the page to see the latest, then save again.";
  }
  if (error) {
    const detail = (error as { detail?: unknown }).detail;
    return typeof detail === "string" ? detail : "The server didn't save this receipt. Check the lines and try again.";
  }
  const prices = body.lines.filter((l) => l.ingredient_id).length;
  redirect(`/receipts?saved=${prices}&secs=${Math.round(seconds)}`);
}
