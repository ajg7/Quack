import { expect, test } from "@playwright/test";

test("the app loads", async ({ page }) => {
  await page.goto("/");

  await expect(page).toHaveTitle("Quack");
  await expect(page.getByRole("heading", { name: "Quack" })).toBeVisible();
});
