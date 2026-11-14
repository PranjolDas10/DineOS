"use client";

import { RotateCw } from "lucide-react";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="mx-auto grid max-w-xl gap-4 py-12">
      <h1 className="text-2xl font-semibold">These numbers didn&apos;t load</h1>
      <p className="text-fg-muted">
        The DineOS server didn&apos;t answer or returned an error. Your data is safe; try loading the page
        again.
      </p>
      <button
        type="button"
        onClick={reset}
        className="btn-primary w-fit"
      >
        <RotateCw aria-hidden className="size-4" />
        Try again
      </button>
    </div>
  );
}
