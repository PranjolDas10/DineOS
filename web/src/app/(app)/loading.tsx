// Skeleton in the page's shape, so nothing jumps when the numbers arrive.
export default function Loading() {
  return (
    <div aria-busy="true" aria-label="Loading" className="mx-auto grid max-w-6xl animate-pulse gap-8">
      <div className="h-6 w-40 rounded-sm bg-surface-sunken" />
      <div className="h-12 w-3/4 rounded-sm bg-surface-sunken" />
      <div className="h-24 rounded-lg bg-surface-sunken" />
      <div className="grid gap-5">
        {[80, 45, 35].map((w) => (
          <div key={w} className="h-9 rounded-sm bg-surface-sunken" style={{ width: `${w}%` }} />
        ))}
      </div>
    </div>
  );
}
