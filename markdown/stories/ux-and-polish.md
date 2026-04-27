# UX and Polish

## Schedule and Transparency

### Scoring Explanation
**Acceptance criteria**
- Stats and their point mapping are shown to the user in the My Team tab
- Collapsible "How is scoring calculated?" section lists all weighted stats

---

### Schedule Tab
**User story**
As a user, I want to see the full season fixture list including past results and upcoming matches.

**Acceptance criteria**
- All series shown in a single chronological list spanning all divisions
- Upcoming series show planned date, team names, and stream link where available
- Past series show actual match start time, series result (e.g. 2–0)
- Team names link to the team detail modal
- Stale cache notice shown if schedule data is outdated

---

## Layout

### Roster-first My Team Layout
**User story**
As a user, I want the My Team tab to show my roster as the primary content area so that I can see my active lineup and bench immediately without scrolling past deck controls.

**Acceptance criteria**
- My Roster (active cards + bench) occupies the majority of the tab's horizontal space
- Deck panel appears to the right of the roster as a sidebar, not above it
- On narrow screens (< 768 px) the sidebar stacks below the roster so the mobile experience is unaffected

---

### Deck Sidebar
**User story**
As a user, I want deck counts, the draw button, token balance, and the promo code field in a compact sidebar so these controls remain accessible without dominating the view.

**Acceptance criteria**
- Sidebar contains (top to bottom): deck rarity counts, draw button + token balance, promo code field, scoring info toggle
- Sidebar width is fixed at approximately 300 px on desktop

---

## Automated Testing

### Backend Unit Tests in CI
**User story**
As a developer, I want the backend pytest suite to run automatically on every push so that failures are caught before they reach production.

**Acceptance criteria**
- GitHub Actions workflow runs `pytest backend/tests/` on every push and pull request to `main`
- Workflow installs dependencies from `backend/requirements.txt` before running
- Failing tests block the PR check

---

### UI Regression Suite *(not yet implemented)*
**User story**
As a developer, I want automated browser tests for critical user flows so that UI regressions are caught without manual testing.

**Acceptance criteria**
- Playwright test suite covers: registration (field validation, duplicate errors), login/logout, card draw modal, roster activate/deactivate, and admin tab access guard
- Tests run against a locally started instance of the app
- Each test is independent — it seeds its own data and does not rely on leftover state from prior tests
- Suite produces a pass/fail exit code usable by CI and runs automatically on pull requests to `main`
