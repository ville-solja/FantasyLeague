# Plan: Design-System Rules from UI Feedback (Issue #202)

## Context
Issue #202 is a list of usability feedback. Most of it is about **states and emphasis**: how a selected control reacts to hover, what role badges look like, how your own row stands out, how the winner and MVP are marked, what can be selected, and how data rows line up. The site already has a design system:
- `.claude/skills/README.md` "Kanaliiga Design System": voice, palette, type, borders, radii, hover, press and focus;
- the tokens in `frontend/colors_and_type.css`, mirrored in `design/colors_and_type.css` and kept equal by `test_weekly_report_readability.py`;
- the core brand rules repeated in `.claude/commands/ui-design.md`.

The system has **no rules** for any of those states, so each surface invented its own:
- the ADMIN badge uses the display font with an outline, while tag chips are inline-styled filled boxes in the body font;
- your standings row is gold text set inline (`#f0b429`, which isn't a token);
- the Weekly Report rings both the winner and the MVP in accent;
- seven different "active" controls (`.tab`, `.weekly-summary-tab-btn`, `.howtoplay-tab-btn`, `.admin-tab-btn`, `.schedule-div-chip`, `.schedule-week-chip`, `.schedule-hide-toggle[aria-pressed]`) each define their own active look, and none defines active plus hover.

**Approach:**
1. Write the missing rules into the design system first. Back them with semantic tokens in `colors_and_type.css` and with shared CSS classes in one "Shared states" section of `style.css`.
2. Apply them **everywhere** the pattern appears, not only where the feedback pointed.

Feedback point 9 (Weekly Report flashing) is caching behaviour, not design. It stays in this plan as its own story.

**Fitting the existing rules:** the first draft of this plan broke two existing rules, and this version follows them instead:
- "No left-border accent cards": the own-row highlight is a full-row tint, not a left bar.
- "Rarity colours never as chrome": role badges use only flame, amber and neutral colours, not rare-blue.

**Decisions** (assumptions; change them in review if needed):
- **Selected + hover = inverted:** accent fill with `--accent-fg` text.
- **Role badge colours:** ADMIN `--accent`; Season Winner `--k-amber-500` (the palette's accent glow); Caster `--fg` (the neutral highlight); any other tag `--fg-muted`. Each is a semantic token, so it can be changed in one place.
- **Badge reasons on hover:** they come from a small frontend map keyed by tag key, falling back to the label. No schema change.
- **Weekly Report cache:** kept for the page session, invalidated on reveal, logout or user switch and when the week list changes. Data older than 60 s is refreshed quietly.
- **Emphasis colours:** `--mark-winner` is `--k-amber-500` (like the Season Winner badge) and `--mark-mvp` is `--accent` (like the existing My roster MVP chip).

**Review resolutions** (the code and the existing design rules win over the first draft):
- The seven selected controls use their real selectors, including `.schedule-week-chip.selected` (not `.active`).
- Badges use the display font at `--fs-sm`, not `--fs-xs`: the readability rule allows Big Shoulders only at `--fs-sm` and up.
- The Weekly Report shows no user tags or ADMIN badge, so it is not a badge surface; its roster status chips (`.weekly-summary-tag`) stay as they are.
- Badge and self-row surfaces: `_lbStandingsRow` and `loadPastSeasonStandings` (rows carry `user_id`) in `app-leaderboard.js`; Profile's tags and `adminBadgeHtml`; `_renderUsers` and `_linkBadges` in `app-admin-users.js` (keeping "Caster (auto)" from #201); the schedule's `.league-week-tag` and `.live-tag`, which share the status-badge rule (LIVE keeps its red text); and the hex colour on My Team's week status line (`app-roster.js`).
- The cache is cleared from `_clearLocalAuthState()` (logout, expired session) and `login()` (also registration and Steam sign-up); `has_unseen` decides the "seen" POST.
- Older tests that pinned the replaced behaviour are updated in the same change (#151, #159, #169, #188, #201 harness).

Frontend and design docs only: no endpoint, schema or env var change.

Resolves GitHub issue #202.

## User Stories

### The Design System Defines States and Emphasis
**User story**
As a developer or designer, I want the rules for selected, badge, self, emphasis, selection and data-row patterns written in the design system and backed by tokens, so that every surface applies them the same way instead of inventing its own.

**Acceptance criteria**
- **New section:** `.claude/skills/README.md` gets a "States and emphasis" section under VISUAL FOUNDATIONS with these rules, each naming its tokens and shared class:
  - **Selected:** accent text plus a 2 px accent underline (tabs) or a 1.5–2 px border (chips, toggles). The schedule chips keep their neutral selected border, because an accent border there marks the current week.
  - **Selected + hover / focus-visible:** inverted, with an `--accent` fill and `--accent-fg` text, through one shared selector list. Unselected hover stays as it is (muted → `--fg`).
  - **Role badges:** one family (`.role-badge`): display font, bold, `--fs-sm` (the readability rule allows Big Shoulders only at `--fs-sm` and up), uppercase, `--tr-wider`. Coloured text, no fill, a 1 px border in the same colour, `--r-xs` (2 px). Every badge has a `title` giving its reason. Rarity colours are never used for roles.
  - **Status badges** (LIVE, league week, ID SHARED, Steam/Twitch, TESTER, "(You)"): the same type and shape, in neutral (`--fg-muted` text, `--border` outline), so they read as information rather than roles. LIVE keeps its semantic red text.
  - **Self (the signed-in user):** a full-row `--row-self-bg` tint and bold text, plus a "(You)" label in the badge style. No left bars and no inline colours.
  - **Emphasis inside data:**
    - the winning side is `--mark-winner` text, bold, with a label;
    - the MVP is a `--mark-mvp` label before the name;
    - the two never share a colour or a form.
    - No rings or outlines around floating elements; borders belong to controls and cards only.
  - **Selection:** images and controls are `user-select: none` and not draggable. Names, dates, numbers and prose stay selectable.
  - **Data rows:** repeated rows (game lists, standings, tables) use a fixed-column grid with `tabular-nums` on numbers. Inline chips must not change row height.
- **Tokens:** `colors_and_type.css` gets the semantic tokens below, in both copies, which stay identical (the existing test):
  - `--state-selected-hover-bg`, `--state-selected-hover-fg`;
  - `--badge-admin`, `--badge-winner`, `--badge-caster`, `--badge-tag`, `--badge-status`;
  - `--row-self-bg`;
  - `--mark-winner`, `--mark-mvp`.
- **`/ui-design`:** its core brand rules list in `.claude/commands/ui-design.md` gains one line pointing to "States and emphasis".
- **Shared classes:** `style.css` gets a "Shared states" section (before GUIDED TOUR) holding the shared classes and selectors. Surfaces use these classes instead of their own copies.

### Selected Controls Respond to Hover Everywhere
**User story**
As a player, I want every selected tab, chip or toggle to react when I hover it, so that every control gives the same feedback.

**Acceptance criteria**
- **Covered controls:** all seven selected controls follow the Selected + hover rule through one shared selector list:
  - main tabs (`.tab.active`);
  - Weekly Report week tabs (`.weekly-summary-tab-btn.active`);
  - How to Play subtabs (`.howtoplay-tab-btn.active`);
  - Admin subtabs (`.admin-tab-btn.active`);
  - Schedule division chips (`.schedule-div-chip.active`);
  - Schedule week chips (`.schedule-week-chip.selected`);
  - the Schedule hide-results toggle when pressed (`.schedule-hide-toggle[aria-pressed="true"]`).
- **Focus:** `:focus-visible` on a selected control shows the same style, and the focus outline is kept.
- **Unselected hover:** unchanged.

### Badges Look Like One Family and Explain Themselves
**User story**
As a player, I want role and status badges to look consistent and tell me what they mean, so that I can tell them apart and understand them.

**Acceptance criteria**
- **Role badges:** the ADMIN badge (`adminBadgeHtml`) and user tags use `.role-badge` with their token colour and a `title`:
  - ADMIN: "Kana Cards admin";
  - `caster`: "Verified caster: an approved tournament streamer";
  - `season_winner`: "Won a previous season";
  - any other tag: its label.

  This applies wherever they appear: the season and weekly standings (`_lbStandingsRow`; ADMIN also on the past season standings), Profile (`#profileAdminBadge`, `.profile-tags`, replacing `.tag-chip`) and Admin › User Management (`_renderUsers`, where a synced Caster tag still reads "Caster (auto)" with its #201 explanation). The Weekly Report shows no user tags or ADMIN badge; its roster status chips (`.weekly-summary-tag`) stay as they are.
- **Status badges:** TESTER, LIVE (`.live-tag`), "League week N" (`.league-week-tag`), ID SHARED and the Steam/Twitch link badges (#201) use the neutral status style (`statusBadgeHtml` / `.status-badge`; the two schedule classes share its rule).
- **Unchanged:** card stickers on card art, rarity badges and the version and demo-mode badges.
- **No inline styles:** no badge markup in `app-*.js` has an inline `style` attribute. Labels and titles are escaped (`_escHtml`).

### Your Own Row Stands Out Wherever You Appear
**User story**
As a logged-in player, I want my own row highlighted in every ranking, so that I can find my placement at a glance.

**Acceptance criteria**
- **Rankings:** the signed-in user's row in the season and weekly standings has the class `row-self`: a full-row `--row-self-bg` tint and bold text. Its expandable card detail row gets the same tint.
- **Other rankings:** any other ranking that shows users uses the same class: the past season standings mark the row whose `user_id` matches.
- **Cleanup:** the inline `color:#f0b429` style and the inline style on the "(You)" label are removed (and the `#f0b429` on My Team's week status line becomes a token). "(You)" uses the status badge style.
- **Logged out:** no row is highlighted.

### Weekly Report Emphasis Follows the Rules
**User story**
As a player reading match results, I want the winner and the MVP marked clearly and differently, so that each highlight is clear and they don't blur together.

**Acceptance criteria**
- **No rings:** `.weekly-summary-winner` and `.weekly-summary-mvp` draw no border, outline or ring.
- **Winner:** the winning team name is `--mark-winner`, bold, under its existing "Winner" label.
- **MVP:** the MVP is a `--mark-mvp` "MVP" label before the player name, on its own line.
- **My roster:** the MVP chip in My roster game rows uses `--mark-mvp`, matching the results.
- **Static elements:** images (avatars, team logos, hero icons, roster thumbnails) and controls in the Weekly Report follow the selection rule. Thumbnails still open the card viewer and keep their focus outline.
- **Game rows:** each My roster game row (`.weekly-summary-game`) follows the data-row rule:
  - a grid of date | opponent | game | result | MVP | points;
  - columns line up across rows and cards;
  - MVP rows are no taller than other rows;
  - a long opponent name wraps inside its column.

  The player name and total in each card header share a baseline.
- **Images site-wide:** the selection rule is also applied to `img` in the shared base styles. Card art keeps its hover lift.

### Reopening the Weekly Report Doesn't Flash
**User story**
As a player, I want the Weekly Report to open instantly and stay still when its data is already loaded, so that it doesn't flicker.

**Acceptance criteria**
- **Cache lifetime:** `_weeklySummaryCache` keeps each week's data, with its fetch time, for the page session. Closing the popup no longer clears it.
- **Clearing it:** on reveal, on logout or user switch (`_clearLocalAuthState()` for logout and an expired session, and `login()`), and when the week list's signature changes.
- **Reopening:** a cached week renders immediately with no `is-loading` dim. It is fetched again only when its data is more than 60 s old. A quiet refresh re-renders only if the HTML changed (`renderIfChanged`), and never replays the recap.
- **Week list:** reopening reuses a week list less than 60 s old. Otherwise it fetches the list once.
- **Same tab:** clicking the active week tab does nothing.
- **Recap:** a week's recap plays at most once per page visit. One interrupted by a week switch or by closing the popup does not play again on reopening (the week is cached); the **Replay** button plays it.
- **"Seen":** `POST /weekly-summary/seen` is sent only when the week list reported `has_unseen: true`.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `.claude/skills/README.md` | New "States and emphasis" section |
| `.claude/commands/ui-design.md` | One core-rule line pointing to it |
| `frontend/colors_and_type.css`, `design/colors_and_type.css` | Semantic state, badge, self and mark tokens, identical in both copies |
| `frontend/style.css` | "Shared states" section: the selected + hover selector list, `.role-badge` and its variants, `.status-badge`, `.row-self`, the mark classes, selection rules, the data-row grid. The per-surface duplicates it replaces are removed. |
| `frontend/app-globals.js` | `adminBadgeHtml` → `.role-badge`; new `tagBadgeHtml(tag, opts)` and `statusBadgeHtml(label, title)` with the reason map |
| `frontend/app-leaderboard.js` | `_lbStandingsRow` and `loadPastSeasonStandings`: classes, `row-self`, the badge helpers, no hex colours |
| `frontend/app-profile.js`, `frontend/app-admin-users.js` | Use the badge helpers |
| `frontend/app-players.js` (Schedule tags) | Unchanged markup; `.league-week-tag` / `.live-tag` take the shared status-badge rule |
| `frontend/app-weekly-summary.js` | Weekly Report marks, image attributes, game-row grid, cache |
| `frontend/app-auth.js` | Clear the Weekly Report cache on logout, expired session and sign-in |
| `frontend/app-roster.js` | Week status colour from tokens |
| `markdown/ui_description/*.md` (leaderboards, weekly-report, profile, schedule, admin) | Point to the design rules instead of describing one-off styles |
| `backend/tests/test_issue_202_ui_feedback_polish.py` | Static rule checks and a Node harness for the cache |

### Step 1 — Write the rules
Add the README section and the `/ui-design` line, and add the tokens to both CSS copies.

### Step 2 — Shared CSS
Add the "Shared states" section. Point each selected control's selector at it, and delete the duplicated per-surface badge and highlight styles.

### Step 3 — Apply in JS
- **Helpers:** the badge helpers go in `app-globals.js`.
- **Callers:** replace every inline-styled badge and the self row in the leaderboard, Profile, User Management and Schedule.
- **Weekly Report:** markup for the marks, and `draggable="false"` on images.

### Step 4 — Weekly Report cache
- **Cache entries:** `{data, at}`, plus a fetch time for the week list.
- **`closeWeeklySummary`:** keeps the cache.
- **`selectWeeklySummaryTab`:** returns early for the active tab, and skips the dim and the fetch for fresh cached data.
- **Invalidation:** logout and user switch clear the cache (`clearWeeklySummaryCache()` from `_clearLocalAuthState()` and `login()`).

### Step 5 — Tests and docs
**Tests (static):**
- **Design system:** the README has the "States and emphasis" section, every new token exists in both CSS copies, and the copies are equal (existing test).
- **Selected controls:** each of the seven has a selected + hover rule through the shared selector.
- **No inline styles or hex:**
  - no `style="` in badge markup or in `_lbStandingsRow`;
  - no hex colours in `app-leaderboard.js`;
  - no hex colours in the new `style.css` rules.
- **Brand rules:**
  - no left-border accent on `.row-self`;
  - role badge tokens resolve to flame, amber or neutral colours (no rarity tokens);
  - winner and MVP have no border or outline;
  - `img` has `user-select: none`.
- **Rows and placement:** the game row is a grid, and the shared section sits before GUIDED TOUR.

**Tests (Node harness for the cache):**
- closing keeps the cache;
- a fresh week doesn't fetch, and a stale one refreshes without `is-loading`;
- the active tab is a no-op;
- reveal and logout clear the cache;
- "seen" is posted only when unseen.

**Docs:** UI descriptions point to the design rules.

## Verification
- **Selected controls:** hover each selected tab, chip and toggle (main tabs, Weekly Report weeks, How to Play, Admin, Schedule chips, hide toggle); all invert. Keyboard focus shows the same style.
- **Badges:**
  - ADMIN, Caster and Season Winner look alike in shape and type, each in its own colour, with hover reasons, on standings, Profile, the Weekly Report and User Management;
  - LIVE, league week, TESTER and the link badges are neutral;
  - nothing uses blue or purple outside cards.
- **Self row:** your row is tinted across its full width in both standings, with no left bar.
- **Weekly Report:**
  - no rings; the winner and MVP are visibly different;
  - images and controls don't get selected when dragging;
  - My roster columns line up.
- **Caching:** reopen the report within a minute; there is no dim, no flicker and no repeated fetches.
- **Phone width:** every changed surface works with no horizontal scroll.
- **Design copies:** `design/colors_and_type.css` still equals the frontend copy.
