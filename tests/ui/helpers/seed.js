/**
 * API-level helpers for seeding test state before UI interactions.
 * Each helper uses Playwright's request fixture to call the backend directly.
 */

/** Creates a unique test user via the registration API and returns credentials. */
async function createTestUser(request, suffix = "") {
  const ts = Date.now();
  const username = `testuser_${ts}${suffix}`;
  const email = `${username}@test.local`;
  const password = "testpass1";

  const res = await request.post("/register", {
    data: { username, email, password },
  });
  if (!res.ok()) {
    const body = await res.json();
    throw new Error(`createTestUser failed: ${JSON.stringify(body)}`);
  }
  return { username, email, password };
}

/**
 * Logs in as an existing user by filling the login modal.
 * Assumes the page is at the app root and the header login button is visible.
 */
async function loginViaUI(page, { username, password }) {
  await page.click("#headerLoginBtn");
  await page.fill("#loginUsername", username);
  await page.fill("#loginPassword", password);
  await page.click("button:has-text('Login')");
  // Wait for modal to close (login button hidden means session active)
  await page.waitForSelector("#headerLoginBtn[style*='none'], #headerLoginBtn:not([style])", {
    timeout: 5_000,
  }).catch(() => {});
  // More reliable: wait for token balance to appear
  await page.waitForSelector("#tokenBalance", { state: "visible", timeout: 5_000 }).catch(() => {});
}

/** Returns the current deck counts from the API. */
async function getDeckCounts(request) {
  const res = await request.get("/deck");
  return res.json();
}

module.exports = { createTestUser, loginViaUI, getDeckCounts };
