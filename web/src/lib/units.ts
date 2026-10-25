// Receipt units -> an ingredient's base unit (g, ml or each). Exact factors (1 lb = 453.59237 g).
const FACTORS: Record<string, [base: string, factor: number]> = {
  g: ["g", 1],
  kg: ["g", 1000],
  lb: ["g", 453.59237],
  lbs: ["g", 453.59237],
  oz: ["g", 28.349523125],
  ml: ["ml", 1],
  l: ["ml", 1000],
  qt: ["ml", 946.352946],
  gal: ["ml", 3785.411784],
  "fl oz": ["ml", 29.5735295625],
  each: ["each", 1],
  ea: ["each", 1],
  pc: ["each", 1],
  pcs: ["each", 1],
};

/** The amount in the base unit, or null when the receipt's unit can't be converted on its own
 * (a "case" or "bag" holds whatever the supplier packs, so only the owner knows). */
export function toBase(quantity: number, unit: string, baseUnit: string): number | null {
  const known = FACTORS[unit.trim().toLowerCase()];
  if (!known || known[0] !== baseUnit || !(quantity > 0)) return null;
  return Math.round(quantity * known[1] * 10) / 10;
}

/** An ingredient whose whole name appears in the receipt line ("Heavy cream 36%" -> Cream).
 * shortcut: name match only; learn supplier item -> ingredient from confirmed receipts later. */
export function suggestIngredient<T extends { name: string }>(description: string, ingredients: T[]) {
  const text = ` ${description.toLowerCase().replace(/[^a-z0-9]+/g, " ")} `;
  return ingredients
    .filter((i) => text.includes(` ${i.name.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim()} `))
    .sort((a, b) => b.name.length - a.name.length)[0];
}
