const { test, expect } = require("@playwright/test");
const { createTestUser, loginViaUI } = require("./helpers/seed");

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
});

// ---------------------------------------------------------------------------
// Registration field validation (client-side, no network needed)
// ---------------------------------------------------------------------------

test("short password shows inline field error without submitting", async ({ page }) => {
  await page.goto("/");
  await page.click("#headerLoginBtn");
  await page.waitForSelector("#loginModal:not(.hidden)", { timeout: 5_000 });
  await page.click("button:has-text('Create new account')");

  await page.fill("#regUsername", "someuser");
  await page.fill("#regEmail", "someuser@test.local");
  await page.fill("#regPassword", "abc"); // under 6 chars
  await page.click("button:has-text('Create account')");

  await expect(page.locator("#regPasswordErr")).toHaveText(/at least 6/i);
  // Modal must still be open
  await expect(page.locator("#registerModal")).toBeVisible();
});

test("empty username shows inline field error", async ({ page }) => {
  await page.goto("/");
  await page.click("#headerLoginBtn");
  await page.waitForSelector("#loginModal:not(.hidden)", { timeout: 5_000 });
  await page.click("button:has-text('Create new account')");

  await page.fill("#regEmail", "x@test.local");
  await page.fill("#regPassword", "validpassword");
  await page.click("button:has-text('Create account')");

  await expect(page.locator("#regUsernameErr")).toHaveText(/required/i);
  await expect(page.locator("#registerModal")).toBeVisible();
});

test("invalid email format shows inline field error", async ({ page }) => {
  await page.goto("/");
  await page.click("#headerLoginBtn");
  await page.waitForSelector("#loginModal:not(.hidden)", { timeout: 5_000 });
  await page.click("button:has-text('Create new account')");

  await page.fill("#regUsername", "someuser");
  await page.fill("#regEmail", "notanemail");
  await page.fill("#regPassword", "validpassword");
  await page.click("button:has-text('Create account')");

  await expect(page.locator("#regEmailErr")).toHaveText(/valid email/i);
  await expect(page.locator("#registerModal")).toBeVisible();
});

// ---------------------------------------------------------------------------
// Registration success
// ---------------------------------------------------------------------------

test("successful registration navigates to team tab", async ({ page, request }) => {
  await page.goto("/");
  const ts = Date.now();
  const username = `newuser_${ts}`;

  await page.waitForSelector("#loginModal:not(.hidden)", { timeout: 5_000 });
  await page.click("button:has-text('Create new account')");
  await page.fill("#regUsername", username);
  await page.fill("#regEmail", `${username}@test.local`);
  await page.fill("#regPassword", "validpassword");
  await page.click("button:has-text('Create account')");

  // Modal closes and team tab content is visible
  await expect(page.locator("#registerModal")).toBeHidden();
  await expect(page.locator("#tab-team")).toBeVisible();
  await expect(page.locator("#tokenBalance")).toBeVisible();
});

// ---------------------------------------------------------------------------
// Duplicate username shows server-side error on the correct field
// ---------------------------------------------------------------------------

test("duplicate username shows username field error", async ({ page, request }) => {
  const user = await createTestUser(request);

  await page.goto("/");
  await page.click("#headerLoginBtn");
  await page.waitForSelector("#loginModal:not(.hidden)", { timeout: 5_000 });
  await page.click("button:has-text('Create new account')");

  await page.fill("#regUsername", user.username); // already taken
  await page.fill("#regEmail", `duplicate_${Date.now()}@test.local`);
  await page.fill("#regPassword", "validpassword");
  await page.click("button:has-text('Create account')");

  await expect(page.locator("#regUsernameErr")).not.toBeEmpty();
  await expect(page.locator("#registerModal")).toBeVisible();
});

// ---------------------------------------------------------------------------
// Register modal X button closes the modal
// ---------------------------------------------------------------------------

test("register modal X button closes the modal", async ({ page }) => {
  await page.goto("/");
  await page.click("#headerLoginBtn");
  await page.waitForSelector("#loginModal:not(.hidden)", { timeout: 5_000 });
  await page.click("button:has-text('Create new account')");
  await expect(page.locator("#registerModal")).toBeVisible();

  await page.click("#registerModal button.ghost:has-text('✕'), #registerModal button[onclick*='closeRegisterModal']");
  await expect(page.locator("#registerModal")).toBeHidden();
});

// ---------------------------------------------------------------------------
// Login
// ---------------------------------------------------------------------------

test("login with wrong password shows error in login modal", async ({ page, request }) => {
  const user = await createTestUser(request);

  await page.goto("/");
  await page.click("#headerLoginBtn");
  await page.waitForSelector("#loginModal:not(.hidden)", { timeout: 5_000 });
  await page.fill("#loginUsername", user.username);
  await page.fill("#loginPassword", "wrongpassword");
  await page.click("button:has-text('Login')");

  await expect(page.locator("#loginStatus")).toHaveClass(/err/);
  await expect(page.locator("#loginModal")).toBeVisible();
});

// ---------------------------------------------------------------------------
// Logout
// ---------------------------------------------------------------------------

test("logout returns to logged-out state", async ({ page, request }) => {
  const user = await createTestUser(request);

  await page.goto("/");
  await loginViaUI(page, user);

  // Logged in: logout button visible
  await expect(page.locator("#headerLogoutBtn")).toBeVisible();

  await page.click("#headerLogoutBtn");

  // Logged out: login button visible, token balance hidden
  await expect(page.locator("#headerLoginBtn")).toBeVisible();
  await expect(page.locator("#tokenBalance")).toBeHidden();
});
