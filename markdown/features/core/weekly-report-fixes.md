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
after the two-column `.weekly-summary-columns` block in `frontend/index.html` — outside both
scrolling column bodies (`#weeklySummaryRoster`, `#weeklySummaryContent`; see the issue #151
section below). It therefore stays visible regardless of
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

### Roster panel, side-by-side layout and scrollbar (issue #151)
*(see `markdown/plans/plan-issue-151-weekly-report-aesthetics.md`, resolves GitHub issue #151;
mock: https://claude.ai/artifact/CSAhGz2DRr4RTGtHL5p4wp)*

UI details (elements, columns, states, copy): `markdown/ui_description/weekly-report.md`.

- **Layout** (`frontend/index.html`, `frontend/style.css`): `#weeklySummaryModal` holds
  `.modal.weekly-summary-modal.k-scroll` (`width: min(1280px, calc(100vw - 48px))`,
  `max-height: 85vh`, flex column; below 600 px `width: calc(100vw - 16px)` and
  `max-height: 92vh`). The modal carries `k-scroll` because it scrolls as a whole when stacked. The week tabs (`#weeklySummaryTabs`) are the only tabs. Below them,
  `.weekly-summary-columns` is a grid of `480px minmax(0, 1fr)` with two `<section>`s, each
  with a fixed `.weekly-summary-col-head` and a `div.k-scroll.weekly-summary-col-body`:
  `#weeklySummaryRoster` (My roster) and `#weeklySummaryContent` (Match results). Inline height
  and overflow styles are gone. `@media (max-width: 1100px)` stacks the columns (roster first),
  sets the bodies to `overflow: visible` and lets the modal scroll (`overflow-y: auto`), with the
  reveal footer sticky at the bottom.
- **Scrollbar:** `.k-scroll` is the shared thin scrollbar: `scrollbar-width: thin`, thumb
  `var(--border)` (`var(--fg-dim)` on hover), transparent track, `var(--r-xs)` corners,
  `scrollbar-gutter: stable` and `padding-right: var(--s-3)` (12 px). Tokens only. `.card-grid`
  (`#rosterActiveGrid`, `#benchGrid`) now carries `k-scroll` instead of its own scrollbar rules,
  with `scrollbar-gutter: auto` since it scrolls horizontally.
- **My roster column** (`_weeklySummaryRosterHtml`, `_weeklySummaryRosterCardHtml`,
  `_weeklySummaryGameHtml`, `_renderWeeklySummaryRosterHeader` in
  `frontend/app-weekly-summary.js`): rendered from the response's `roster` block
  (`core/weekly-summary.md`). Counted cards first, then a "Did not play" group of subbed-out
  cards. The thumbnail is a `<button>` wrapping `<img src=cardImageUrl(card_id)>`
  (`_cardImgFallback` on error); `_weeklySummaryShowCard` opens `showCard({...card, id: card_id},
  "{week_points} wk pts")`. Names use `playerLink` / `teamLink`; every other string goes through
  `_escHtml`.
- **Your cards in the results:** `_weeklySummaryPlayerHtml` adds `.weekly-summary-owned`
  (`var(--accent-ghost)` fill) and a "YOUR CARD" / "YOUR SUB" label when `p.card_points != null`,
  and shows `card_points` instead of match points. The MVP outline still applies.
- **Stacking:** `.reveal-overlay` is now `z-index: 350`, above `.modal-overlay` (300), so the
  card viewer opens on top of the report. `.reveal-overlay ~ .modal-overlay` (popups after
  `#revealModal` in the DOM, such as `#playerModal` and `#teamModal`) is 360, so a player link
  inside the card viewer still opens on top of it.
- **Recap popup:** `#weeklyRecapPrompt` (`.modal-overlay`, `role="dialog"`, `aria-modal`,
  `aria-labelledby="weeklyRecapPromptTitle"`). `checkWeeklySummaryHighlight()` calls
  `maybeShowWeeklyRecapPrompt(data)` after loading `GET /weekly-summary`; it returns without
  showing or marking anything unless `data.show_prompt` is true and no other `.modal-overlay` /
  `.reveal-overlay` is open, no tour is running (`_tour`) and `activeMustChangePassword` is
  false. "Open recap" (`openWeeklyRecapFromPrompt`) calls `openWeeklySummary(latest_week.week_id)`,
  which then posts `/weekly-summary/seen`. Close, the X, Esc (`data-close`) and the backdrop call
  `dismissWeeklyRecapPrompt()`, which hides it and posts `/weekly-summary/prompted`. Focus moves
  to "Open recap"; a keydown handler keeps Tab inside the popup.
- **Points breakdown and reveal (issue #152):** each counted card's tag row now reads RAW,
  the modifier chips (`.recap-chip`), then the status tag; the #151 rarity tag is gone (the
  rarity name sits at the thumbnail's foot, with a "+pct% +points" caption below it), and an
  MVP game's tag reads "MVP +points". The subbed-in card lost its `var(--accent-ghost)` tint
  and the "SUBBED IN" tag is now neutral (`var(--fg-muted)` on `var(--border)`), because orange
  now marks only the card being revealed. The reveal animation, Skip / Replay and the
  `breakdown` field are in `reference/weekly-recap-animations.md`.
- **API and model:** `GET /weekly-summary/{week_id}` gains `roster` and `card_points`;
  `GET /weekly-summary` gains `show_prompt` and `latest_week`; new
  `POST /weekly-summary/prompted`; `POST /weekly-summary/seen` also sets
  `last_prompted_week_id`. New column `weekly_summary_seen.last_prompted_week_id` (migration
  `030_weekly_summary_seen_last_prompted`). Details in `core/weekly-summary.md`.

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

### `POST /weekly-summary/prompted` — new (issue #151)
Auth required (`Depends(get_current_user)`). Marks the newest report week announced by the
recap popup (`WeeklySummarySeen.last_prompted_week_id`), creating the row if needed. Idempotent;
returns `{"ok": true}`. Defined as `mark_weekly_summary_prompted`.
