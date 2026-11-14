import type { Metadata } from "next";
import { connection } from "next/server";
import { ChartNoAxesColumn, ReceiptText, ShieldCheck } from "lucide-react";

import { Mark } from "@/components/mark";

import { LoginForm } from "./login-form";

export const metadata: Metadata = { title: "Sign in" };

const POINTS = [
  { icon: ChartNoAxesColumn, title: "Profit per channel", text: "What dine-in and each delivery app leave after food, commission and labor." },
  { icon: ReceiptText, title: "Receipts keep costs current", text: "A photo of a supplier receipt updates ingredient prices and every dish that uses them." },
  { icon: ShieldCheck, title: "Books that add up", text: "Every sale is a balanced double-entry posting. Corrections reverse; nothing is edited." },
];

// Recruiter with 30 seconds: the form on the left, what the product is on the right.
export default async function LoginPage() {
  await connection(); // DEMO_LOGIN is read at request time, not baked in at build
  return (
    <main className="grid min-h-dvh bg-surface lg:grid-cols-2">
      <div className="grid place-items-center px-4 py-12">
        <div className="w-full max-w-sm">
          <p className="mb-12 flex items-center gap-2.5 font-semibold tracking-tight">
            <Mark /> DineOS
          </p>
          <h1 className="text-3xl font-semibold text-balance">Sign in to your restaurant</h1>
          <p className="mt-2 text-fg-muted">Food cost, profit by channel and the week&apos;s numbers.</p>
          <LoginForm demo={process.env.DEMO_LOGIN === "1"} />
        </div>
      </div>
      <aside className="hidden place-items-center border-l border-line bg-bg px-12 lg:grid">
        <div className="max-w-md">
          <p className="text-4xl leading-tight font-semibold tracking-tighter text-balance">
            Know what every plate earns, <span className="text-accent-text">after everything.</span>
          </p>
          <ul className="mt-10 grid gap-6">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span className="panel grid size-10 shrink-0 place-items-center">
                  <Icon aria-hidden className="size-4" />
                </span>
                <p>
                  <span className="block font-medium">{title}</span>
                  <span className="block text-fg-muted">{text}</span>
                </p>
              </li>
            ))}
          </ul>
        </div>
      </aside>
    </main>
  );
}
