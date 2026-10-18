# Admin Enhancements

The Admin tab reorganised around its most frequent jobs: approving streamers, setting missing MVPs and adding players. Settings is grouped by purpose. Plan: `markdown/plans/plan-issue-214-admin-enhancements.md`. Design canvas: https://claude.ai/artifact/WPnstGBfP24mJeqHFtm6ih. Notifying admins outside the site is #215.

---

## What changed

- **Twitch sub-tab** (`data-admin-tab="twitch"`, after User Management): Approved streamers first (waiting approvals on top), then Twitch status, then Twitch collection merges. Superseded player id claims stays in User Management.
  - **Pending badge:** `#adminTwitchPendingBadge` on the sub-tab button and `#adminTabPendingBadge` on the top-level Admin tab show the number of channels waiting, with `aria-label` "N streamers waiting for approval"; hidden at zero or when the fetch fails.
  - The count comes from `GET /admin/twitch/channels` (`pending`). `refreshTwitchPendingBadge()` (`app-admin.js`) runs from `applyAuthState()` for an admin; `_renderTwitchChannels()` re-sets it whenever the list loads, which Approve and Reject trigger. Approve, Reject and Remove still need the password re-check.
- **Typed ids:** every OpenDota id input (Add player, Bulk add, Mark champions, Add accolade, End Season add-by-id, and Add league) is `type="text" inputmode="numeric"`. `idInputProblem()` rejects non-digits with "OpenDota ids are digits only" before any request. The accolade value is `inputmode="decimal"`.
  - **Add player:** blur or Enter calls the lookup and shows "Glete · not in the pool", "Glete · already in the pool" or "No OpenDota player with this id" in `#addPlayerPreview`. Confirm still posts `POST /admin/players` whatever the preview says.
  - **Bulk add:** ids split on commas, spaces or new lines (each once, at most 50). **Preview** lists each id with its name and status (new, already in pool, not found); **Add N players** posts only the new ids to `POST /admin/players/bulk`, and the existing progress panel runs. Editing the ids drops the preview, so Add never sends ids nobody saw; with no new ids the button is disabled.
- **Mark champions:** the paste box (`champPaste`, `champApplyPaste`) is gone; **+ Add player** stays. The modal is up to 720 px wide; a roster row is id (12ch), name (the rest, at least 12ch) and Remove, stacked below 640 px. Add accolade's bulk Played box stays (`_parsePlayerLines`).
- **Matches** (`app-admin-matches.js`):
  - **Series groups:** a header row per feed series ("Reds vs Blues · Div 1 · Week 4 · Stream ↗"), newest series first, its games in play order; matches outside the feed are under "Not in the schedule".
  - **Teams in feed order:** each game shows the series' team 1 vs team 2 (`series_team1_id` / `series_team2_id`), not radiant/dire.
  - **Columns:** Match (OpenDota link), Teams, League (name · Div), Start, MVP with **Set MVP**, Stream, Week, Scoring, Parse, Live seen, Stats in, MVP picked, More.
  - **Filters** (combined): MVP missing (checked on the first load when any match lacks an MVP), League (All, Div 1, Div 2) and Unparseable only. A count shows "N of M matches"; the empty state names the active filters.
  - **More** opens a details row with the admin VOD link editor (the Weekly Report VOD, `PATCH /admin/matches/{id}/vod`) and the exact timing times.
  - Scoring checkboxes sit in a two-column grid (`.admin-scoring-grid`).
- **Settings:** six sections (Season, Scoring, Tokens and rewards, Announcements, Players and tags, Maintenance) with a section nav, sticky on desktop and a chip row at phone width. Selecting a section scrolls to it and stores it in `localStorage` (`adminSettingsSection`, guarded by try/catch); opening Settings returns to it. Every panel has the shared header (`.admin-panel-head`: title, one-line description, actions). Season Lifecycle is last in Season with Reset Season at its bottom; Recalculate is danger-styled and last in Scoring. Every element id is unchanged.

## Endpoints

### `GET /admin/players/lookup?ids=1,2,3`
`routers/admin_players.py::lookup_players`, `require_admin`, global rate-limit baseline only (admin route, see `action-throttling.md`).

- **Input:** comma-separated ids, 1 to 50, each a positive integer up to 2**63−1. Anything else (missing, empty, non-digit, zero, too many, too large) answers 422 before OpenDota is called.
- **Output:** one entry per id in request order, `[{id, name, source, in_pool}]`:
  - an active pool player: its pool name, `source: "pool"`, `in_pool: true`, no OpenDota call;
  - otherwise the OpenDota `personaname`, `source: "opendota"`, `in_pool: false`;
  - no such OpenDota player (or OpenDota unreachable): `name: null`, `source: null`.
- **Cache:** OpenDota answers, including "no such player", are kept in process for 10 minutes (`_lookup_cache`, `clear_lookup_cache()` for tests). A failed call isn't cached, so the next lookup retries. Calls use the interactive retry settings that Add player uses.
- An inactive pool row is looked up on OpenDota and shows as new; bulk add then reports it as "already exists", as before.

### `GET /admin/matches` (extended)
Adds per match, from one `schedule.get_schedule(db)` pass (`_feed_series_by_match`):

| Field | Value |
|---|---|
| `series_key` | The feed series the match belongs to (`w<week>-<div>-<index>`), via `series_result.match_ids`; null outside the feed |
| `series_team1_id`, `series_team2_id` | The series' teams in feed order; null outside the feed |
| `division` | `div1` / `div2` from the series' division list, else `accolades.league_division(league name)`; null when the league is unknown |
| `league_name` | The `leagues` row's name, or null |
| `stream_url` | The series' stream link from the feed, or null |

If the schedule can't be read, the lookup logs the error and the series fields are null; the endpoint still answers. Existing fields are unchanged.

## Tests

`backend/tests/test_issue_214_admin_enhancements.py` (backend through a TestClient with OpenDota and the schedule feed mocked; frontend by source reading and Node harnesses).
