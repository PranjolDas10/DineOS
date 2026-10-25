import { expect, test } from "@playwright/test";

import { parseDollars } from "../src/lib/format";
import { suggestIngredient, toBase } from "../src/lib/units";

// Pure functions behind the receipt review: no browser needed.
test("converts receipt units to an ingredient's base unit", () => {
  expect(toBase(40, "lb", "g")).toBe(18143.7);
  expect(toBase(4, "L", "ml")).toBe(4000);
  expect(toBase(2, " kg ", "g")).toBe(2000);
  expect(toBase(12, "ea", "each")).toBe(12);
  expect(toBase(2, "each", "g")).toBeNull(); // a pack of unknown size
  expect(toBase(1, "case", "g")).toBeNull();
  expect(toBase(3, "kg", "ml")).toBeNull(); // weight is not volume
  expect(toBase(0, "kg", "g")).toBeNull();
});

test("suggests the ingredient named in a receipt line", () => {
  const ingredients = [{ name: "Cream" }, { name: "Chicken thigh" }, { name: "Onion" }];
  expect(suggestIngredient("Heavy cream 36%", ingredients)?.name).toBe("Cream");
  expect(suggestIngredient("CHICKEN THIGH BNLS", ingredients)?.name).toBe("Chicken thigh");
  expect(suggestIngredient("Onions red", ingredients)).toBeUndefined(); // whole words only
  expect(suggestIngredient("Trash bags", ingredients)).toBeUndefined();
});

test("parses dollar amounts to cents", () => {
  expect(parseDollars("61.50")).toBe(6150);
  expect(parseDollars("$1,299.99")).toBe(129999);
  expect(parseDollars("0.1")).toBe(10);
  expect(parseDollars("1.005")).toBeNull();
  expect(parseDollars("-3")).toBeNull();
  expect(parseDollars("")).toBeNull();
});
