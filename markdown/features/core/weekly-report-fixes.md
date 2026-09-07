# Weekly Report Fixes

Four corrections to the Weekly Summary Report popup (`core/weekly-summary.md`): a docked
reveal control, a single reveal-all action, spoiler-safe winner hiding before reveal, and a
visible match date.

*(see `markdown/plans/plan-issue-100-weekly-report-fixes.md`, resolves GitHub issue #100)*

---

## Relationship to the Weekly Summary Report

This does not change the underlying feature described in `core/weekly-summary.md` —
availability (`Week.end_time`), live computation of report content, and per-user/per-week
reveal storage (`WeeklySummaryReveal`) are all unchanged. It corrects how reveal is triggered
and what is shown before that reveal happens.

## Fixes

### Docked reveal control
The "Reveal results" control lives in `#weeklySummaryRevealFooter`, a sibling element rendered
after `#weeklySummaryContent` in `frontend/index.html` — outside the scrollable
(`max-height:60vh; overflow-y:auto`) match list. It therefore stays visible regardless of
scroll position or match count. `_updateWeeklySummaryRevealFooter()` in
`frontend/app-weekly-summary.js` toggles the `hidden` class on it: shown whenever any week in
`_weeklySummaryWeeks` has `revealed === false`, hidden once every listed week is revealed. It
is re-evaluated from `renderWeeklySummaryTabs()` and after a reveal-all completes.

### Reveal all at once
`revealAllWeeklySummaries()` posts to `POST /weekly-summary/reveal-all`, then marks every entry
in `_weeklySummaryWeeks` as revealed, hides the footer, and re-renders the active tab so its
content updates immediately. Switching to any other previously-unrevealed tab then also shows
it revealed. A week that gets a `WeeklySummary` row later (via the `generate_weekly_summaries`
background pass) is untouched by past calls and starts unrevealed. The old per-tab
`revealWeeklySummary(weekId)` / inline `POST /weekly-summary/{week_id}/reveal` button is
removed from the frontend (the `{week_id}/reveal` endpoint itself is retained).

### Hide winner until revealed
`_build_week_summary` in `backend/routers/weekly_summary.py` sets
`match["winner_team_id"] = winner_team_id if revealed else None`. Before reveal every match
reports `winner_team_id: null`, matching the existing gating on player/MVP/points data. The
frontend's `winnerRadiant` / `winnerDire` flags in `_weeklySummaryMatchHtml` derive directly
from `m.winner_team_id`, so a `null` value naturally suppresses the "Winner" label and
highlight class — no separate frontend flag needed. This applies to both
`GET /weekly-summary/{week_id}` and the `POST /weekly-summary/{week_id}/reveal` response.

### Match date shown
`_weeklySummaryMatchHtml` formats `m.start_time` (unix seconds) with
`new Date(m.start_time * 1000).toLocaleDateString("fi-FI", {day:"numeric", month:"numeric", year:"2-digit"})`
— the same convention as the player-profile match history — and renders it in a
`.weekly-summary-match-date` span inside `.weekly-summary-match-vs-cell`, next to the VOD link.
It is emitted unconditionally, before the `revealed`-only players block, so it shows both
before and after reveal.

## Endpoints

### `POST /weekly-summary/reveal-all`
Auth required (`Depends(get_current_user)`). Inserts a `WeeklySummaryReveal` row
(`week_id`, `user_id`, `revealed_at`) for every `WeeklySummary` week the current user has not
already revealed. Idempotent — already-revealed weeks are skipped (no duplicate row, no
`revealed_at` overwrite). Returns `{"revealed_week_ids": [...]}` (all currently-available week
ids). Defined in `backend/routers/weekly_summary.py` as `reveal_all_weekly_summaries`.

### `GET /weekly-summary/{week_id}` — changed
Existing endpoint (`core/weekly-summary.md`); `winner_team_id` is now `null` when the caller
has not revealed that week, instead of always being populated.
