"use client";

import { useActionState } from "react";
import { CircleAlert } from "lucide-react";

import { login } from "../actions";

export function LoginForm({ demo }: { demo: boolean }) {
  const [error, action, pending] = useActionState(login, null);
  return (
    <form action={action} className="mt-8 grid gap-5" aria-describedby={error ? "login-error" : undefined}>
      <label className="grid gap-1.5 text-sm font-medium">
        Email
        <input
          name="email"
          type="email"
          autoComplete="username"
          required
          defaultValue={demo ? "demo@dineos.dev" : undefined}
          className="field"
        />
      </label>
      <label className="grid gap-1.5 text-sm font-medium">
        Password
        <input
          name="password"
          type="password"
          autoComplete="current-password"
          required
          defaultValue={demo ? "demo-password-123" : undefined}
          className="field"
        />
      </label>
      {error && (
        <p id="login-error" role="alert" className="flex gap-2 rounded-md bg-danger-bg p-3 text-danger">
          <CircleAlert aria-hidden className="mt-0.5 size-5 shrink-0" />
          {error}
        </p>
      )}
      <button type="submit" disabled={pending} className="btn-primary">
        {pending ? "Signing in…" : "Sign in"}
      </button>
      {demo && (
        <p className="text-sm text-fg-muted">
          This is the public demo. The sign-in is filled in, and every number is sample data.
        </p>
      )}
    </form>
  );
}
