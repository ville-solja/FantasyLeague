# Plan: MVP Visibility Across Players, Profile, and Schedule

## Context
GitHub issue #92 asks for the Twitch-broadcaster-assigned match MVP (`PlayerMatchStats.is_mvp`,
already the authoritative flag set by `_apply_mvp_bonus()` in `backend/twitch.py` on
`POST /twitch/mvp`, and already scored via `reference/mvp-fantasy-bonus.md`) to be surfaced in
three places it currently isn't visible at all:

1. **Players tab** — a count of how many matches each player has been named MVP in.
2. **Player detail modal's match history table** — three additions: an MVP star as the very
   first column (currently the badge is a small inline marker appended after the Fantasy pts
   cell, easy to miss when scanning); a new "Opponent" column (the match history currently shows
   only the player's own team for that match, never who they played against); and an OpenDota
   match link as the final column (an external link already exists in the Schedule tab's game
   rows, but not here).
3. **Schedule tab game rows** — the match's MVP player, rendered as a link (matching the
   existing in-app `playerLink()` pattern used everywhere else player names are clickable),
   positioned immediately before the match duration.

None of this requires new data — `is_mvp` is already stored per `player_match_stats` row and
already joined into `GET /players/{player_id}`'s `match_history`. The "opponent team" is
derivable from `Match.radiant_team_id`/`dire_team_id` versus the player's own
`player_match_stats.team_id` for that match (both share the same OpenDota team-ID space —
`Team.id` **is** the OpenDota team_id, confirmed in `backend/ingest.py`), so no new column or
migration is needed anywhere in this plan.

Because `markdown/features/core/players.md` and `markdown/features/reference/schedule-series-game-breakdown.md`
already document the exact endpoints and response shapes this plan extends, both are **updated
in place** rather than duplicated into new stub files, per the project's "do not duplicate
documentation" rule.

Resolves GitHub issue #92.

## User Stories

### MVP Count on the Players Tab
**User story**
As a user browsing the Players tab, I want to see how many times each player has been named
match MVP so that I can spot standout performers at a glance.

**Acceptance criteria**
- `GET /players` includes an `mvp_count` field per player: the count of that player's
  `player_match_stats` rows where `is_mvp` is true
- The Players tab table shows a new "MVPs" column, sortable like the existing columns
- Players who have never been MVP show `0`, not a blank cell

---

### Match History Shows MVP, Opponent, and an OpenDota Link
**User story**
As a user viewing a player's match history in the detail modal, I want to immediately see which
matches they were MVP in, who they played against, and a way to jump to the match on OpenDota,
so that I don't have to cross-reference other tabs or an external site to get that context.

**Acceptance criteria**
- `GET /players/{player_id}`'s `match_history` rows each include `opponent_team_id` and
  `opponent_team_name`, resolved from whichever of the match's `radiant_team_id`/`dire_team_id`
  is not the player's own `team_id` for that match
- The match history table's first column is a dedicated MVP indicator (star), populated only
  for rows where `is_mvp` is true — not appended after another column as a small inline badge
  the way it is today
- An "Opponent" column shows the resolved opponent team name (linking to the team detail modal
  when `opponent_team_id` is available, matching how team names link elsewhere in the app)
- The last column is a link to the match on OpenDota (`https://www.opendota.com/matches/{match_id}`),
  opening in a new tab

---

### Schedule Tab Shows Match MVP
**User story**
As a user browsing the Schedule tab's expanded game rows, I want to see who was MVP for each
individual game so that I don't have to open the match on OpenDota or check Twitch to find out.

**Acceptance criteria**
- `GET /schedule`'s per-game entries (`_build_games()` in `backend/schedule.py`) include
  `mvp_player_id` and `mvp_player_name`, `null` when no MVP has been set for that match
  (matches without an `is_mvp=true` row in `player_match_stats`)
- Each game row shows the MVP player's name as a clickable link (the existing `playerLink()`
  pattern — opens the player detail modal), positioned immediately before the game's duration
- Games with no MVP set show no MVP link in that position — the row layout doesn't shift or
  leave a visibly broken gap

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/players.py` | `list_players()`: add an `mvp_count` aggregate to the `GET /players` query. `get_player()`: extend the `match_history` query to resolve `opponent_team_id`/`opponent_team_name` |
| `backend/schedule.py` | `_build_games()`: add an MVP lookup per `match_id` (join `player_match_stats.is_mvp = 1` to `players`), attach `mvp_player_id`/`mvp_player_name` to each game entry |
| `frontend/index.html` | Players tab table: add an "MVPs" `<th data-col="mvp_count">`. Player detail modal's match history `<thead>`: add a leading MVP-star column and an "Opponent" column; colspan on the empty-state row updates accordingly |
| `frontend/app-players.js` | `renderPlayers()`: render `mvp_count` in the new column. `openPlayerModal()`'s match-history row builder: move the MVP indicator to the first `<td>`, add the Opponent `<td>` (via `teamLink()`), add a trailing OpenDota-link `<td>`. Schedule tab's `gameRowsHtml` builder: insert the MVP `playerLink()` before `.game-row-duration` when `g.mvp_player_id` is present |
| `markdown/features/core/players.md` | Update in place: `mvp_count` in the `GET /players` example, `opponent_team_id`/`opponent_team_name` in the `GET /players/{player_id}` match_history example |
| `markdown/features/reference/schedule-series-game-breakdown.md` | Update in place: document `mvp_player_id`/`mvp_player_name` on each game entry |
| `markdown/stories/leaderboard.md` | Append the three stories above under a new `## MVP Visibility` heading |

### Step 1 — MVP count on `GET /players`
Add to `list_players()`'s raw SQL:
```sql
COALESCE(SUM(CASE WHEN s.is_mvp THEN 1 ELSE 0 END), 0) as mvp_count
```
alongside the existing `matches`/`avg_points`/`total_points` aggregates (same `LEFT JOIN player_match_stats s` this query already has).

### Step 2 — Opponent team on match history
In `get_player()`'s `match_history` query, join `matches` (already joined for `start_time`) to
read `radiant_team_id`/`dire_team_id`, and resolve the opponent:
```sql
CASE WHEN s.team_id = m.radiant_team_id THEN m.dire_team_id ELSE m.radiant_team_id END AS opponent_team_id
```
then `LEFT JOIN teams ot ON ot.id = opponent_team_id` for `ot.name AS opponent_team_name`. Verify
against the real query text in `backend/routers/players.py` before editing — this plan describes
the derivation, not a verbatim drop-in replacement.

### Step 3 — MVP on schedule game rows
In `_build_games()`, add one more bulk query alongside the existing duration/kills/hero lookups:
```sql
SELECT s.match_id, s.player_id, p.name
FROM player_match_stats s
JOIN players p ON p.id = s.player_id
WHERE s.match_id IN :ids AND s.is_mvp = 1
```
Build a `mvp_by_match` dict and attach `mvp_player_id`/`mvp_player_name` (both `null` if absent)
to each game entry in the returned list.

### Step 4 — Frontend rendering
Players tab: add the MVPs column matching the existing sortable-header pattern already used for
`matches`/`avg_points`/`total_points`. Match history table: restructure the row template so the
MVP star is the first `<td>`, add an Opponent `<td>` using `teamLink(m.opponent_team_id, m.opponent_team_name)`
(falling back to plain text if `opponent_team_id` is null, matching the existing `teamLink()`
null-handling), and append a final `<td>` with the OpenDota link (`target="_blank" rel="noopener"`,
mirroring the existing schedule game-row link's attributes). Schedule tab: insert
`playerLink(g.mvp_player_id, g.mvp_player_name)` as the first child of `.game-row-meta`, before
`.game-row-duration`, only when `g.mvp_player_id` is present.

### Step 5 — Documentation
Update `core/players.md` and `reference/schedule-series-game-breakdown.md` in place with the new
fields. Append the three stories to `markdown/stories/leaderboard.md` under `## MVP Visibility`.

## Verification
- `GET /players` for a player with 2 recorded MVP matches out of 10 returns `"mvp_count": 2`;
  a player never named MVP returns `"mvp_count": 0`, not a missing key
- Players tab "MVPs" column sorts correctly ascending/descending like the other numeric columns
- Open a player's detail modal for a match where they were MVP: the star appears in the first
  column of that row, not appended after Fantasy pts
- The same modal shows an "Opponent" column with the correct team name for every row, and a
  working OpenDota link as the last column on every row
- Schedule tab: expand a series with a game that has an MVP set — the MVP name appears as a
  link immediately before the duration; a game with no MVP set shows no gap or broken layout
  in that position
- No migration needed — `is_mvp`, `team_id`, `radiant_team_id`/`dire_team_id` all already exist
