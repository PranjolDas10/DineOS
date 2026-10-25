import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function signIn(page: Page) {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/); // signed out: redirected
  await page.getByRole("button", { name: "Sign in" }).click(); // demo login is prefilled
  await expect(page.getByRole("heading", { level: 1 })).toContainText("in food sales");
}

async function expectAccessible(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa"]).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" ")}`)).toEqual([]);
}

test("pages pass axe in light and dark", async ({ page }) => {
  await signIn(page);
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const path of ["/", "/menu", "/receipts"]) {
      await page.goto(path);
      await expectAccessible(page);
    }
  }
});

test("reviewing a receipt saves its prices", async ({ page }) => {
  await signIn(page);
  await page.goto("/receipts");
  await page.getByRole("link", { name: /Ready to review/ }).first().click();
  await expect(page.getByRole("heading", { name: "Check this receipt" })).toBeVisible();
  await expectAccessible(page);

  const save = page.getByRole("button", { name: /^(Decide|Save receipt)/ });
  await expect(save).toBeDisabled(); // nothing is accepted by default

  const accept = page.getByRole("button", { name: /^Accept \d+$/ });
  if (await accept.isVisible()) await accept.click();
  // Every line still undecided gets an explicit decision in the dialog.
  const undecided = page.locator("section").getByRole("button").filter({ hasText: /Check this|What is it/ });
  while ((await undecided.count()) > 0) {
    await undecided.first().click();
    const dialog = page.getByRole("dialog", { name: "Check this line" });
    await expectAccessible(page);
    await dialog.getByLabel("What is it?").selectOption("none");
    await dialog.getByRole("button", { name: "Save line" }).click();
    await expect(dialog).toBeHidden();
  }

  await expect(save).toBeEnabled();
  await save.click();
  await expect(page.getByRole("status")).toContainText("Saved.");
});
