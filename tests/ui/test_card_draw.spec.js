const { test, expect } = require("@playwright/test");
const { createTestUser, loginViaUI, getDeckCounts } = require("./helpers/seed");

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
});

// ---------------------------------------------------------------------------
// Token display
// ---------------------------------------------------------------------------

test("token balance is visible after login", async ({ page, request }) => {
  const user = await createTestUser(request);
  await page.goto("/");
  await loginViaUI(page, user);

  const balance = page.locator("#tokenBalance");
  await expect(balance).toBeVisible();
  // Balance text should contain a number (initial tokens)
  await expect(balance).toHaveText(/\d+/);
});

// ---------------------------------------------------------------------------
// Draw with empty deck shows an error
// ---------------------------------------------------------------------------

test("draw button is visible on team tab after login", async ({ page, request }) => {
  const user = await createTestUser(request);
  await page.goto("/");
  await loginViaUI(page, user);

  await page.click("#tab-btn-team");
  await expect(page.locator("#drawBtn")).toBeVisible();
});

// ---------------------------------------------------------------------------
// Deck has cards (seed_db.py provides these in CI) — skip if empty
// ---------------------------------------------------------------------------

test("draw opens reveal modal and decrements token balance", async ({ page, request }) => {
  const deck = await getDeckCounts(request);
  const totalCards = Object.values(deck).reduce((a, b) => a + b, 0);
  test.skip(totalCards === 0, "Deck is empty — run seed_db.py to populate test cards");

  const user = await createTestUser(request);
  await page.goto("/");
  await loginViaUI(page, user);

  await page.click("#tab-btn-team");

  // Record token balance before draw
  const balanceBefore = parseInt(
    await page.locator("#tokenBalance").textContent(),
    10,
  );

  // Draw
  await page.click("#drawBtn");

  // Reveal modal must appear
  await expect(page.locator("#revealModal")).toBeVisible({ timeout: 10_000 });

  // Rarity label is always set regardless of draw animation
  await expect(page.locator("#revealRarity")).not.toBeEmpty();

  // Close reveal
  await page.click("#revealModal button:has-text('Continue')");
  await expect(page.locator("#revealModal")).toBeHidden();

  // Token balance must have decremented by 1
  const balanceAfter = parseInt(
    await page.locator("#tokenBalance").textContent(),
    10,
  );
  expect(balanceAfter).toBe(balanceBefore - 1);
});

test("draw with no tokens shows error", async ({ page, request }) => {
  const deck = await getDeckCounts(request);
  const totalCards = Object.values(deck).reduce((a, b) => a + b, 0);
  test.skip(totalCards === 0, "Deck is empty — draw error path not reachable");

  // Create user and drain all tokens via API
  const user = await createTestUser(request);

  // Draw all tokens away so balance is 0
  // Use the API session of the request fixture (different session from page)
  // So instead: create user with 0 tokens by direct check after login
  // This is complex; simplest: just verify the error appears when balance is 0
  // We know the deckStatus shows an error when draw fails.

  // Register a fresh user via UI so the page session has their cookies
  await page.goto("/");
  const ts = Date.now();
  const username = `nodraw_${ts}`;
  await page.waitForSelector("#loginModal:not(.hidden)", { timeout: 5_000 });
  await page.click("button:has-text('Create new account')");
  await page.fill("#regUsername", username);
  await page.fill("#regEmail", `${username}@test.local`);
  await page.fill("#regPassword", "validpassword");
  await page.click("button:has-text('Create account')");
  await expect(page.locator("#tab-team")).toBeVisible();

  // Drain tokens by drawing until balance hits 0
  const revealModal = page.locator("#revealModal");
  let attempts = 0;
  while (attempts < 10) {
    const bal = parseInt(await page.locator("#tokenBalance").textContent(), 10);
    if (bal === 0) break;
    await page.click("#drawBtn");
    // Wait for the reveal modal to either appear (success) or skip (error/empty deck)
    const appeared = await revealModal.waitFor({ state: "visible", timeout: 5_000 })
      .then(() => true).catch(() => false);
    if (appeared) {
      await page.click("#revealModal button:has-text('Continue')");
      await revealModal.waitFor({ state: "hidden", timeout: 5_000 }).catch(() => {});
    }
    attempts++;
  }

  // Now try to draw with 0 tokens
  await page.click("#drawBtn");
  await expect(page.locator("#deckStatus")).toHaveClass(/err/);
  await expect(page.locator("#revealModal")).toBeHidden();
});
