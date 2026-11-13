/** The DineOS mark: a plate seen from above with one green slice, the part you keep.
 * Decorative; the wordmark next to it carries the name. */
export function Mark() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="size-6 shrink-0">
      <rect width="24" height="24" rx="6" className="fill-primary" />
      <circle cx="12" cy="12" r="6.5" fill="none" strokeWidth="1.5" className="stroke-on-primary" />
      <path d="M12 12V5.5A6.5 6.5 0 0 1 18.5 12Z" className="fill-accent" />
    </svg>
  );
}
