"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { ACCESS, REFRESH, authRequest, storeTokens } from "@/lib/session";

export async function login(_: string | null, form: FormData): Promise<string | null> {
  const response = await authRequest("login", {
    email: String(form.get("email") ?? ""),
    password: String(form.get("password") ?? ""),
  }).catch(() => null);
  if (response?.status === 401) return "That email and password don't match. Check both and try again.";
  if (response?.status === 429) return "Too many attempts. Wait a minute, then try again.";
  if (!response?.ok) return "Can't reach the DineOS server right now. Try again in a moment.";
  storeTokens(await cookies(), await response.json());
  redirect("/");
}

export async function logout() {
  const jar = await cookies();
  const refresh = jar.get(REFRESH)?.value;
  // Revoke server-side too, so a copied refresh cookie stops working. Best effort: sign out anyway.
  if (refresh) await authRequest("logout", { refresh_token: refresh }).catch(() => null);
  jar.delete(ACCESS);
  jar.delete(REFRESH);
  redirect("/login");
}
