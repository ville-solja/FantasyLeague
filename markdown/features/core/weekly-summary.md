# Weekly Summary Report

A post-week recap popup, similar in spirit to the Battle Report popup in the Dota 2 client:
once a week's scoring window closes, users can open a "Weekly report" button to see that
week's matches, then choose to reveal the full player-level breakdown (MVPs, points earned)
at their own pace.

*(see `markdown/plans/plan-issue-51-weekly-summary.md`, resolves GitHub issue #51)*

---

## Availability, Not Generation

There is no scheduled-content generation step and no calendar cadence (the originating issue
proposed "every Monday at 06:00"; that was overridden — see the plan's Context section).
Instead, a week simply becomes **available** in the report once its own `end_time` has passed
— the same boundary `auto_lock_weeks()` already uses, including its post-midnight grace period
(see `reference/admin-week-management.md`). This is checked from the existing background
week-maintenance loop, so irregular weeks (e.g. a compressed finals week) are handled the same
way as regular ones, with no separate schedule to keep in sync.

Report content itself (matches, teams, players, points, MVP) is computed live from `Match`,
`PlayerMatchStats`, and `Team` at request time — the same way the weekly leaderboard and card
scoring already work — rather than being pre-generated and stored as a snapshot.

## Two-Stage Visibility

Each week's tab in the popup has two states, gated per user:

1. **Before reveal** — matches for the week, grouped by series (same two teams clustered
   together), team names and logos (winner highlighted), and a VOD link where one has been
   set. No player names, points, or MVP information.
2. **After reveal** — clicking "Reveal results" permanently unlocks, for that user and that
   week only: every player per match grouped under their team, the match's MVP player with a
   highlighted portrait, and a points-earned number per player. A player who was one of the
   viewing user's counted cards that week gets a filled YOUR CARD tile (YOUR SUB for a
   subbed-in card) showing the user's card points for that match, in the accent colour; other
   players show match points in a neutral colour. "Counted" means a roster entry after
   [bench substitution](../reference/automatic-bench-substitution.md): an active card not subbed
   out, or a subbed-in bench card. The roster itself is in the My roster column (below).

Bench substitutions run `SUBSTITUTION_DELAY_HOURS` (default 24) after the week ends, so the
report normally opens before they have run. Until then a revealed week shows a muted note in
the "My roster" column header: "Bench substitutions are made {N} hours after the week ends;
roster marks may change." The "on roster" marks update once substitutions have run.

## My Roster Column and Your Cards (issue #151)

The popup shows two columns under the week tabs: **My roster** (the user's cards for that week,
with per-game card points) and **Match results** (the series view above). Players the user had
as a counted card get a filled "YOUR CARD" tile ("YOUR SUB" for a subbed-in card) showing the
user's card points for that game. Before reveal the roster column lists only the lock-time
cards' identities. Layout, states and copy: `markdown/ui_description/weekly-report.md`; the
changes are summarised in `core/weekly-report-fixes.md`.

Since issue #152 each counted card also shows a points breakdown (RAW and modifier chips, a
rarity caption under the thumbnail, the MVP bonus on each MVP game's tag), revealed card by card
with an animation the first time a revealed week is shown in a browser. See
`reference/weekly-recap-animations.md`.

Reveal state does not affect other users or other weeks.

## Report Highlight

The "Weekly report" button carries a highlight/badge whenever a newer week's summary has
become available than the last one the current user opened the popup for. Opening the popup
(not revealing any particular week) clears it.

## Recap Popup (issue #151)

After login or page load, a small "Week {label} recap is ready" popup (`#weeklyRecapPrompt`)
announces the newest report week once per user, across devices. "Open recap" opens the report
on that week (marking it seen and announced); Close, the X, Esc or a backdrop click marks it
announced only, so the badge stays until the report is opened. The popup is skipped, without
marking anything, while another popup or the guided tour is open or a password change is
required. Tracked by `WeeklySummarySeen.last_prompted_week_id`. When the guided tour closes,
`endTour()` runs `checkWeeklySummaryHighlight()` again, so a recap held back by the tour
appears right away (issue #153; see `reference/guided-tour.md`).

## Series Grouping

Matches within a week are clustered into series with the same pair/gap rule
`backend/schedule.py` uses for the season-wide schedule view (`_group_into_series()` in
`backend/routers/weekly_summary.py`): consecutive matches between the same unordered team pair
belong to the same series as long as the gap to the previous match in that pair is ≤ 6 hours.

## Endpoints

### `GET /weekly-summary`
Auth required (`Depends(get_current_user)`). Lists weeks with a generated `WeeklySummary` row,
ordered most-recent-first:
```json
{
  "weeks": [{"week_id": 3, "label": "Week 3", "revealed": false}],
  "has_unseen": true,
  "show_prompt": true,
  "latest_week": {"week_id": 3, "label": "Week 3"}
}
```
`has_unseen` compares the latest available week against the caller's `WeeklySummarySeen.last_seen_week_id`.
`show_prompt` is true when the latest available week is neither `last_seen_week_id` nor
`last_prompted_week_id` (issue #151). `latest_week` is the newest report week, or `null` when
no week is available.

### `GET /weekly-summary/{week_id}`
Auth required. 404 if no `WeeklySummary` row exists for the week yet. Returns matches (grouped
into `series`) with team names/logos/winner/VOD link always included; each match additionally
carries a `players` list (`player_id`, `name`, `avatar_url`, `team_id`, `points`, `is_mvp`,
`on_roster`) only if the caller has revealed that week. Each match also carries
`excluded_from_scoring`. On an excluded match, every player's `points` is `null` (see
`reference/unparseable-match-handling.md`). `on_roster` uses `counted_roster_entry_sql()`, so it
reflects bench substitution. The response also carries `substitutions_pending` (true while the
week's `substitutions_at` is null), `substitutions_at` (unix seconds or null) and
`substitution_delay_hours`.

Issue #151 adds:

- **`card_points`** on every revealed result player: `display_points` of the summed
  `card_match_points` of the caller's counted cards for that player and match, or `null` when
  the player is not on the caller's counted roster that week (and on a match excluded from
  scoring). `on_roster` stays for compatibility.
- **`roster`**, the "My roster" column, built from the locked-week branch of
  `routers.cards._build_roster_response` (which now also returns `team_id` per card). A card's
  `team_id` / `team_name` are the player's most recent team (as in `GET /roster`), not
  necessarily their team that week, and `week_points` is `_build_roster_response`'s
  `total_points`. Revealed:

  ```json
  "roster": {
    "week_total": 168.8,
    "cards": [{"card_id": 1, "card_type": "legendary", "player_id": 7, "player_name": "Varjo",
               "avatar_url": "...", "team_id": 3, "team_name": "Halla",
               "counted": true, "subbed_in": false, "subbed_out": false, "subbed_in_for": null,
               "modifiers": [], "week_points": 55.8,
               "games": [{"match_id": 1, "start_time": 1711180800, "game_number": 1,
                          "opponent_team_id": 12, "opponent_name": "Kuura",
                          "won": true, "is_mvp": true, "points": 31.2, "scored": true}],
               "breakdown": {"raw": 50.0, "steps": [
                 {"kind": "rarity", "label": "Legendary", "pct": 3.0, "points": 1.5},
                 {"kind": "mvp", "label": "MVP", "pct": 10.0, "points": 4.3, "match_id": 1}]}}]
  }
  ```

  `cards` holds the roster's `active` cards in My Team order (a subbed-in card in the slot of
  the card it replaced), then only the `bench` entries with `subbed_out: true`; unused bench
  cards are left out. `week_total` is `combined_value`, so it equals the caller's `week_points`
  on the weekly leaderboard. `games` has one row per match the card's player played in the
  week window: `points` is the stored `card_match_points` row through `display_points`;
  an excluded match has `points: null, scored: false`; `won` is `null` when `radiant_win` is
  unknown; `game_number` is the match's position in its series (`_group_into_series`).
  `breakdown` (issue #152, counted cards only) splits `week_points` into `raw` and ordered
  `steps` (rarity when above 0, one per modifier, one MVP step per MVP game with its
  `match_id`); the rounded values add up to `week_points` exactly. Details:
  `reference/weekly-recap-animations.md`.

  Unrevealed: `{"cards": [...]}` with the lock-time roster (each subbed-in card swapped back
  for the card it replaced, in slot order) and only `card_id`, `card_type`, `player_id`,
  `player_name`, `avatar_url`, `team_id`, `team_name` per card; no `week_total`, points, games
  breakdown or substitution fields. A week that is not locked returns an empty `cards` list (plus
  `week_total: 0.0` when revealed).

### `POST /weekly-summary/{week_id}/reveal`
Auth required. Idempotently inserts a `WeeklySummaryReveal` row for `(week_id, current user)`,
then returns the same content `GET /weekly-summary/{week_id}` would return afterward.

### `POST /weekly-summary/seen`
Auth required. Upserts `WeeklySummarySeen.last_seen_week_id` (and, since issue #151,
`last_prompted_week_id`) to the current latest available week, clearing the highlight badge and
the recap popup on the caller's next `GET /weekly-summary`.

### `POST /weekly-summary/prompted`
Auth required (`Depends(get_current_user)`; 401 without a session). Issue #151: sets
`WeeklySummarySeen.last_prompted_week_id` to the current latest available week, creating the
row if needed (`last_seen_week_id` stays as it was). Idempotent; returns `{"ok": true}`. Called
when the recap popup is closed without opening the report.

### `PATCH /admin/matches/{match_id}/vod`
Admin required (`Depends(require_admin)`). Body `{"vod_url": "https://..." | null}`; rejects
non-`http(s)` values with 422, 404 if the match doesn't exist. Also surfaced as a `vod_url`
field on `GET /admin/matches`.

## Generation

`weeks.generate_weekly_summaries(db)` runs from the same background loop as `auto_lock_weeks`
(`_week_maintenance_loop` in `backend/main.py`, interval `WEEK_CHECK_INTERVAL`). It inserts a
`WeeklySummary(week_id, generated_at)` row for every `Week` whose `end_time` has passed and has
no row yet — idempotent, and with no dependency on calendar day/time.

## Models

`Match.vod_url` (nullable string), `WeeklySummary` (`week_id` PK, `generated_at` — availability
marker only, no denormalised content), `WeeklySummaryReveal` (`week_id`, `user_id`,
`revealed_at`; unique per week/user), `WeeklySummarySeen` (`user_id` PK, `last_seen_week_id`,
`last_prompted_week_id` — nullable FK to `weeks.id`, added by migration
`030_weekly_summary_seen_last_prompted`; existing rows get `NULL`).

---

*Implemented via `markdown/plans/plan-issue-51-weekly-summary.md`.*
