const { test, expect } = require("@playwright/test");
const { createTestUser, loginViaUI } = require("./helpers/seed");

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
});

test("admin tab does not load content for a regular user", async ({ page, request }) => {
  const user = await createTestUser(request);

  await page.goto("/");
  await loginViaUI(page, user);

  // Admin tab button is hidden for non-admins; invoke switchTab directly
  // to verify the in-function guard blocks data loading.
  await page.evaluate(() => window.switchTab("admin"));
  await page.waitForTimeout(500);

  const adminTab = page.locator("#tab-admin");
  await expect(adminTab).toBeAttached();

  // Guard returns early — table bodies keep their placeholder content, not real data
  await expect(page.locator("#weightsBody")).toContainText("—");
  await expect(page.locator("#usersBody")).toContainText("—");
  await expect(page.locator("#codesBody")).toContainText("—");
});

test("admin tab button is hidden for regular users", async ({ page, request }) => {
  // The admin tab button is only shown to accounts where is_admin is true.
  const user = await createTestUser(request);
  await page.goto("/");
  await loginViaUI(page, user);

  await expect(page.locator("#tab-btn-admin")).toBeHidden();
});

test("unauthenticated user cannot access team tab content", async ({ page }) => {
  await page.goto("/");

  // App auto-opens login modal; dismiss it so we can test the guard
  await page.waitForSelector("#loginModal:not(.hidden)", { timeout: 5_000 });
  await page.evaluate(() => document.getElementById("loginModal").classList.add("hidden"));

  // Tab button is hidden when not logged in; call switchTab directly
  await page.evaluate(() => window.switchTab("team"));
  await page.waitForTimeout(300);

  // Guard returns early without calling loadDeck/loadRoster — deck counter stays empty
  await expect(page.locator("#drawCounter")).toBeEmpty();
  await expect(page.locator("#rosterActiveGrid")).toBeEmpty();
});
