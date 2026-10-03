# Plan: Weekly Report: Roster Panel and Aesthetics

## Context
Issue #151 reported two problems in the Weekly Report popup. The browser's default white scrollbar clashes with the dark theme, and it sits directly against the right-hand team column. Review of the popup then raised a bigger one: the report is about results, but whether you owned a player is shown only by orange points text. At a glance it's hard to see what *your* cards scored.

The chosen design (mock: https://claude.ai/artifact/CSAhGz2DRr4RTGtHL5p4wp, frame "Side by side") is a wider popup. The **week tabs are the only tabs**. Below them, two columns sit side by side, each scrolling on its own under a fixed header:
- **My roster** (left): your counted cards for that week, plus any original roster cards that were replaced. Unused bench cards are not shown, since a bench can hold many cards. Each card has:
  - a card image thumbnail; clicking it opens the existing card viewer, which shows the modifiers,
  - the card's points for the week,
  - one row per game: opponent, win or loss, MVP, and the card's points for that game,
  - the substitution states (#129).
- **Match results** (right): the existing series and games view. Your players get a "YOUR CARD" tile showing your card's points for that game.

Player and team names are links that open the site's existing player and team popups, as everywhere else.

**What already exists:**
- `_build_roster_response(db, user_id, week_id)` in `backend/routers/cards.py` returns a locked week's roster:
  - counted (`active`) and `bench` cards,
  - `subbed_in`, `subbed_out` and `subbed_in_for`,
  - `modifiers`, the per-card week `total_points`, and `combined_value`,
  
  all from stored `card_match_points` (#141) and rounded with `display_points` (#149).
- Per-game card points are rows in `card_match_points` (`card_id`, `match_id`). Opponent and result come from `matches` (`radiant_team_id`, `dire_team_id`, `radiant_win`) and the player's `player_match_stats.team_id`. MVP comes from `player_match_stats.is_mvp`.
- `playerLink(id, name)` and `teamLink(id, name)` (`frontend/app-globals.js`) open `#playerModal` and `#teamModal`. Those are `.modal-overlay` elements (`z-index: 300`) placed after `#weeklySummaryModal` in `index.html`, so they already open on top of the report.
- `showCard(card, footer)` (`frontend/app-cards.js`) opens the card viewer `#revealModal` with the generated card image (`GET /cards/{id}/image`), which is the only place modifiers are shown (`core/cards.md`). But `.reveal-overlay` has `z-index: 200`, **below** `.modal-overlay` (300), so today it would open behind the report.

**Assumptions:**
- The Weekly Report exists only for weeks that have ended and are locked, so the roster panel always uses the locked-week branch of `_build_roster_response`, the same data My Team shows for that week.
- The roster panel's week total equals the user's `week_points` on the weekly leaderboard (`GET /leaderboard/weekly/{week_id}`), because both sum the same counted cards' stored points.
- The phone-width layout stacks the columns (roster first) in one scroll instead of using tabs. Week tabs stay the only tabs at every width.
- One new column, `weekly_summary_seen.last_prompted_week_id`, for the recap popup. It needs migration `030`, because it is a new column on an existing table.

Resolves GitHub issue #151.

## User Stories

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
  1. **The counted cards**, in the same order as My Team for that week. A bench card that was subbed in takes the slot of the card it replaced. It is marked with a "SUBBED IN" tag, a tinted card background (`var(--accent-ghost)`, not a left border) and the line "From your bench, for {name}, who did not play this week".
  2. **A "Did not play" group**, after the counted cards. It holds the original roster cards that were replaced, so it comes after the fifth counted card. It appears only when a substitution happened. The cards are greyed out with a dashed border and the line "No matches this week. Replaced by {name}", and their points don't count.
- Each card shows:
  - a card image thumbnail with the rarity border,
  - the player name as a player link and the team name as a team link,
  - a rarity tag,
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
- **When it appears:** after login or page load, a popup "Week {label} recap is ready" appears when the newest available report week has not been announced to the user yet. That means not opened and not shown as this popup before.
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

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/weekly_summary.py` | `_build_week_summary` adds a `roster` block (from `_build_roster_response`) with per-card `games`, and `card_points` on result players; nothing about points for unrevealed weeks |
| `backend/models.py` | `WeeklySummarySeen.last_prompted_week_id` (nullable `Integer`, FK `weeks.id`) |
| `backend/migrate.py` | Migration `030_weekly_summary_seen_last_prompted` adding the column, guarded by `PRAGMA table_info` |
| `backend/routers/cards.py` | `_build_roster_response` also returns `team_id` per card (from the existing latest-team subquery), needed for the team link |
| `frontend/index.html` | New `#weeklyRecapPrompt` dialog (`.modal-overlay`); `#weeklySummaryModal` restructured: wide modal class, two-column body (`#weeklySummaryRoster`, `#weeklySummaryContent`), each with a fixed header and a `.k-scroll` body; inline styles moved to classes |
| `frontend/app-weekly-summary.js` | `maybeShowWeeklyRecapPrompt()` after `checkWeeklySummaryHighlight()`; `_weeklySummaryRosterHtml(roster, revealed)` and its card and game rows; "YOUR CARD" tiles in `_weeklySummaryPlayerHtml`; thumbnail opens `showCard`; links via `playerLink` and `teamLink` |
| `frontend/style.css` | `.k-scroll`; `.weekly-summary-modal` and column layout with the 1100 px breakpoint; roster card, game row, status and thumbnail styles; `.weekly-summary-owned`; `.reveal-overlay` `z-index` above `.modal-overlay`; `.card-grid` uses `.k-scroll` |
| `markdown/features/core/weekly-summary.md`, `core/weekly-report-fixes.md`, `markdown/ui_description/` | Response shape, layout and states documented; a new `ui_description/weekly-report.md` for the popup |
| `backend/tests/test_issue_151_weekly_report_aesthetics.py` | API and static frontend tests |

### Step 1 — Backend: roster block
In `_build_week_summary(db, week, revealed, user_id)`:

```python
roster = _build_roster_response(db, user_id, week.id)   # locked-week branch
cards = roster["active"] + [c for c in roster["bench"] if c["subbed_out"]]
```

For every card, add `games`. Query the stored per-game points for those card ids in the week window, using the same `scored_match_sql()` and week-window conditions as the roster query. Excluded matches are included, with `points: None` and `scored: False`. Join `matches` and `player_match_stats` (on `player_id` and `match_id`) for:

```json
{"match_id": 1, "start_time": 1711180800, "game_number": 1,
 "opponent_team_id": 12, "opponent_name": "Kuura",
 "won": true, "is_mvp": true, "points": 31.2, "scored": true}
```

- `won` is `null` when `radiant_win` is unknown.
- `game_number` comes from the same series grouping as the results (`_group_into_series`).
- Points use `display_points`.

Return:

```json
"roster": {
  "week_total": 168.8,
  "cards": [{"card_id": 1, "card_type": "legendary", "player_id": 7, "player_name": "Varjo",
             "avatar_url": "...", "team_id": 3, "team_name": "Halla",
             "counted": true, "subbed_in": false, "subbed_out": false, "subbed_in_for": null,
             "modifiers": [], "week_points": 55.8, "games": []}]
}
```

`week_total` is `roster["combined_value"]`. `cards` holds `roster["active"]` plus only the `bench` entries with `subbed_out: true`, in `_build_roster_response`'s order. Unused bench cards are left out of the response.

When `revealed` is false, return the lock-time roster instead: the counted cards with any subbed-in card swapped back for the subbed-out card it replaced, in slot order, with `card_id`, `card_type`, the player and the team only. Leave out `week_total`, `week_points`, `games`, `counted` and the substitution fields.

For result players, add `card_points`: the sum of the user's counted cards' `card_match_points` for that player and match, and `null` when the player is not on the user's counted roster. `on_roster` stays for compatibility.

### Step 2 — Popup structure and scrolling
`index.html`:
- Give the modal a `weekly-summary-modal` class.
- Keep the tabs row.
- Add `<div class="weekly-summary-columns">` holding two `<section>` elements. Each has a header `div` and a `div class="k-scroll ...">` body: `#weeklySummaryRoster` and `#weeklySummaryContent`.
- Keep the reveal footer docked after the columns.
- Remove the inline height and overflow styles.

`style.css`:
- `.k-scroll`, as in the first story.
- `.weekly-summary-modal { width: min(1280px, calc(100vw - 48px)); max-height: 85vh; display: flex; flex-direction: column; }`
- `.weekly-summary-columns { display: grid; grid-template-columns: 480px minmax(0, 1fr); gap: 24px; min-height: 0; flex: 1; }`, with each column body set to `overflow-y: auto; min-height: 0`.
- `@media (max-width: 1100px)`: one column, bodies `overflow: visible`, and the modal scrolls instead.
- Move the `.card-grid` scrollbar rules to `.k-scroll`.

### Step 3 — Roster panel rendering
In `app-weekly-summary.js`, `_weeklySummaryRosterHtml(roster, revealed, substitutionsPending)` renders:
- the header total,
- the counted cards (a subbed-in card marked, in the replaced card's slot), then a "Did not play" group (subbed-out cards, only when there are any),
- each card: a thumbnail `<img src=cardImageUrl(card_id)>` inside a `<button>` that calls `showCard({...card, id: card_id}, `${week_points} wk pts`)`, `playerLink`, `teamLink`, the rarity and status tags, the week points, and the game rows.

Escape every string with `_escHtml`. The thumbnail uses `_cardImgFallback` on error, like My Team.

### Step 4 — Results tiles and stacking
- In `_weeklySummaryPlayerHtml`, when `p.card_points != null`, add `weekly-summary-owned` (filled tile) and a "YOUR CARD" label, and show `card_points`.
- In `style.css`, set `.reveal-overlay`'s `z-index` above `.modal-overlay` (for example 400). Check that the draw reveal and My Team card popup, opened with no other popup, behave as before.

### Step 5 — Tests and docs
`backend/tests/test_issue_151_weekly_report_aesthetics.py`, using the project's in-memory DB fixtures:
- **Revealed week:**
  - `roster.cards` order matches `_build_roster_response`,
  - `week_total` equals the weekly leaderboard `week_points` for the user,
  - each game's `points` equals the `card_match_points` row,
  - `won`, `is_mvp` and `opponent_team_id` are correct,
  - an excluded match gives `points: null, scored: false`.
- **Substitution:** a subbed-in bench card has `counted: true, subbed_in_for` set and sits in the replaced card's slot; the replaced card has `subbed_out: true` and comes after the counted cards.
- **Unused bench:** bench cards that weren't subbed in are not in `roster.cards`.
- **Results:** `card_points` is set only for the user's counted players.
- **Failure path:** an unrevealed week returns no `week_total`, `games` or statuses, and no `card_points` (the existing players block is already hidden).
- **Static checks:**
  - `.k-scroll` rules, with no hex colours,
  - the two-column markup with no inline overflow styles,
  - the 1100 px breakpoint,
  - `.reveal-overlay` `z-index` greater than `.modal-overlay`'s,
  - `app-weekly-summary.js` using `playerLink`, `teamLink`, `showCard` and `cardImageUrl`.

Bump the suite-size check in `test_issue_85_split_admin_router.py`. Update `core/weekly-summary.md` (response shape), `core/weekly-report-fixes.md`, the stories, and add `ui_description/weekly-report.md`.

### Step 6 — New recap popup
**Backend** (`backend/routers/weekly_summary.py`, `backend/models.py`, `backend/migrate.py`):
- Add `last_prompted_week_id` to `WeeklySummarySeen`, with migration `030_weekly_summary_seen_last_prompted`. Existing rows get `NULL`.
- `GET /weekly-summary` also returns:
  - `show_prompt`: true when the newest report week is neither `last_seen_week_id` nor `last_prompted_week_id`,
  - `latest_week`: `{"week_id", "label"}`.
- New `POST /weekly-summary/prompted` (auth required): sets `last_prompted_week_id` to the newest report week, creating the row if needed. It is idempotent and returns `{"ok": true}`.
- `POST /weekly-summary/seen` also sets `last_prompted_week_id`, so opening the report counts as announced.

**Frontend:**
- `#weeklyRecapPrompt` in `index.html`: `role="dialog"`, `aria-modal`, `aria-labelledby`, with eyebrow, title, text, "Open recap" and "Close" buttons, and an X.
- `maybeShowWeeklyRecapPrompt(data)` runs after `checkWeeklySummaryHighlight()` loads the list. It shows the popup only when all of these hold:
  - `data.show_prompt` is true,
  - no other `.modal-overlay` or `.reveal-overlay` is open,
  - no tour is running (`_tour`),
  - `activeMustChangePassword` is false.
- "Open recap" calls `openWeeklySummary()`, which selects `latest_week` and then marks it seen.
- "Close", the X, Esc and a backdrop click call `POST /weekly-summary/prompted`, then hide the popup.

**Tests:**
- `show_prompt` is true for a new week.
- After `/prompted`, `show_prompt` is false and `has_unseen` is still true.
- After `/seen`, both are false.
- A newer report week makes `show_prompt` true again.
- `/prompted` requires authentication.
- The migration adds the column on the legacy schema (`tests/test_migrate.py` coverage).
- Static checks: the dialog markup and the call order in `app-weekly-summary.js`.

## Verification
- Open a revealed week with a substitution in a desktop browser:
  - both columns scroll on their own and the headers stay put,
  - the week total matches the weekly leaderboard,
  - game rows match the player's games in the results column,
  - "YOUR CARD" tiles match the roster.
- Click a thumbnail: the card viewer opens on top with the modifiers. Close it: the report is unchanged.
- Click a player, a team and an opponent link in both columns: the existing popups open on top, and closing them returns to the report.
- Open an unrevealed week: only card identities are shown. Reveal, and points appear.
- Resize below 1100 px and to 375 px: the columns stack, roster first, with no horizontal scrolling.
- Draw a card on My Team and open a roster card there: the card viewer behaves as before.
- Log in with a new report week:
  - the popup appears once,
  - Close leaves the header dot, and a reload shows no popup,
  - opening from the header clears the dot.
- On a second browser, the popup does not appear for an announced week.
- When the next week's report arrives, the popup appears again.
- With the guided tour running, or a password change required, no popup appears.
- `cd backend && python3 -m pytest tests/ -q` passes.
