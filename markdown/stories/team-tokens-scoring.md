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

### Atomic Roster Activation Limit Enforcement
**User story**
As a player, I want the active-roster limit to be enforced correctly even under concurrent
activation requests, so that I can never end up with more active cards than the game intends
(and no one can exploit this for an unfair scoring advantage).

**Acceptance criteria**
- Firing many concurrent `POST /roster/{card_id}/activate` requests for the same user against
  distinct bench cards never results in more than `ROSTER_LIMIT` active cards, regardless of
  how many requests race
- A single, sequential activation request still behaves exactly as before: success when under
  the limit, 404 for a missing/foreign card, 409 "Card already active", 409 "Roster full ({N}
  cards max)" at the limit, 409 duplicate-player guard when another active card already has
  the same player
- The fix does not change the existing successful-path response shape
  (`{"status": "ok", "card_id": ...}`)

---

### Atomic Duplicate-Player Guard on Roster Swap
**User story**
As a player, I want `POST /roster/swap`'s duplicate-player guard to hold up under concurrent
swap requests, so that I can never end up with two active cards for the same player even if
overlapping swap requests race.

**Acceptance criteria**
- Firing concurrent `POST /roster/swap` requests that could both pass a naive read-then-write
  duplicate-player check never results in two active cards for the same player
- A single, sequential swap request still behaves exactly as before: 404 for missing cards, 409
  duplicate-player guard, and the existing bench↔active flip with `slot_index` handling
  unchanged

---

### Per-User Rate Limiting on Roster Mutations
**User story**
As an operator, I want the roster activate/deactivate/swap/reorder endpoints to enforce a
per-user rate limit so that rapid toggling — accidental or deliberate — can't meaningfully
load the backend.

**Acceptance criteria**
- `POST /roster/{card_id}/activate`, `/roster/{card_id}/deactivate`, `/roster/swap`, and
  `/roster/reorder` each enforce a per-user limit, configurable via
  `RATE_LIMIT_ROSTER_MUTATION` (default `30/minute`)
- The limit is keyed by the authenticated user's session `user_id`, not source IP, so it
  follows the account regardless of network; an unauthenticated caller falls back to being
  keyed by IP
- Exceeding the limit returns HTTP 429 with the same `{"detail": "Rate limit exceeded: ..."}`
  shape already established by issue #121
- The default is generous enough that normal roster-building activity (a handful of swaps
  while setting up a 5-card active roster) is never blocked

---

### Prevent Rapid Re-Fire from the Roster UI
**User story**
As a player, I want the roster UI to ignore extra activate/deactivate/swap clicks or drops
while a previous one is still in flight, so that impatient clicking can't queue up more
requests than the app can usefully process (and so I don't see a confusing partial-update
state from overlapping requests).

**Acceptance criteria**
- While an activate, deactivate, swap, or reorder request is in flight, a new interaction of
  the same kind (click, Enter/Space keyboard toggle, or drag-drop) for the same user is
  ignored rather than firing another request
- The guard clears once the in-flight request resolves (success or failure), so normal
  sequential use is unaffected
- No new UI affordance is required — existing interactions (card-image click/keyboard
  toggle, HTML5 drag-and-drop) are unchanged in appearance, only guarded against overlap

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
  clustered together), each match's two team names and logos, a VOD link where one has been
  set, and the date each match was played
- Before the user has revealed that week's results, no player names, points, MVP information,
  or winning-team highlight are shown — only the fields above

---

### Reveal Full Match Results
**User story**
As a user, I want to click "Reveal results" on a week's tab to see the full player-level
breakdown, so that I control when I see the outcome instead of it being shown immediately.

**Acceptance criteria**
- A "Reveal results" control is shown while any listed week is not yet revealed (see "Reveal
  Button Stays Visible While Scrolling" and "Reveal All Currently Available Results at Once")
- Using it permanently reveals, for each not-yet-revealed week: the winning team (now visually
  highlighted),
  every player in each match grouped under their team, the match's MVP player with a
  highlighted portrait, and a points-earned number under each player's portrait
- Players who were one of the viewing user's counted cards that week show a YOUR CARD / YOUR SUB
  tile with the user's card points (see "Your Cards in the Match Results"); other players show
  match points in a neutral/grey color
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

### Reveal Button Stays Visible While Scrolling
**User story**
As a user, I want the "Reveal results" control to stay visible at the bottom of the Weekly
Report popup regardless of how many matches are listed, so I don't have to scroll to find it.

**Acceptance criteria**
- The reveal control is docked to the bottom of the popup (not inside the scrollable match
  list) and remains visible while scrolling through a week's matches
- It is shown whenever at least one currently-listed week is not yet revealed, and hidden once
  everything currently listed has been revealed
- Scrolling the match list does not move, hide, or duplicate the docked control

---

### Reveal All Currently Available Results at Once
**User story**
As a user, I want a single "Reveal results" action to reveal every week currently shown in the
report, so I don't have to click reveal separately for each week tab.

**Acceptance criteria**
- Clicking the reveal control reveals every week currently listed in the popup that the user
  has not yet revealed, not just the currently active tab
- Weeks already revealed before the click are unaffected (idempotent — clicking again changes
  nothing for them)
- After the click, the active tab's content updates immediately to show the revealed state;
  switching to any other previously-unrevealed tab also shows it already revealed
- A week that becomes available (gets listed) after a previous "reveal all" click starts
  unrevealed, requiring the reveal control to be used again to reveal it

---

### Hide Match Outcome Until Revealed
**User story**
As a user, I want the winning team, MVP, and points breakdown all hidden until I reveal a
week's results, so glancing at the report can't spoil the outcome before I'm ready to see it.

**Acceptance criteria**
- Before a week is revealed, no team is visually marked as the winner and no "Winner" label is
  shown for either team in that week's matches
- MVP highlighting and per-player points remain hidden before reveal (existing behaviour,
  confirmed unaffected by this fix)
- After reveal, the winning team is visually highlighted exactly as before, alongside the
  existing MVP and points breakdown

---

### Match Date Displayed
**User story**
As a user, I want to see the date each match was played, so I can place the result in time
without cross-referencing the schedule tab.

**Acceptance criteria**
- Each match in the Weekly Report shows the date it was played
- The date is shown for every match regardless of reveal state, consistent with the other
  always-visible match fields (teams, VOD link)

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
- Scored stats (weight × value loop): `kills`, `assists`, `last_hits`, `denies`, `gold_per_min`, `obs_placed`, `towers_killed`, `roshan_kills`, `teamfight_participation`, `camps_stacked`, `rune_pickups`, `firstblood_claimed`, `stuns`
- Death scoring: separate clamped pool contribution (defaults: `death_pool = 3.0`, `death_deduction = 0.3`, floored at 0 — i.e. 0 deaths = 3.0 pts, then −0.3 per death)
- Death formula params (`death_pool`, `death_deduction`) and all stat weights are configurable via the `weights` table (defaults/overrides from `backend/seed.py` + optional `WEIGHTS_JSON` on startup)

---

### Include Assists in Fantasy Scoring
**User story**
As a league participant, I want assists to actually contribute to my fantasy score — matching
what's already captured, ingested, and shown to me — so that a strong assist-heavy performance
is reflected in my points instead of silently contributing nothing.

**Acceptance criteria**
- `assists` is added to `SCORING_STATS` in `backend/scoring.py`, flowing through the same
  weight × value loop as every other captured stat
- A new `assists` weight is added to `DEFAULT_WEIGHTS` in `backend/seed.py` (provisional
  default `0.15`), so it auto-seeds on next startup for both fresh and already-existing
  databases via `seed_weights()`'s existing idempotent upsert logic
- `card_modifiers`'s DB-level `CHECK` constraint is updated via a new migration (rebuilding
  the table the same way migration `008_card_modifiers_constraint` did) to allow `assists` as
  a valid `stat_key`, so card modifier rolls that land on it don't fail
- Card, roster, and leaderboard scores (since issue #141, sums of stored per-match card
  points) reflect the new weight once the stored points are rebuilt: automatically at the
  next startup (the weights fingerprint changes after seeding) or by running
  `POST /recalculate`
- Running `POST /recalculate` after the fix retroactively updates every already-ingested
  match's stored `player_match_stats.fantasy_points` (used by the Players tab match history
  and `/top`) to include assists, not just newly-ingested matches going forward

---

### Public Scoring Explanation Includes Assists
**User story**
As a player, I want the public "How to Play" scoring table to list Assists alongside every
other scored stat, so I understand what actually earns me points without needing to guess.

**Acceptance criteria**
- `frontend/app-init.js::loadHowToPlay()`'s stat list includes `assists` / `"Assists"`, so the
  rendered table shows its current weight value the same way every other stat already does

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

---

## Stored Card Points

### One Card Value Everywhere
**User story**
As a player, I want a card to show the same points on My Team, the weekly leaderboard, the season leaderboard and in season archives so that I can trust the numbers.

**Acceptance criteria**
- A card's points for a week are the sum of its stored per-match points for the scored matches in that week's window, on every page that shows them
- A card's season points equal the sum of its weekly points over the locked weeks it was rostered in
- A user's weekly and season totals equal the sum of their cards' points in that scope
- The death bonus is floored at 0 per match, so it matches the Players tab's per-match `fantasy_points` before card modifiers and rarity
- The season leaderboard view shows totals only (no card chips); the weekly leaderboard's card chips and My Team ("wk pts") show the same stored week value for a card
- Values are stored and summed unrounded and rounded once, in the response, to 1 decimal (`display_points`, issue #149); the page only formats them, and a list of card values can differ from the shown total by about 0.1

### Stored Per-Match Card Points
**User story**
As a developer, I want each card's points per match stored when the inputs change so that pages read totals instead of recalculating them on every request.

**Acceptance criteria**
- A `card_match_points` table stores one row per (card, match) with the card's final points for that match: stats with card modifiers, plus the MVP bonus when the player was that match's MVP, times the rarity multiplier. It has a unique constraint on (card_id, match_id)
- Rows are written or updated when:
  - a match is ingested or its stats are replaced after a parse (for every card of the players in it),
  - an MVP is set or changed (Twitch or admin, for that match),
  - a card is drawn (for all of that player's matches),
  - a card's modifiers are rerolled (for that card)
- Rows are deleted when their card or match is deleted (season reset, league purge) or when a match's stat rows are removed. Player removal only deactivates cards, so their rows are kept and past locked weeks still score
- My Team, the weekly leaderboard, the season leaderboard and End Season's `compute_season_standings` read `SUM(points)` from `card_match_points` joined to roster entries and weeks. They no longer call `card_fantasy_score` per request
- Match exclusion and week assignment are applied when reading, as today, so toggling them changes totals immediately without a rebuild

### Rebuild Stored Points
**User story**
As an admin, I want stored card points rebuilt when scoring rules change so that stored values never go stale.

**Acceptance criteria**
- `POST /recalculate` also rebuilds every `card_match_points` row, and its response says how many rows were written
- At startup, after weights are seeded, the table is rebuilt if it is empty or if the weights differ from those it was built with (a stored fingerprint of the weight values)
- A rebuild runs in one transaction; a failure leaves the previous rows in place and logs the error

### Faster Pages
**User story**
As a player, I want My Team and the leaderboards to load quickly as the season grows.

**Acceptance criteria**
- Each leaderboard and roster request runs a fixed number of queries, independent of the number of users and cards (no per-card Python scoring loop)
- `scripts/bench_leaderboards.py --compare scripts/bench-leaderboards-baseline.json` (60 users, 10 locked weeks, 20 matches per player) shows the season leaderboard at least 5× faster than the pre-#141 baseline of 112.5 ms median, and the weekly leaderboard no slower than its 18.3 ms baseline
- At `--weeks 20 --games 3` (240 matches, 6,000 roster entries) the season leaderboard stays under 100 ms median, against 584 ms before #141

---

## Automatic Bench Substitution

### Bench Saved at Lock
**User story**
As a player, I want my bench order saved when the week locks so that substitutions follow the order I set.

**Acceptance criteria**
- When a week locks, every card on each user's bench is saved to `weekly_roster_entries` with `is_bench = 1` and `bench_order` taken from the bench order on My Team (`slot_index` ascending with NULL last, then card id), alongside the active cards (`is_bench = 0`)
- Bench cards of deactivated players (`players.is_active = 0`) are not saved
- Saved bench entries don't count towards any points total unless substituted in
- Migration `029_weekly_roster_entries_substitution` adds `is_bench`, `bench_order`, `subbed_in`, `subbed_out` and `subbed_for_entry_id` to `weekly_roster_entries` and `substitutions_at` to `weeks`, all defaulting so existing rows remain active, non-substituted entries

### Automatic Substitution After the Week
**User story**
As a player, I want an active card whose player didn't play to be replaced by my highest bench card whose player did play so that rotation doesn't cost me the week.

**Acceptance criteria**
- `SUBSTITUTION_DELAY_HOURS` (default 24) after a locked week's `end_time`, its substitutions run once for every user
- Active cards are checked in roster slot order. Each one whose player has 0 scored matches in the week's window is marked `subbed_out`
- For each card marked `subbed_out`, the first bench entry (in `bench_order`) that qualifies is marked `subbed_in`: its player played at least one scored match that week, it isn't already subbed in, and its player isn't already counted on that week's roster
- If no bench card qualifies, the slot stays without points, as today
- An active card whose player played is never replaced, however few points it scored
- Each run writes one `weekly_substitutions` audit entry per week with the number of substitutions made
- Running it again for a week with no data changes gives the same result

### Points Count the Substituted Roster
**User story**
As a player, I want my week and season points to use the substituted roster so that the leaderboard reflects the swap.

**Acceptance criteria**
- A roster entry counts for a week when it is active and not `subbed_out`, or when it is `subbed_in`
- My Team for a locked week, the weekly leaderboard, the season leaderboard and End Season (`compute_season_standings`) all use that rule, as do the Weekly Report's "on roster" marks and the admin Week Management roster count (active entries only)
- Before substitution runs for a week, totals are exactly as today

### See What Was Substituted
**User story**
As a player, I want to see which cards were swapped so that a points change isn't a surprise.

**Acceptance criteria**
- My Team for a substituted week shows the subbed-in card on the roster with a "Subbed in for {player}" label, and the subbed-out card on the bench with a "Did not play" label
- `GET /roster/{user_id}?week_id=…` returns `subbed_in` / `subbed_out` per card and a `substitutions_done` flag for the week
- Before substitution has run, a locked week shows "Substitutions are made {N} hours after the week ends" under the roster
- The Weekly Report still opens when the week ends. Until that week's substitutions have run, a revealed week shows "Bench substitutions are made {N} hours after the week ends; roster marks may change.", and its "on roster" marks update once they run (`GET /weekly-summary/{week_id}` returns `substitutions_pending`)
- The How to Play Users subtab explains the rule in one bullet under Roster & Weekly Lock: bench order matters, left first

### Admin Re-Run
**User story**
As an admin, I want to re-run a week's substitutions after correcting match data so that the swaps match the final results.

**Acceptance criteria**
- `POST /admin/weeks/{week_id}/substitutions` (admin only) resets `subbed_in`, `subbed_out` and `subbed_for_entry_id` for that week and runs substitution again, returning the number of substitutions made
- It returns 409 for a week that isn't locked, or whose substitution time hasn't been reached
- It writes an `admin_substitutions_rerun` audit entry
- The admin Week Management table has a "Re-run substitutions" action on locked weeks once `end_time + SUBSTITUTION_DELAY_HOURS` has passed

---

## Consistent Points Rounding

### Same Week Points Everywhere
**User story**
As a player, I want my week points to show the same number on My Team and on the leaderboard so that I can trust the scores.

**Acceptance criteria**
- One helper, `display_points(x)` in `backend/scoring.py`, rounds a points value to one decimal, half away from zero, using its decimal value (`Decimal(repr(x))`) so binary artefacts don't change the result. For example 240.45 → 240.5, 231.25 → 231.3, 0.05 → 0.1, −0.05 → −0.1, and 2.675 → 2.7
- My Team's `combined_value`, `season_points` and each card's `total_points`, and the weekly and season leaderboards' totals and card `points`, all come from `display_points` applied to the exact sum
- For every user and week in the benchmark season, My Team's week total equals the weekly leaderboard's total exactly (0 mismatches, against 29 of 600 before)
- For every user, My Team's `season_points` equals the season leaderboard total

### One Rounding Rule for All Points
**User story**
As a player, I want every points number in the app and the Twitch panel rounded the same way so that the same value never shows two different ways.

**Acceptance criteria**
- `display_points` is used for:
  - the Twitch MVP panel player points (`GET /twitch/matches/current`),
  - Weekly Report per-match points,
  - `/top` points and `/leaderboard` average points,
  - archived season standings,
  - `/simulate` results, with two decimals there via a `places` argument, since the simulator compares weights
- No other `round(` on a points value remains in `backend/routers/` or `backend/twitch.py`, checked by a test that searches the source
- The frontend shows the server's value: `toFixed(1)` on an already-rounded number only formats it, and no frontend code rounds a points value any other way

### Explain Card Totals
**User story**
As a player, I want to know why my cards' values don't always add up exactly to my total so that a 0.1 difference isn't confusing.

**Acceptance criteria**
- Where the leaderboard lists a user's cards under their total, a one-line note reads "Totals are rounded from exact points, so card values may differ by 0.1 in sum"
- The How to Play scoring section has the same note once

## Weekly Report Roster Panel and Aesthetics

### Side-by-Side Weekly Report
**User story**
As a player, I want my roster and the match results side by side under the week tabs so that I can see what my cards scored and how the games went without switching views.

**Acceptance criteria**
- The week tabs are the only tabs in the popup. Below them, a "My roster" column (about 480 px) and a "Match results" column (the rest) sit side by side.
- The popup is at most 1280 px wide and 85% of the window height.
- Each column has a fixed header and its own scrolling area:
  - the roster header shows "My roster", the count of cards counted and substitutions, and the week total,
  - the results header shows "Match results" and the number of series and games.
- Both scrolling areas use a shared `.k-scroll` class in `frontend/style.css`:
  - thin, with the thumb in `var(--border)` and `var(--fg-dim)` on hover,
  - a transparent track and `var(--r-xs)` corners,
  - `scrollbar-gutter: stable` and at least 12 px between content and scrollbar.
  
  No hard-coded colours. `.card-grid` uses the same class instead of its own copy of the rules.
- Below 1100 px window width, the columns stack, roster first, and the popup scrolls as one page. At 375 px there is no horizontal scrolling.
- The docked "Reveal results" footer stays under both columns.

### My Roster Panel
**User story**
As a player, I want to see each card that counted for my roster this week, with the games its player played and what the card scored in each, so that I understand my week's points.

**Acceptance criteria**
- The roster lists the cards in two parts:
  1. **The counted cards**, in the same order as My Team for that week. A bench card that was subbed in takes the slot of the card it replaced. It is marked with a "SUBBED IN" tag and the line "From your bench, for {name}, who did not play this week". (#151 also gave it a tinted `var(--accent-ghost)` background; #152 removed it so that orange marks only the card being revealed, and the tag is now neutral.)
  2. **A "Did not play" group**, after the counted cards. It holds the original roster cards that were replaced, so it comes after the fifth counted card. It appears only when a substitution happened. The cards are greyed out with a dashed border and the line "No matches this week. Replaced by {name}", and their points don't count.
- Each card shows:
  - a thumbnail: the player's avatar in a rarity-coloured border (initials when there is no avatar; the shrunken card image was replaced because it blurred),
  - the player name as a player link and the team name as a team link,
  - a rarity tag (since #152: the rarity name below the thumbnail instead, see Points Breakdown per Card),
  - its status tag, if any,
  - the card's points for the week.
- Each card lists one row per game its player played that week:
  - the date,
  - "vs {opponent}", where the opponent is a team link,
  - the game number in the series,
  - WIN or LOSS,
  - an MVP tag if the player was that game's MVP,
  - the card's points for that game (`card_match_points`), including modifiers and the MVP bonus.
- A game excluded from scoring shows "Not scored" instead of points.
- Bench cards that weren't subbed in are not listed, because a bench can hold many cards. The "Did not play" group takes the subbed-out cards from `_build_roster_response`'s `bench` list, in its order, and drops the rest.
- The week total equals the sum of the counted cards' week points, and it equals the user's `week_points` on the weekly leaderboard for that week.
- Clicking or pressing Enter on a thumbnail opens the existing card viewer (`showCard`), with the full card image and its modifiers, on top of the report. The viewer's footer reads "{points} wk pts". Closing the viewer returns to the report with both scroll positions unchanged.

### Your Cards in the Match Results
**User story**
As a player, I want my own players marked in the match results, with my card's points, so that I can spot them at a glance.

**Acceptance criteria**
- A player the user had as a counted card that week gets a filled tile (`var(--accent-ghost)` background) with a "YOUR CARD" label, or "YOUR SUB" for a card that was subbed in. The tile shows the user's card points for that game instead of the match points.
- Other players show match points in the muted colour.
- The MVP outline and the "YOUR CARD" tile can appear together on the same player.
- The ownership mark uses a label and a filled shape, not colour alone.
- On a match excluded from scoring there are no card points (`card_points` is null), so no tile is marked there.

### Links Work as Everywhere Else
**User story**
As a player, I want player and team names in the Weekly Report to open the same popups as on the rest of the site so that I can look someone up without leaving the report.

**Acceptance criteria**
- Every player name (roster cards, result tiles) uses `playerLink(id, name)`, and every team name (roster card team, game opponent, series teams) uses `teamLink(id, name)`. Each is keyboard reachable, with the same hover style (`.entity-link`).
- The player and team popups and the card viewer open on top of the Weekly Report. Closing them leaves the report open on the same week, with both scroll positions unchanged.
- `.reveal-overlay` stacks above `.modal-overlay`, so the card viewer is never hidden behind an open popup.

### Reveal and Substitution States
**User story**
As a player, I want the roster panel to follow the report's reveal and substitution rules so that it doesn't spoil results or show points that may still change without saying so.

**Acceptance criteria**
- Before the week is revealed, the roster panel lists the cards (up to five) as they were at lock time: a replaced card stays in its slot and the substitute is not shown, so the list gives nothing away. It shows thumbnails, names, teams and rarity only. Points, game rows, win/loss, MVP tags and status tags stay hidden, and the panel says "Reveal results to see your points". Clicking a thumbnail still opens the card viewer.
- While substitutions are pending (`substitutions_pending`), the roster header shows the existing note that substitutions run {N} hours after the week ends and statuses may change.
- The API returns no per-game points, results or statuses for an unrevealed week.

### New Recap Popup
**User story**
As a player, I want a popup telling me when a new weekly recap is ready so that I don't miss it. I also want it to show up only once, so that it doesn't nag me.

**Acceptance criteria**
- **When it appears:** after login or page load, a popup "Week {label} recap is ready" (a label that already starts with "Week" is used as is) appears when the newest available report week has not been announced to the user yet. That means not opened and not shown as this popup before.
- **Content:**
  - one line, "See what your cards scored and how the matches went",
  - a note that the recap is also under Weekly Report at the top right,
  - an "Open recap" button (primary) and a "Close" button, plus an X.
  
  It gives no results, points or winners away.
- **Open recap** opens the Weekly Report on that week and marks it both announced and seen, which clears the dot on the header button.
- **Close**, the X, Esc or a click on the backdrop closes the popup and marks the week announced only. The dot on the Weekly Report button stays until the report is opened.
- **Once per week:** once announced, the popup does not reappear for that week, on any device or after logging in again. It appears again only when a newer week's report becomes available.
- **One popup at a time:** when several weeks are new, the popup announces the newest only, and opening it shows that week with the other week tabs available.
- **No clashes:** the popup does not appear while another popup or the guided tour is open, or while the user must change their password. It is shown on a later page load instead, since nothing was marked.
- **Keyboard:** focus moves to "Open recap" when the popup opens, and Tab stays inside the popup.

## Weekly Recap Animations

### Points Breakdown per Card
**User story**
As a player, I want each card in the Weekly Report to show how its points were made up so that I understand what my rarity, modifiers and MVPs contributed.

**Acceptance criteria**
- Every counted card in a revealed week's `roster.cards` (`GET /weekly-summary/{week_id}`) has a `breakdown` covering its counted, scored games that week:
  - `raw`,
  - `steps`, a list in this order:
    - rarity (only when the rarity bonus is above 0),
    - one entry per modifier (stat label and %),
    - one MVP entry **per MVP game** (with that game's `match_id`). A player who was MVP in two games gets two MVP steps, so two separate scoring ticks.
  
  Each step has its points, rounded with `display_points`.
- The exact (unrounded) parts add up to the card's stored points within 1e-6. The rounded `raw` plus the rounded steps equal the card's `week_points` exactly, because the rounding remainder goes to the last step (or to `raw` when there are no steps).
- Cards in the "Did not play" group and unrevealed weeks have no `breakdown`.
- When the reveal animation is finished, skipped or never played, each card shows its breakdown where each bonus comes from:
  - **Tag row** under the player's name, in the order the bonuses are added, left to right: "RAW 48.2", then the modifier chips ("KILLS +10% +1.2", "GPM +10% +1.6"), then a status tag ("SUBBED IN") at the end. There is no rarity chip or tag in this row. The row wraps when needed.
  - **Rarity bonus:** shown on the card thumbnail on the left. The thumbnail keeps its rarity-coloured border, with the rarity name below it. Under that, a small caption in the rarity colour reads "+3% +1.4". A card with no rarity bonus (common) has no caption.
  - **MVP bonus:** shown on the MVP tag of the game row that earned it: "MVP +1.5". Each MVP game shows its own bonus.
  - The game rows (#151) stay below the tag row, so the breakdown and the games don't compete for the same place.

### Card-by-Card Reveal
**User story**
As a player opening a revealed week, I want my cards revealed one at a time with their points counting up so that the recap feels like a reveal, not a table.

**Acceptance criteria**
- **Order:** cards appear one at a time in reverse roster order, each at the top of the My roster list, so the finished list is in My Team order.
- **Entry transition:** the cards already shown move down smoothly while the new card's slot opens from zero height at the top, in about 340 ms with an ease-out. Then the new card **slides in from the left edge of the column** into the open slot: about 420 ms, ease-out (cubic), with its opacity rising from 0 to 1 over the first 60% of the slide.
- **Count-up:**
  - each card's number counts up from 0 to its `raw` with an accelerating (ease-in) curve,
  - the number grows slightly and gains an orange glow as it rises,
  - the count lasts `clamp(1000 + raw × 35, 1000, 3000)` ms,
  - **the RAW chip is highlighted (filled, glowing) for the whole count and shows the running value**, then settles to its lit state about 0.2 s after the count ends. It doesn't flash only at the end.
- **Week total:** the header's week total starts at 0 and counts up by each card's final points as that card finishes. At the end it equals `roster.week_total`.
- **After the counted cards:** the "Did not play" group appears without animation.
- **Results column:** stays usable during the animation.

### Bonus Highlights
**User story**
As a player, I want each bonus on a card highlighted as it is added so that I can see what my rarity, each modifier and an MVP were worth.

**Acceptance criteria**
- After the count-up, each step in `breakdown.steps` plays in order: rarity, then the modifiers left to right, then MVP. For each step:
  - the element that earned it (the rarity caption, the modifier chip or the MVP tag) changes from a pending to a filled, glowing state with "+points",
  - **at the same moment** the card total jumps to its new value. It doesn't count up as the raw points do. Instead, the number pops (about 28% larger, shrinking back over about 520 ms) and a small "+points" label floats up from it and fades out.
- **Rarity step:** played only on the card thumbnail on the left:
  - the thumbnail glows in the rarity colour and scales up slightly (rarity colours are allowed on card badges); the card's own border doesn't change,
  - its "+pct% +points" caption appears,
  - the floating "+points" uses the rarity colour.
- **Modifier step:** the modifier's chip glows orange.
- **MVP step:** played on the game row with that MVP:
  - the row is tinted orange,
  - its MVP tag fills and glows and gains "+points".
  
  A player who was MVP in several games gets one tick per game, in game order, each with its own pop.
- **Steps without a bonus:** a card with no steps (a common card with no modifiers and no MVP) goes straight to the next card.
- **Final value:** after the last step, the card total equals its `week_points`.

### Control and Accessibility
**User story**
As a player, I want to skip or replay the reveal, and to have it respect reduced motion, so that it never gets in my way.

**Acceptance criteria**
- **Skip:** a "Skip" button in the My roster header is visible while the animation plays. It shows the finished state at once, with all chips lit and totals final.
- **Replay:** a "Replay" button shows when the animation isn't playing and reduced motion is off, on a week with at least one counted card, and plays it again from the start.
- **Plays once per week:** the animation plays once per week per browser. The played week ids are stored in `localStorage` under one key per user. Reads and writes are wrapped in try/catch, so if storage is unavailable the animation simply plays again.
- **Reduced motion:** with `prefers-reduced-motion: reduce` (`_prefersReducedMotion()`), nothing animates and the finished state is shown.
- **Leaving early:** switching week tab, closing the report or opening another week stops a running animation cleanly, with no timers left running.
- **Screen readers:**
  - while animating, the roster body has `aria-busy="true"`,
  - each card's final points are in its accessible text from the start, so screen readers never hear the counting numbers,
  - the counting number itself is `aria-hidden`.

## Weekly Report Readability

### Readable Weekly Report
**User story**
As a player reading my weekly recap, I want its text large and clear enough to read comfortably so that I can follow my points without squinting.

**Acceptance criteria**
- No text in the Weekly Report or the recap popup is below 11 px. Game rows, tags, bonus chips, notes, player names and points on result tiles, and dates are 13 px.
- Big Shoulders is used only at 13 px and up; smaller labels use Inter.
- Readable text has at least 4.5:1 contrast (`--fg-muted` or brighter); `--fg-dim` is not a text colour.
- Points use tabular numerals.
- Font sizes use `rem` tokens, so the browser's font-size setting scales the report.
- A static test (`backend/tests/test_weekly_report_readability.py`) fails if any of these regress.
