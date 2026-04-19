const { test, expect } = require("@playwright/test");
const { createTestUser, loginViaUI, getDeckCounts } = require("./helpers/seed");

test.beforeEach(async ({ context }) => {
  await context.clearCookies();
});

/**
 * Draws one card via UI and closes the reveal modal.
 * Caller must already be on the team tab.
 */
async function drawOneCard(page) {
  await page.click("#drawBtn");
  await expect(page.locator("#revealModal")).toBeVisible({ timeout: 10_000 });
  await page.click("#revealModal button:has-text('Continue')");
  await expect(page.locator("#revealModal")).toBeHidden();
}

// ---------------------------------------------------------------------------
// Roster active/bench toggle
// ---------------------------------------------------------------------------

test("drawn card appears in active roster or bench", async ({ page, request }) => {
  const deck = await getDeckCounts(request);
  const totalCards = Object.values(deck).reduce((a, b) => a + b, 0);
  test.skip(totalCards === 0, "No cards in deck — run seed_db.py to populate test cards");

  const user = await createTestUser(request);
  await page.goto("/");
  await loginViaUI(page, user);
  await page.click("#tab-btn-team");

  await drawOneCard(page);

  // After draw the card must appear in either the active grid or bench grid
  const activeCards = page.locator("#rosterActiveGrid [data-card-id], #rosterActiveGrid .card-row");
  const benchCards  = page.locator("#benchGrid [data-card-id], #benchGrid .card-row");

  // Wait for roster to reload
  await page.waitForTimeout(800);

  const activeCount = await activeCards.count();
  const benchCount  = await benchCards.count();
  expect(activeCount + benchCount).toBeGreaterThan(0);
});

test("bench card can be activated into the roster", async ({ page, request }) => {
  const deck = await getDeckCounts(request);
  const totalCards = Object.values(deck).reduce((a, b) => a + b, 0);
  test.skip(totalCards === 0, "No cards in deck — run seed_db.py to populate test cards");

  const user = await createTestUser(request);
  await page.goto("/");
  await loginViaUI(page, user);
  await page.click("#tab-btn-team");

  // Draw enough cards to fill the active roster (5 slots) and leave one on bench
  for (let i = 0; i < 6; i++) {
    const bal = parseInt(await page.locator("#tokenBalance").textContent(), 10);
    if (bal === 0) break;
    const d = await getDeckCounts(request);
    if (Object.values(d).reduce((a, b) => a + b, 0) === 0) break;
    await drawOneCard(page);
    await page.waitForTimeout(300);
  }

  // Bench section should be visible with at least one card
  const benchSection = page.locator("#benchSection");
  await expect(benchSection).toBeVisible();

  const activateBtn = benchSection.locator("button:has-text('Activate')").first();
  const hasBenchCard = (await activateBtn.count()) > 0;
  test.skip(!hasBenchCard, "No benched card available to activate");

  // Record active count before
  const beforeCount = await page.locator("#rosterActiveGrid button:has-text('Bench')").count();

  await activateBtn.click();
  await page.waitForTimeout(600);

  // Active roster should now have one more Bench button
  const afterCount = await page.locator("#rosterActiveGrid button:has-text('Bench')").count();
  expect(afterCount).toBeGreaterThan(beforeCount);
});

test("active card can be moved to bench", async ({ page, request }) => {
  const deck = await getDeckCounts(request);
  const totalCards = Object.values(deck).reduce((a, b) => a + b, 0);
  test.skip(totalCards === 0, "No cards in deck — run seed_db.py to populate test cards");

  const user = await createTestUser(request);
  await page.goto("/");
  await loginViaUI(page, user);
  await page.click("#tab-btn-team");

  await drawOneCard(page);
  await page.waitForTimeout(500);

  const benchBtn = page.locator("#rosterActiveGrid button:has-text('Bench')").first();
  const hasActive = (await benchBtn.count()) > 0;
  test.skip(!hasActive, "No active card available to bench");

  await benchBtn.click();
  await page.waitForTimeout(600);

  // Bench section should now be visible
  await expect(page.locator("#benchSection")).toBeVisible();
  await expect(page.locator("#benchGrid button:has-text('Activate')").first()).toBeVisible();
});

// ---------------------------------------------------------------------------
// Locked week banner
// ---------------------------------------------------------------------------

test("locked week shows the lock banner", async ({ page, request }) => {
  const user = await createTestUser(request);
  await page.goto("/");
  await loginViaUI(page, user);
  await page.click("#tab-btn-team");

  // Find the week selector and see if any locked week exists
  const weekSelect = page.locator("#rosterWeekSelect");
  await weekSelect.waitFor({ state: "attached" });

  const options = await weekSelect.locator("option").all();
  let foundLocked = false;
  for (const opt of options) {
    const text = await opt.textContent();
    if (text && text.toLowerCase().includes("locked")) {
      await weekSelect.selectOption({ label: text.trim() });
      await page.waitForTimeout(500);
      foundLocked = true;
      break;
    }
  }

  test.skip(!foundLocked, "No locked week exists yet in this environment");

  const banner = page.locator("#rosterLockedBanner");
  await expect(banner).toBeVisible();
  // Activate/Bench buttons must not appear in the active grid for locked weeks
  await expect(
    page.locator("#rosterActiveGrid button:has-text('Bench')"),
  ).toHaveCount(0);
});
