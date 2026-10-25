"use server";

import { revalidatePath } from "next/cache";

import { api } from "@/lib/api";

type Times = { starts_at: string; ends_at: string; note: string | null };

/** Turns an API problem into a sentence for the dialog; null means it worked. */
function problem(status: number, error: unknown): string | null {
  if (status < 300) {
    revalidatePath("/schedule");
    return null;
  }
  if (status === 412) return "This shift changed since the page loaded. Close this and check the week again.";
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg.replace(/^Value error, /, "");
  return "The server didn't save this shift. Try again.";
}

export async function createShift(staffId: string, times: Times) {
  const { error, response } = await (await api()).POST("/v1/shifts", { body: { staff_id: staffId, ...times } });
  return problem(response.status, error);
}

export async function moveShift(id: string, version: number, times: Times) {
  const { error, response } = await (await api()).PATCH("/v1/shifts/{shift_id}", {
    params: { path: { shift_id: id }, header: { "if-match": `"${version}"` } },
    body: times,
  });
  return problem(response.status, error);
}

export async function deleteShift(id: string, version: number) {
  const { error, response } = await (await api()).DELETE("/v1/shifts/{shift_id}", {
    params: { path: { shift_id: id }, header: { "if-match": `"${version}"` } },
  });
  return problem(response.status, error);
}
