# 14. Automated Testing

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
