# 11. Security and Integrity

### 11.1 Server-side Validation
**Acceptance criteria**
- All state-changing actions (draw, activate, admin ops) are validated server-side
- Client-side `is_admin` flag alone is not sufficient — every admin endpoint re-verifies from the session

---

### 11.2 Audit Logs
**User Story**
As admin I want to have visibility into actions that have taken place on the app.

**Acceptance Criteria**
- Tracks: user registrations, user logins, token draws, code redemptions, admin token grants, league ingestion, weight changes, recalculations, schedule refreshes, code creation and deletion
- Each entry includes timestamp, actor username, action type, and a detail string
- Visible in the Admin tab with most recent entries first
- Admin-only access
- Roster changes and other minor "regular" events are not needed to be tracked
