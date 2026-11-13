import { expect, test as setup } from "@playwright/test";

setup("sign in", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/); // signed out: redirected
  await page.getByRole("button", { name: "Sign in" }).click(); // demo login is prefilled
  await expect(page.getByRole("heading", { level: 1, name: "Profit" })).toBeVisible();
  await page.context().storageState({ path: "test-results/.auth.json" });
});
