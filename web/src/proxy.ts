import { NextResponse, type NextRequest } from "next/server";

import { ACCESS, REFRESH, authRequest, storeTokens, type Tokens } from "@/lib/session";

// Refresh tokens rotate and a reused one revokes the whole session. Parallel requests (prefetches)
// carry the same refresh cookie, so they share one refresh call instead of racing.
// shortcut: per-process map, fine for one Next server; a shared lock if it ever runs as N replicas.
const inflight = new Map<string, Promise<Tokens | null>>();

function refreshOnce(token: string): Promise<Tokens | null> {
  let pending = inflight.get(token);
  if (!pending) {
    pending = authRequest("refresh", { refresh_token: token }).then((r) => (r.ok ? r.json() : null));
    inflight.set(token, pending);
    setTimeout(() => inflight.delete(token), 30_000);
  }
  return pending;
}

export async function proxy(request: NextRequest) {
  const onLogin = request.nextUrl.pathname === "/login";
  if (onLogin || request.cookies.has(ACCESS)) return NextResponse.next();

  const refresh = request.cookies.get(REFRESH)?.value;
  const tokens = refresh ? await refreshOnce(refresh) : null;
  if (!tokens) {
    const response = NextResponse.redirect(new URL("/login", request.url));
    response.cookies.delete(REFRESH);
    return response;
  }
  // Hand the new access token to this request's server components, and the browser for the next.
  request.cookies.set(ACCESS, tokens.access_token);
  const response = NextResponse.next({ request: { headers: request.headers } });
  storeTokens(response.cookies, tokens);
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|icon.svg).*)"],
};
