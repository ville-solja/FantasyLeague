# Pre-Season Team Signup (#220)

Implemented for S17. Feature doc: `markdown/features/core/team-signup.md`. Plan: `markdown/plans/plan-issue-220-pre-season-team-signup.md`.

### An Admin Opens and Closes the Signup Period
**User story**
As an admin, I want to open a team signup period before the season and close it when signups end, so that the Team Finder tab is shown only when teams are forming.

**Acceptance criteria**
- **Open:** Admin › Settings › Season has a Team signup section. **Open signup** takes a label (required, up to 40 characters) and an optional closing time, and is refused with `409` while another period is open.
- **Visible:** while a period is open and its closing time hasn't passed, `GET /config` returns `team_signup_open: true` and the Team Finder tab shows for everyone. Admins see the tab at any time.
- **Close:** **Close now** ends the period at once. A period whose closing time has passed is closed without a background job. Once it is closed, `GET /config` returns `false`, the tab hides for non-admins, and saves are refused with `409`.
- **Audit:** opening, closing, clearing and removing a listing are recorded in the audit log with the admin's name and the period label.
- **Refused:** non-admins get `403` from every `/admin/team-signup` route.

### A Captain Lists a Partial Team
**User story**
As a team captain, I want to list my team with the players I have, the roles we still need and how to reach me, so that other partial teams and players can find us.

**Acceptance criteria**
- **Who:** a logged-in website account can create one listing per open period. Logged-out visitors see "Log in to list your team". Twitch soft accounts have no website session, so their requests are refused as logged out (`401`); the listing logic also refuses a soft account (`403`) as a defensive check.
- **Fields:** team name (2–32 characters, cleaned, no links), 1–7 Dota ids, open roles from positions 1–5 (optional), a note (up to 280 characters, no links, optional), and contact (required, up to 100 characters).
- **Ids:**
  - a 32-bit Dota id or a Steam64 id (converted) is accepted;
  - the form shows each id's name and medal from the pool or OpenDota before saving, or "Unknown player";
  - a duplicate id in the same listing, or more than 7 ids, is refused (`422`).
- **Own player:** when the captain's account has a Steam-verified player, it is added first and labelled Verified.
- **Edit and delete:** the captain can change any field or delete the listing while the period is open. Deleting removes the listing and its contact at once.
- **Full:** the captain can mark the team full and undo it. A full team moves to the Full teams section.
- **Limits:** saves are rate-limited per user, and closed periods refuse saves (`409`).

### Captains Browse the Other Teams
**User story**
As a captain or player looking for a team, I want to browse the listed teams and their players fairly, so that I can find a team that fits and contact its captain.

**Acceptance criteria**
- **List:** the Team Finder tab lists partial teams with their name, players (name, medal, Verified or Listed by captain), open roles, players needed (5 minus listed players, at least 0), the note and the last update date.
- **Order:** partial teams are shuffled in an order that stays the same for a day and changes the next (seeded by period and date), and editing a listing doesn't move it up. Full teams are in a collapsed Full teams section at the end.
- **Filters:** players needed, open role and medal range narrow the list in the browser.
- **Contact:** logged-in users see each team's contact. Logged-out visitors see "Log in to see contact details", and `GET /team-signup` leaves contacts out for them.
- **Duplicates:** a player listed on more than one team is marked "Also listed by another team".
- **Escaping:** every user-written field is escaped in the page.

### A Player Removes Themselves From a Team
**User story**
As a player, I want to remove myself from a team that listed me without asking, so that my name isn't used without my consent.

**Acceptance criteria**
- **Who:** a logged-in user whose Steam-verified player is listed on another captain's team sees **Not on this team** on that player row.
- **Effect:** the player row is deleted, and the listing shows the change. The captain isn't told who removed it, and an audit row records the removal.
- **Refused:** a user without that verified player gets `403`, and a captain removing their own player uses the edit form instead.
- **Re-adding:** the captain can list the id again, and the player can remove it again.

### The Organiser Exports the Signups
**User story**
As the tournament organiser, I want the signups as a spreadsheet, so that I can contact captains and plan the divisions without copying data by hand.

**Acceptance criteria**
- **Download:** Admin › Settings › Season › Team signup has **Download CSV** for the current or last period. It has one row per player, with the columns period, team, captain username, contact, full, open roles, note, Dota id, name, medal, verified, also on another team and updated at.
- **Safe for spreadsheets:** a cell starting with `=`, `+`, `-`, `@`, a tab or a carriage return is prefixed with `'`, so it can't run as a formula.
- **Admin list:** the section lists every listing with player counts and a **Remove** button (audited).
- **Retention:** 60 days after a period closes, the daily cleanup deletes the period with its listings. **Clear signups** deletes a period's listings at once and keeps the period (audited, with confirmation). The privacy page describes the data and the 60 days.
