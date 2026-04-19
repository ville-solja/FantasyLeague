# Plan: Automated Testing

## Context

Agent-based test execution (`/qa-engineer`) consumes tokens and requires manual invocation — it cannot run continuously or gate pull requests. This plan adds two automated test layers that run outside the agent system: a Playwright browser suite for UI regression covering critical user flows, and a GitHub Actions workflow that runs the existing pytest suite on every push and pull request. Together they enforce a continuous quality gate that catches regressions before they reach production with zero token cost per run. The pytest suite already exists in `backend/tests/`; this plan only adds automation wiring and the new Playwright layer.

## User Stories

### 14.1 Automated UI Regression Suite
**User story**
As a developer, I want automated browser tests for critical user flows so that UI regressions are caught without manual testing or agent invocation.

**Acceptance criteria**
- Playwright test suite covers: registration (field validation, duplicate errors), login/logout, card draw modal, roster activate/deactivate, and admin tab access guard
- Tests run against a locally started instance of the app (docker-compose or direct uvicorn)
- Each test is independent — it seeds its own data and does not rely on leftover state from prior tests
- Suite produces a pass/fail exit code usable by CI

---

### 14.2 Continuous Unit Test Automation
**User story**
As a developer, I want the backend pytest suite to run automatically on every push so that failures are caught before they reach production without relying on agent invocation.

**Acceptance criteria**
- GitHub Actions workflow runs `pytest backend/tests/` on every push and pull request to `main`
- Workflow installs dependencies from `backend/requirements.txt` before running
- Failing tests block the PR check
- Test results are visible in the GitHub Actions tab without requiring local setup

---

### 14.3 UI Tests in CI
**User story**
As a developer, I want the Playwright UI suite to run in CI so that browser-level regressions are caught on every pull request.

**Acceptance criteria**
- GitHub Actions workflow starts the app and runs the Playwright suite against it
- App is seeded with test data before the suite runs
- Workflow reports pass/fail per test file
- CI does not require any secrets beyond those already available in the repo

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `.github/workflows/unit-tests.yml` | New — pytest on push/PR |
| `.github/workflows/ui-tests.yml` | New — Playwright suite on push/PR |
| `tests/ui/package.json` | New — Playwright dependency |
| `tests/ui/playwright.config.js` | New — base URL, browser, timeout config |
| `tests/ui/helpers/seed.js` | New — test data setup/teardown helpers |
| `tests/ui/test_auth.spec.js` | New — registration, login, logout, tab access |
| `tests/ui/test_card_draw.spec.js` | New — draw modal, token deduction, reveal |
| `tests/ui/test_roster.spec.js` | New — activate, deactivate, locked-week guard |
| `tests/ui/test_admin_guard.spec.js` | New — admin tab blocked for non-admin users |

---

### Step 1 — GitHub Actions: unit tests

Create `.github/workflows/unit-tests.yml`:

```yaml
name: Unit Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r backend/requirements.txt
      - run: cd backend && python -m pytest tests/ -v --tb=short
```

This runs without Docker — SQLite is file-based and tests already use an in-memory fixture database.

---

### Step 2 — Playwright setup

```
tests/ui/
├── package.json
├── playwright.config.js
├── helpers/
│   └── seed.js
└── *.spec.js
```

`package.json`:
```json
{
  "name": "ui-tests",
  "private": true,
  "scripts": {
    "test": "playwright test"
  },
  "devDependencies": {
    "@playwright/test": "^1.44.0"
  }
}
```

`playwright.config.js`:
```js
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  timeout: 30_000,
  use: {
    baseURL: process.env.TEST_BASE_URL ?? "http://localhost:8000",
    headless: true,
  },
});
```

The `TEST_BASE_URL` env var lets CI override the target — defaults to the standard local dev port.

---

### Step 3 — Test helper: seed

`helpers/seed.js` wraps the API to set up a fresh test user before each test and clean up after:

```js
export async function createTestUser(request, suffix = "") {
  const username = `testuser_${Date.now()}${suffix}`;
  const res = await request.post("/register", {
    data: { username, email: `${username}@test.local`, password: "testpass1" },
  });
  return { username, password: "testpass1", data: await res.json() };
}
```

Tests use Playwright's `request` fixture to call the API directly for setup, then drive the browser for assertion.

---

### Step 4 — UI tests: auth flows

`test_auth.spec.js` covers:
- Successful registration shows the team tab
- Registration with a short password highlights the password field with an error (does not submit)
- Registration with a duplicate username shows the username field error
- Login with wrong password shows an error in the login modal
- Logout returns the user to the logged-out state (no token balance visible)
- Navigating to the admin tab as a non-admin user does not load admin content

---

### Step 5 — UI tests: card draw and roster

`test_card_draw.spec.js`:
- Drawing a card when the user has ≥1 token opens the reveal modal
- Token balance decrements by 1 after a successful draw
- Drawing when the user has 0 tokens shows an error

`test_roster.spec.js`:
- Activating a benched card moves it to the active roster row
- Deactivating an active card moves it to the bench row
- A locked week shows a lock banner and the activate/deactivate buttons are absent

---

### Step 6 — GitHub Actions: UI tests

Create `.github/workflows/ui-tests.yml`:

```yaml
name: UI Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  playwright:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Start app
        run: |
          cp .env.example .env
          echo "SECRET_KEY=ci-secret-key-for-testing" >> .env
          echo "DEBUG=true" >> .env
          docker compose up -d
          sleep 10  # wait for startup

      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install Playwright
        run: cd tests/ui && npm ci && npx playwright install --with-deps chromium

      - name: Run UI tests
        run: cd tests/ui && npm test
        env:
          TEST_BASE_URL: http://localhost:8000

      - name: Stop app
        if: always()
        run: docker compose down
```

---

## Verification

- Run `pytest backend/tests/ -v` locally — all existing tests pass before adding CI
- Run `cd tests/ui && npm test` locally against a running dev instance — all new specs pass
- Push a branch and confirm both GitHub Actions workflows appear in the PR checks
- Introduce a deliberate bug in `register()` frontend validation and confirm the `test_auth.spec.js` run fails in CI
- Confirm CI does not require any manually added secrets (uses `.env.example` defaults + overrides)
