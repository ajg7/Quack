import { execFileSync } from "node:child_process";
import { expect, test } from "@playwright/test";

test.skip(!process.env.QUACK_E2E_REAL, "set QUACK_E2E_REAL=1 with the backend running on :8000");

function killBackend(): void {
  execFileSync("powershell", [
    "-NoProfile",
    "-Command",
    "Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }",
  ]);
}

test("a real question gets progress and an answer", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");

  await page.getByLabel("Message").fill("What are today's Agoge rituals?");
  await page.getByLabel("Message").press("Enter");

  await expect(page.getByRole("list", { name: "Progress" })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/\d+ tool calls/)).toBeVisible({ timeout: 90_000 });
});

test("killing the backend mid-answer says so", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/");

  await page.getByLabel("Message").fill("What are today's Agoge rituals?");
  await page.getByLabel("Message").press("Enter");

  await expect(page.getByRole("list", { name: "Progress" })).toBeVisible({ timeout: 60_000 });
  killBackend();

  await expect(page.getByRole("alert").first()).toContainText(
    /lost before the answer finished|Couldn't reach/,
    {
      timeout: 30_000,
    },
  );
  await expect(page.getByText(/\d+ tool calls/)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Send" })).toBeVisible();
});
