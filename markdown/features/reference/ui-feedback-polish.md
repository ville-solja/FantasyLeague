# Design-System States and Emphasis

Rules for selected controls, badges, the signed-in user's row, emphasis inside data, what can be selected, and data-row alignment. They are written into the Kanaliiga Design System and applied the same way across the site. The issue also covered the Weekly Report's no-flash caching. Resolves GitHub issue #202; plan: `markdown/plans/plan-issue-202-ui-feedback-polish.md`.

Frontend and design docs only: no endpoint, schema or env var change.

---

## Where the rules live

- **Rules:** `.claude/skills/README.md`, VISUAL FOUNDATIONS › "States and emphasis". The core brand rules in `.claude/commands/ui-design.md` point to it.
- **Tokens:** `frontend/colors_and_type.css`, kept identical to `design/colors_and_type.css` (`test_weekly_report_readability.py` checks this):

  | Token | Value | Used for |
  |---|---|---|
  | `--state-selected-hover-bg` / `-fg` | `--accent` / `--accent-fg` | Selected control on hover or keyboard focus |
  | `--badge-admin` | `--accent` | ADMIN role badge |
  | `--badge-winner` | `--k-amber-500` | Season Winner tag |
  | `--badge-caster` | `--fg` | Caster tag |
  | `--badge-tag` | `--fg-muted` | Any other tag |
  | `--badge-status` | `--fg-muted` | Status badges |
  | `--row-self-bg` | `--accent-ghost` | The signed-in user's rows |
  | `--mark-winner` | `--k-amber-500` | Winning team name and its label |
  | `--mark-mvp` | `--accent` | MVP labels (results and My roster) |

- **Shared classes:** the "SHARED STATES (issue #202)" section of `frontend/style.css`, placed before GUIDED TOUR: the selected + hover / focus-visible selector list, `.role-badge` and its variants (`-admin`, `-winner`, `-caster`, `-tag`), `.status-badge` (also styling `.league-week-tag` and `.live-tag`), `.badge-list`, `.row-self`, `.mark-winner` / `.mark-mvp`, and the `img` / `button` selection rules. The per-surface copies they replace (`.admin-badge`, `.tag-chip`, the schedule tag styles, inline badge styles) are gone.
- **Badge helpers** in `frontend/app-globals.js`:
  - `adminBadgeHtml(isAdmin)`: the ADMIN role badge, only when `isAdmin === true`, title "Kana Cards admin".
  - `tagBadgeHtml(tag, opts)`: a tag as a role badge. The variant and hover reason come from `_TAG_BADGE_VARIANTS` / `_TAG_BADGE_REASONS` (`caster`: "Verified caster: an approved tournament streamer"; `season_winner`: "Won a previous season"); any other key is the neutral tag variant with its label as the reason. Keys are looked up as own properties only. `opts.title` and `opts.suffix` let User Management show a synced Caster tag as "Caster (auto)" with its #201 explanation.
  - `statusBadgeHtml(label, title)`: a neutral status badge.

  Labels and titles are escaped with `_escHtml`; no badge markup has an inline `style`.

## Rules as applied

- **Selected + hover / focus-visible** inverts all seven selected controls: `.tab.active`, `.weekly-summary-tab-btn.active`, `.howtoplay-tab-btn.active`, `.admin-tab-btn.active`, `.schedule-div-chip.active`, `.schedule-week-chip.selected` and `.schedule-hide-toggle[aria-pressed="true"]`. Focus keeps a `2px solid --accent` outline (offset 2 px). On a selected week chip that is also the current week, the accent "This week" label and the hidden-results marker switch to `--state-selected-hover-fg` while inverted. Unselected hover is unchanged. The schedule chips keep their neutral selected look, because an accent border there marks the current week.
- **Role badges:** display font at `--fs-sm` (the readability rule allows Big Shoulders only at `--fs-sm` and up, so the plan's `--fs-xs` was not used), bold, uppercase, `--tr-wider`, coloured text, transparent fill, a hairline `currentColor` border, `--r-xs`. Shown on the season and weekly standings (ADMIN on past season standings too), Profile (`#profileAdminBadge`, `.profile-tags`) and Admin › User Management.
- **Status badges:** the same shape with `--badge-status` text and a `--border` outline: TESTER, ID SHARED, the Steam and Twitch link badges (#201), "(You)", "League week N" and LIVE. LIVE keeps the semantic `--k-err` text colour.
- **Unchanged:** card stickers on card art (since retired, issue #217), rarity chips (`.lb-chip-rarity`, `.common` … `.legendary`), the version and demo-mode badges, and the Weekly Report's roster status chips (`.weekly-summary-tag`, SUBBED IN / NOT COUNTED), which already had the neutral status look. The Weekly Report shows no user tags or ADMIN badge.
- **Self row:** `_lbStandingsRow` (season and weekly standings) marks the signed-in user's row, and its card detail row, with `.row-self` and adds a "(You)" status badge; `loadPastSeasonStandings` marks the row whose `user_id` matches. Logged out, nothing is marked (`_lbIsSelf`). The old inline `color:#f0b429` is gone, and `app-leaderboard.js` has no hex colours left (empty-table rows use `.table-empty`). The My Team week status line uses `--k-amber-500` / `--fg-muted` instead of hex.
- **Weekly Report emphasis:** no ring on the winner or the MVP. The markup uses the shared classes: the "Winner" label and the winning team's name block carry `.mark-winner` (bold `--mark-winner`; the name is marked even when it is plain text because the team has no id); the MVP tile's "MVP" label, on its own line above the avatar, and the My roster MVP chip (no border) carry `.mark-mvp`. The surface rules set no colours of their own. The recap's glow on an MVP chip (`.weekly-summary-game-mvp.hl`) is a transient motion highlight, exempt from the no-rings rule.
- **Selection:** `img` and `button` are `user-select: none`, and images are not draggable (`-webkit-user-drag: none`, plus `draggable="false"` on every `<img>` the frontend modules generate: Weekly Report, leaderboards, players and team popups, booster teams, admin players, roster cards). Names, dates, points and prose stay selectable. Card art keeps its hover lift.
- **Data rows:** each My roster game row (`.weekly-summary-game`) is a grid of date | opponent | game | result | MVP | points with fixed rem columns and a flexible opponent column that wraps. The result and MVP cells are always emitted (empty when they don't apply), so columns line up across rows and cards, and the MVP chip has no padding or border, so MVP rows are no taller. At 600 px and below each row takes two lines (date, opponent, points; then game, result, MVP). The card header aligns the player name and total on their baseline.

## Weekly Report cache

Week data stays cached for the page visit as `{data, at}`. Reopening renders a cached week without dimming and refreshes it quietly only when it is more than 60 s old; the week list is reused for 60 s too. The cache is cleared on reveal, on logout or user switch (`clearWeeklySummaryCache()`, called from `_clearLocalAuthState()`, before a new sign-in and from `loadMe()` when the user id changes), and when the week list's signature changes. Clearing bumps the request counter, so a fetch still in flight for the previous user never lands; and the cache records its owner (`activeUserId`), so a user change made in another tab drops it on the next use. A recap plays at most once per week per page visit: one interrupted by a week switch or by closing the popup does not play again on reopening, and **Replay** plays it. Clicking the active week tab does nothing, and `POST /weekly-summary/seen` is sent only when the list reported unseen reports. Details: `markdown/features/core/weekly-summary.md` › "Client Cache".

## Tests

`backend/tests/test_issue_202_ui_feedback_polish.py`: static checks on the README, tokens, `style.css` and the frontend modules; a Node harness for the badge helpers and `_lbStandingsRow`; and a Node harness that runs `app-weekly-summary.js` against a fake DOM, fetch and clock for the cache. Older tests that pinned the replaced behaviour were updated in the same change (#151 MVP outline, #159 cache on close, #169 `.admin-badge`, #188 `.tag-chip`, and the #201 users-table harness, which now loads the badge helpers).
