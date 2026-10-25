import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function expectAccessible(page: Page) {
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag22aa"]).analyze();
  expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target).join(" ")}`)).toEqual([]);
}

test("pages pass axe in light and dark", async ({ page }) => {
  for (const scheme of ["light", "dark"] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    for (const path of ["/", "/menu", "/receipts", "/schedule"]) {
      await page.goto(path);
      await expectAccessible(page);
    }
  }
});

test("reviewing a receipt saves its prices", async ({ page }) => {
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

test("the schedule refuses an overlap, explains it, then adds and deletes a shift", async ({ page }) => {
  await page.goto("/schedule");
  await page.getByRole("button", { name: /^Add a shift for Ravi/ }).first().click();
  const dialog = page.getByRole("dialog", { name: "Add shift" });
  await expectAccessible(page);

  // Ravi works 10:30-21:30 every day in the demo: the database refuses, the dialog says why.
  await dialog.getByLabel("Starts").fill("12:00");
  await dialog.getByLabel("Ends").fill("14:00");
  await dialog.getByRole("button", { name: "Save shift" }).click();
  await expect(dialog.getByRole("alert")).toContainText("already works 10:30 to 21:30");

  await dialog.getByLabel("Starts").fill("22:00");
  await dialog.getByLabel("Ends").fill("23:30");
  await dialog.getByRole("button", { name: "Save shift" }).click();
  await expect(dialog).toBeHidden();
  const added = page.getByRole("button", { name: /22:00–23:30/ });
  await expect(added).toBeVisible();

  await added.click();
  const change = page.getByRole("dialog", { name: "Change shift" });
  await change.getByRole("button", { name: "Delete shift" }).click();
  await change.getByRole("button", { name: "Yes, delete it" }).click();
  await expect(added).toBeHidden();
});
