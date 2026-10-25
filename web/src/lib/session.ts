// Tokens live in httpOnly cookies set by this Next server; browser JavaScript never sees them.
export const API_URL = process.env.API_URL ?? "http://localhost:8000";
export const ACCESS = "dineos_access";
export const REFRESH = "dineos_refresh";

export type Tokens = { access_token: string; refresh_token: string; expires_in: number };

type CookieJar = {
  set(name: string, value: string, options: Record<string, unknown>): unknown;
};

export function storeTokens(jar: CookieJar, tokens: Tokens) {
  const base = {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
  };
  // Expire the access cookie a little early: no cookie means "refresh first" to the proxy.
  jar.set(ACCESS, tokens.access_token, { ...base, maxAge: Math.max(tokens.expires_in - 30, 0) });
  jar.set(REFRESH, tokens.refresh_token, { ...base, maxAge: 60 * 60 * 24 * 30 });
}

export async function authRequest(path: string, body: object): Promise<Response> {
  return fetch(`${API_URL}/v1/auth/${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
}
