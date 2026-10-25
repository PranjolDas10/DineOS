import type { Metadata } from "next";
import { connection } from "next/server";

import { Mark } from "@/components/mark";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

export default async function LoginPage() {
  await connection(); // DEMO_LOGIN is read at request time, not baked in at build
  return (
    <main className="grid min-h-dvh place-items-center bg-bg px-4 py-12">
      <div className="w-full max-w-sm">
        <p className="mb-10 flex items-center gap-2 text-lg font-semibold">
          <Mark /> DineOS
        </p>
        <h1 className="text-2xl font-semibold text-balance">Sign in to your restaurant</h1>
        <p className="mt-2 text-fg-muted">Food cost, profit by channel and the week&apos;s numbers.</p>
        <LoginForm demo={process.env.DEMO_LOGIN === "1"} />
      </div>
    </main>
  );
}
