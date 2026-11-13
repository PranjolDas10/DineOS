import type { Schemas } from "@/lib/api";
import { money } from "@/lib/format";

type Matrix = Schemas["MenuMatrix"];
type Kind = NonNullable<Schemas["MatrixDish"]["kind"]>;

// What to do with each kind: the reason the matrix exists.
const KINDS: Record<Kind, { title: string; rule: string; advice: string }> = {
  star: { title: "Stars", rule: "Sell well, earn well", advice: "Protect them. Keep the recipe and the price steady." },
  plowhorse: { title: "Plowhorses", rule: "Sell well, earn little", advice: "Raise the price a little or trim the portion cost." },
  puzzle: { title: "Puzzles", rule: "Earn well, sell little", advice: "Sell them harder: menu position, a server mention." },
  dog: { title: "Dogs", rule: "Sell little, earn little", advice: "Rework or retire, unless regulars come for it." },
};
// Reading order of the plot: top row first (high margin), left to right (low to high sales).
const ORDER: Kind[] = ["puzzle", "star", "dog", "plowhorse"];

// Owner at night, once a month: which dishes to push, reprice or drop. One dot per dish:
// right means it sells, up means a plate earns. The same dishes are listed by kind beside it,
// so the plot is never the only way to read this.
export function MenuMatrix({ matrix }: { matrix: Matrix }) {
  const placed = matrix.dishes.filter((d) => d.kind !== null && d.margin_cents !== null);
  if (matrix.popularity_bar === null || matrix.margin_bar_cents === null || placed.length === 0) return null;
  const unplaced = matrix.dishes.length - placed.length;

  // Both axes run a little past the data, and far enough to keep each bar inside the box.
  const maxUnits = Math.max(...placed.map((d) => Number(d.units_sold)), Number(matrix.popularity_bar) * 1.5) * 1.12;
  const maxMargin = Math.max(...placed.map((d) => d.margin_cents!), matrix.margin_bar_cents * 1.5) * 1.12;
  const x = (units: string | number) => (Number(units) / maxUnits) * 100;
  const y = (cents: number) => (Math.max(cents, 0) / maxMargin) * 100;
  const [barX, barY] = [x(matrix.popularity_bar), y(matrix.margin_bar_cents)];

  return (
    <section aria-labelledby="matrix" className="panel">
      <div className="border-b border-line px-5 py-4">
        <p className="eyebrow">Menu matrix, last {matrix.days} days</p>
        <h2 id="matrix" className="text-xl font-semibold">
          What to push, reprice or rethink
        </h2>
        <p className="text-sm text-fg-muted">
          Each dish by plates sold and what a plate keeps after food cost.
          {unplaced > 0 && ` ${unplaced} without a known cost ${unplaced === 1 ? "is" : "are"} left out.`}
        </p>
      </div>

      <div className="grid lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="border-b border-line p-5 lg:border-r lg:border-b-0">
          <div aria-hidden className="grid grid-cols-[auto_minmax(0,1fr)] gap-2">
            <p className="text-xs text-fg-muted [writing-mode:vertical-rl] rotate-180 text-center">
              Keeps per plate
            </p>
            <div className="relative aspect-[4/3] rounded-md border border-line bg-bg">
              {ORDER.map((kind, i) => (
                <p
                  key={kind}
                  className={`absolute text-xs font-medium text-fg-muted ${i < 2 ? "top-2" : "bottom-2"} ${i % 2 ? "right-3" : "left-3"}`}
                >
                  {KINDS[kind].title}
                </p>
              ))}
              <div className="absolute inset-y-0 border-l border-dashed border-line-strong" style={{ left: `${barX}%` }} />
              <div className="absolute inset-x-0 border-t border-dashed border-line-strong" style={{ bottom: `${barY}%` }} />
              {placed.map((d) => {
                const right = x(d.units_sold) > 70; // label on the side that has room
                return (
                  <div
                    key={d.menu_item_id}
                    className="absolute flex -translate-y-1/2 items-center gap-1.5"
                    style={{
                      bottom: `calc(${y(d.margin_cents!)}% - 0.75rem)`,
                      ...(right ? { right: `calc(${100 - x(d.units_sold)}% - 0.3125rem)` } : { left: `calc(${x(d.units_sold)}% - 0.3125rem)` }),
                      flexDirection: right ? "row-reverse" : "row",
                    }}
                  >
                    <span
                      className={`size-2.5 shrink-0 rounded-full ring-2 ring-bg ${d.kind === "star" ? "bg-chart-profit" : d.kind === "dog" ? "bg-chart-labor" : "bg-chart-food"}`}
                    />
                    <span className="text-xs font-medium whitespace-nowrap">{d.name}</span>
                  </div>
                );
              })}
            </div>
            <span />
            <p className="text-center text-xs text-fg-muted">Plates sold</p>
          </div>
        </div>

        <dl className="grid content-start gap-5 p-5">
          {(["star", "plowhorse", "puzzle", "dog"] as Kind[]).map((kind) => {
            const dishes = placed.filter((d) => d.kind === kind);
            return (
              <div key={kind}>
                <dt className="flex items-baseline gap-2">
                  <span className="font-semibold">{KINDS[kind].title}</span>
                  <span className="text-sm text-fg-muted">{KINDS[kind].rule}</span>
                </dt>
                {dishes.length === 0 ? (
                  <dd className="text-sm text-fg-muted">None right now.</dd>
                ) : (
                  <>
                    <dd className="text-sm">
                      {dishes.map((d, i) => (
                        <span key={d.menu_item_id}>
                          {i > 0 && ", "}
                          {d.name}{" "}
                          <span className="text-fg-muted">
                            ({Number(d.units_sold).toFixed(0)} sold, {money(d.margin_cents!)} a plate)
                          </span>
                        </span>
                      ))}
                    </dd>
                    <dd className="text-sm text-fg-muted">{KINDS[kind].advice}</dd>
                  </>
                )}
              </div>
            );
          })}
          <p className="border-t border-line pt-4 text-sm text-fg-muted">
            The lines: {Number(matrix.popularity_bar).toFixed(0)} plates (70% of an even share) and{" "}
            {money(matrix.margin_bar_cents)} a plate (the menu&apos;s average).
          </p>
        </dl>
      </div>
    </section>
  );
}
