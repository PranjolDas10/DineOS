// Skeleton in the page's shape, so nothing jumps when the numbers arrive.
export default function Loading() {
  return (
    <div role="status" className="mx-auto grid max-w-6xl animate-pulse gap-6">
      <span className="sr-only">Loading</span>
      <div className="h-6 w-40 rounded-sm bg-surface-sunken" />
      <div className="h-12 w-3/4 rounded-sm bg-surface-sunken" />
      <div className="h-64 rounded-lg bg-surface-sunken" />
      <div className="grid gap-5">
        {[80, 45, 35].map((w) => (
          <div key={w} className="h-9 rounded-sm bg-surface-sunken" style={{ width: `${w}%` }} />
        ))}
      </div>
    </div>
  );
}
