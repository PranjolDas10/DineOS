import "server-only";

import createClient from "openapi-fetch";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import type { components, paths } from "./api-schema";
import { ACCESS, API_URL } from "./session";

export type Schemas = components["schemas"];

/** Typed API client for the signed-in owner. Server-side only: the token never reaches the browser. */
export async function api() {
  const token = (await cookies()).get(ACCESS)?.value;
  if (!token) redirect("/login");
  const client = createClient<paths>({
    baseUrl: API_URL,
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  client.use({
    onResponse({ response }) {
      if (response.status === 401) redirect("/login");
    },
  });
  return client;
}

/** Unwraps an API result; errors reach the route's error boundary, which offers a retry. */
export function must<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data === undefined) {
    throw new Error(`API ${result.response.status} on ${new URL(result.response.url).pathname}`);
  }
  return result.data;
}
