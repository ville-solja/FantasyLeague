# 9. Admin Management

### 9.1 Generate Promo Codes
**User story**
As an admin, I want to create promo codes that grant tokens to users who redeem them.

**Acceptance criteria**
- Admin creates codes with a configurable token amount
- Codes are reusable (multiple users can redeem the same code)
- Each user can only redeem a given code once
- Admin can delete codes

---

### 9.2 Grant Tokens
**User story**
As an admin, I want to manually grant additional tokens to a specific user.

**Acceptance criteria**
- Admin can select any user and grant a specified number of tokens
- Token balance updates immediately
- Logged in the audit log with admin actor, target user, and amount

---

### 9.3 Configure Scoring Weights
**User story**
As an admin, I want to configure the scoring weights for match stats.

**Acceptance criteria**
- Each stat weight (kills, assists, deaths, GPM, wards, tower damage) is editable from environment variables
- Rarity modifier percentages (common, rare, epic, legendary) are also configurable in the environment variables
- Weight changes take effect for future calculations; use Recalculate to apply retroactively

---

### 9.4 Manage Season Lifecycle
**Acceptance criteria**
- Admin can initiate and close a season
- Season configuration (lock dates, league IDs) managed via environment variables

---

### 9.5 View System Status
**Acceptance criteria**
- Admin can see current system state (ingest status, schedule cache status)

---

### 9.6 Start New Season
**Acceptance criteria**
- Admin can reset the database and begin a new season with a fresh configuration

---

### 9.7 Admin Set Series Date
**User Story**
As admin there can be matches that take place outside of their intended week schedule. I need to have the ability to identify the series from a list and set the week when it should have happened instead. This value should not be automatically overwritten by schedule refreshes or other events that touch on the match data.

**Acceptance Criteria**
- Admin view allows selecting a series that took place on the wrong week
- Admin can select the appropriate week
- New datetime is displayed on the schedule instead of the actual match date
- This is done to keep scoring and match history aligned and avoid confusion

---

### 9.8 Recalculate Fantasy Points
**User story**
As an admin, I want to recalculate all historical fantasy points using the current scoring weights.

**Acceptance criteria**
- Recalculate button applies the current weights to all stored player-match stats
- Does not require re-fetching data from OpenDota
- Result shows the number of records updated
- Logged in the audit log

---

### 9.9 Manual League Ingestion
**User story**
As an admin, I want to trigger data ingestion for a specific league at any time.

**Acceptance criteria**
- Admin can enter a league ID and trigger ingestion from the admin tab
- Ingestion fetches new matches, calculates fantasy points, seeds player cards, and enriches player profiles
- Already-stored matches are skipped (idempotent)
- Logged in the audit log

---

### 9.10 Schedule Refresh
**User story**
As an admin, I want to force a refresh of the season schedule from the Google Sheet source.

**Acceptance criteria**
- Refresh button busts the in-memory schedule cache
- Fresh data is fetched immediately from the configured Google Sheets CSV URL
- Logged in the audit log
