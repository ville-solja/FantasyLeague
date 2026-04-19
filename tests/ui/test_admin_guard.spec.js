const { test, expect } = require("@playwright/test");
const { createTestUser, loginViaUI } = require("./helpers/seed");

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
});

test("admin tab does not load content for a regular user", async ({ page, request }) => {
  const user = await createTestUser(request);

  await page.goto("/");
  await loginViaUI(page, user);

  // Click the admin tab
  await page.click("#tab-btn-admin");

  // The tab content div should remain empty/hidden — the app guards against
  // non-admin users loading weights, users, and codes.
  // Specifically, the admin tab content (#tab-admin) must not contain the
  // weights table or the users table that a real admin session would load.
  const adminTab = page.locator("#tab-admin");
  await expect(adminTab).toBeAttached();

  // Give the page a moment in case any async load fires anyway
  await page.waitForTimeout(500);

  // Weights table and user list should not be present inside the admin tab
  await expect(adminTab.locator("table")).toHaveCount(0);
});

test("admin tab is visible in the nav for all users", async ({ page, request }) => {
  // The tab button itself is always rendered — the guard is in the content loading,
  // not in hiding the tab button.
  const user = await createTestUser(request);
  await page.goto("/");
  await loginViaUI(page, user);

  await expect(page.locator("#tab-btn-admin")).toBeVisible();
});

test("unauthenticated user cannot access team tab content", async ({ page }) => {
  await page.goto("/");

  // App auto-opens login modal; dismiss it so we can interact with the nav
  await page.waitForSelector("#loginModal:not(.hidden)", { timeout: 5_000 });
  await page.evaluate(() => document.getElementById("loginModal").classList.add("hidden"));

  // Without login, clicking team tab returns early (guard: !activeUserId)
  await page.click("#tab-btn-team");
  await page.waitForTimeout(300);

  // The team tab content should remain inactive / not loaded
  // Draw button requires auth — it must not be visible if the tab didn't activate
  const teamTab = page.locator("#tab-team");
  await expect(teamTab).not.toHaveClass(/active/);
});
