# Automated Testing

The project uses two automated test layers that run independently of the agent system: a pytest suite for backend unit tests and a Playwright suite for browser-level UI regression. Both run in GitHub Actions CI on every push and pull request.

---

## Unit Tests (pytest)

The existing pytest suite lives in `backend/tests/`. It covers scoring formulas, week generation and locking logic, and auth utilities using an in-memory SQLite database — no running server or Docker is required.

### Running locally

```bash
cd backend && python -m pytest tests/ -v --tb=short
```

### CI

`.github/workflows/unit-tests.yml` runs the suite on every push to `main` and on every pull request. A failing test blocks the PR check.

---

## UI Tests (Playwright)

A Playwright browser test suite in `tests/ui/` drives a running instance of the app through a headless Chromium browser. Tests cover critical user flows and are each independent — they seed their own test data via the API and do not share state.

### Covered flows *(planned)*

| Test file | What it covers |
|---|---|
| `test_auth.spec.js` | Registration field validation, duplicate errors, login/logout, admin tab access guard |
| `test_card_draw.spec.js` | Draw modal, token deduction, reveal |
| `test_roster.spec.js` | Activate/deactivate, locked-week guard |
| `test_admin_guard.spec.js` | Admin tab blocked for non-admin users |

### Running locally

```bash
# Start the app first (dev mode)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Then run the UI suite
cd tests/ui
npm ci
npx playwright install chromium
npm test
```

Override the target URL with `TEST_BASE_URL=http://your-host:port npm test`.

### CI

`.github/workflows/ui-tests.yml` starts the app via `docker compose`, waits for it to be ready, then runs the Playwright suite against `http://localhost:8000`. The workflow uses `.env.example` defaults and injects `SECRET_KEY` and `DEBUG=true` for the CI environment.

---

## Configuration

No new environment variables are introduced. The CI workflows use existing `.env.example` values.

| Variable | Used by | Notes |
|---|---|---|
| `TEST_BASE_URL` | Playwright config | Defaults to `http://localhost:8000`; overridden in CI |
| `SECRET_KEY` | App startup | Set to a fixed CI value in the workflow; not a repo secret |
| `DEBUG` | App startup | Set to `true` in CI to bypass `SECRET_KEY` strength check |

---

*This document is a stub created at feature planning time. Fill in implementation details once the feature is built.*
