# Team, Tokens, and Scoring

## Onboarding

### Starter Tokens
**User story**
As a newly registered user, I want to receive tokens when I sign up so that I can start building my active lineup immediately.

**Acceptance criteria**
- Tokens are granted at registration (configurable via `INITIAL_TOKENS`)

---

### Token Visibility
**User story**
As a user, I want to know how many tokens I currently have.

**Acceptance criteria**
- Token balance is visible in the header across all tabs
- Balance updates immediately after any token-changing event (draw, redeem, weekly grant)

---

### View Cards and Points
**User story**
As a new user, I want to see the cards I have drawn and the points they are earning.

**Acceptance criteria**
- Each drawn card displays player identity, rarity, and current week's points
- Cards are clearly shown as benched until placed into the weekly roster
- Two separate point pools visible: weekly and season

---

## Active Lineup

### Place Cards into Active Slots
**User story**
As a user, I want to assign cards to the upcoming week's roster.

**Acceptance criteria**
- Upcoming week's roster has 5 slots
- User can move a card from bench to active roster (Activate)
- User can move a card from active roster to bench (Bench)
- Only one card may be active from a single player
- Roster changes are only allowed on the editable (upcoming) week, not on locked past weeks

---

### Weekly Lock
**User story**
As a user, I want cards to lock once a week's match window begins.

**Acceptance criteria**
- Weeks are created by an admin with explicit start/end boundaries (no fixed weekly
  cadence) — see `reference/season-lifecycle.md`
- A background maintenance thread locks a week automatically once its start time passes
- UI indicates that the week is locked and shows a locked banner
- User is informed of the upcoming lock date on the My Team tab
- Locked roster is immutable and shown as a read-only snapshot

---

### View Past Week Snapshots
**User story**
As a user, I want to review my roster and points from any past week.

**Acceptance criteria**
- Week selector dropdown on the My Team tab lists all season weeks
- Selecting a past locked week shows the immutable roster snapshot for that week
- Weekly points shown reflect only matches played during that specific week
- Current editable roster is always accessible via the selector

---

### Admin Series Week Override
**User story**
As an admin, I want to correct series timing when teams play out of the regular week cycle.

**Acceptance criteria**
- Ability to see series in the Admin tab
- Ability to select a series and input a corrected match week
- Corrected assignment is persisted so that future schedule refreshes or ingestions do not override it

---

## Weekly Summary Report

### View the Weekly Report
**User story**
As a user, I want to open a "Weekly report" button and see a tab per finished week showing
that week's matches, so I can review the tournament results at a glance.

**Acceptance criteria**
- A "Weekly report" button is shown in a fixed corner of the UI, visible whenever the user is
  logged in
- Clicking it opens a popup with one tab per week that has a generated summary, labeled by
  week number/label, defaulting to the most recent week's tab
- Weeks with no generated summary yet do not appear as tabs — tabs are populated as the
  season progresses, not shown in advance
- Each week's tab shows its matches grouped by series (matches between the same two teams
  clustered together), each match's two team names and logos, and a VOD link where one has
  been set — with the winning team visually highlighted
- Before the user has revealed that week's results, no player names, points, or MVP
  information are shown — only the fields above

---

### Reveal Full Match Results
**User story**
As a user, I want to click "Reveal results" on a week's tab to see the full player-level
breakdown, so that I control when I see the outcome instead of it being shown immediately.

**Acceptance criteria**
- Each not-yet-revealed week tab shows a "Reveal results" button
- Clicking it permanently reveals, for that week: every player in each match grouped under
  their team, the match's MVP player with a highlighted portrait, and a points-earned number
  under each player's portrait
- The points-earned number is shown in a neutral/grey color for players not on the viewing
  user's roster that week, and in an accent color for players who were on it
- Reveal state is per-user and per-week: one user revealing a week does not reveal it for any
  other user, and revealing one week does not reveal any other week
- Reopening the popup later (same session or after logging back in) shows previously revealed
  weeks already revealed, without needing to click "Reveal results" again

---

### New Report Highlight
**User story**
As a user, I want a visual cue on the Weekly report button when a new week's report becomes
available, so I notice it without having to check manually.

**Acceptance criteria**
- The Weekly report button shows a highlight/badge once a new week's summary has been
  generated and the current user has not yet opened the report popup since then
- Opening the report popup clears the highlight, regardless of whether the user reveals any
  week's results while it's open
- The highlight reappears the next time a further week's summary is generated, following the
  same per-user "not opened since" rule

---

### Automatic Weekly Summary Generation
**User story**
As the system, I want to mark a week's summary as available as soon as that week's scoring
window has actually closed, so reports reflect complete results regardless of whether a week
maps to a calendar week.

**Acceptance criteria**
- A week becomes available in the Weekly Report once `now >= week.end_time` — the same
  boundary (including its grace period) used by `auto_lock_weeks` — not a fixed calendar
  schedule
- The check runs from the existing week-maintenance background loop, so it applies uniformly
  to regular weeks and irregular ones (e.g. a finals week with a short window)
- Re-running the check after a week is already marked available does not re-trigger or
  duplicate anything (idempotent, matching the existing `auto_lock_weeks` pattern)
- A week with zero matches still becomes available (shown as an empty-state tab) rather than
  never appearing in the report

---

### Admin: Attach VOD Links to Matches
**User story**
As an admin, I want to attach a caster's VOD link to a match after the fact, so viewers can
find the recording from the Weekly Report.

**Acceptance criteria**
- Admin can set, edit, or clear a VOD URL on any match from the existing admin match tooling
- An invalid (non-URL) value is rejected with a clear error; clearing is always allowed
- Once set, the VOD link appears next to that match in the Weekly Report for every user,
  including weeks whose summary was generated before the link was added
- Clearing the VOD URL removes the link from the report without affecting anything else in
  that week's summary

---

## Tokens

### Free Weekly Token
**User story**
As a user, I want a free weekly token.

**Acceptance criteria**
- When the week is locked all users are granted 1 additional token

---

### Spend Token to Draw Card
**User story**
As a user, I want to draw a card using a token.

**Acceptance criteria**
- 1 token deducted
- Card marked as owned by the user
- Card shown to user immediately in a reveal modal

---

### Redeem Code
**User story**
As a user, I want to redeem a promo code for tokens.

**Acceptance criteria**
- Valid code grants tokens
- Invalid code shows an error
- One use per user
- Logged in the audit log

---

### Re-roll Modifiers
**User story**
As a user, I want to spend a token to re-roll a card's stat modifiers so that I can try for a more useful modifier combination.

**Acceptance criteria**
- Costs 1 token per reroll; returns 409 if the user has no tokens
- All existing modifiers on the card are replaced with a freshly randomised set (same count and bonus rules as draw time)
- Card rarity, player, and league are unchanged — only modifiers are replaced
- Action is recorded in the audit log
- Frontend shows a confirmation prompt before spending the token
- Updated modifier list and remaining token balance are returned in the response

---

## Scoring

### Score Active Cards
**Acceptance criteria**
- Uses Dota 2 match data from OpenDota
- Only active (locked) cards score
- No double counting of matches
- Scored stats (weight × value loop): `kills`, `last_hits`, `denies`, `gold_per_min`, `obs_placed`, `towers_killed`, `roshan_kills`, `teamfight_participation`, `camps_stacked`, `rune_pickups`, `firstblood_claimed`, `stuns`
- Death scoring: separate clamped pool contribution (defaults: `death_pool = 3.0`, `death_deduction = 0.3`, floored at 0 — i.e. 0 deaths = 3.0 pts, then −0.3 per death)
- Death formula params (`death_pool`, `death_deduction`) and all stat weights are configurable via the `weights` table (defaults/overrides from `backend/seed.py` + optional `WEIGHTS_JSON` on startup)

---

### Card Modifier Scoring
**Acceptance criteria**
- Rarity bonus applied on top of raw fantasy points (common +0%, rare +1%, epic +2%, legendary +3% by default)
- Per-stat modifiers applied at scoring time based on the card's assigned modifiers
- Rarity modifier percentages are configurable
- Modifiers can only target stats in `SCORING_STATS` plus `deaths` (DB-enforced); they amplify that stat's contribution (including amplifying the death-pool contribution when `stat_key = deaths`)
- New draws and rerolls only assign modifiers from the current valid stat pool (13 stats: 12 scored stats + `deaths`)

---

### Track Season and Weekly Points
**Acceptance criteria**
- Persistent total score per user across all locked weeks visible on the My Team tab and leaderboard
- Per-week card point contribution visible in the week snapshot view
- Historical tracking via the week selector

---

### Prevent Duplicate Scoring
**Acceptance criteria**
- Match events uniquely tracked
- Safe to retry ingestion — already-stored records are not duplicated
