# Admin Tab Navigation and MVP Match View

Admin-only feature that restructures the admin panel into a tab-based layout and adds a Matches
tab where admins can view all ingested matches and set the MVP for any match without requiring
a Twitch broadcaster session.

---

## Tab Navigation

The admin panel is divided into five tabs:

| Tab | Contents |
|---|---|
| **User Management** | User list, token grants, tester flag toggle — default tab |
| **Week Management** | Week CRUD (create, edit, delete unlocked weeks) |
| **Player Management** | Player management (add, bulk-add, remove with refund) |
| **Matches** | Ingested match table with MVP selection |
| **Audit Log** | Chronological audit log of all admin and user actions |
| **Settings** | League monitoring, Token Grant Events, Notifications, Promo Codes, Scoring Weights, User Tags, Token Balances |

Tab state is stored in `sessionStorage` so the last-selected tab is restored when the user
navigates away and returns.

---

## Matches Tab

### `GET /admin/matches`

Returns all ingested matches ordered by start time descending. Admin-only.

```json
[
  {
    "match_id": 123456789,
    "league_id": 19369,
    "radiant_team_id": 1234,
    "dire_team_id": 5678,
    "team1": "Team Alpha",
    "team2": "Team Beta",
    "start_time": 1700000000,
    "mvp_player_name": "SomePlayer",
    "mvp_player_id": 42,
    "vod_url": null
  }
]
```

`team1` and `team2` are resolved from the `teams` table by `radiant_team_id`/`dire_team_id` — `null` if the team is not in the local DB. `mvp_player_name` and `mvp_player_id` are `null` when no MVP has been set. `vod_url` is `null` until an admin sets one via `PATCH /admin/matches/{match_id}/vod` (see below) — it is also surfaced to every user in the Weekly Report, see `core/weekly-summary.md`.

Note: `Match.duration` exists on the model (added by `reference/schedule-series-game-breakdown.md`,
migration `022_matches_duration`) but this endpoint's response does not include it. `series_id`
still does not exist as a column anywhere on `Match`. Neither field is available here.

### `GET /admin/matches/{match_id}/players`

Returns the players who participated in the specified match, sourced from
`player_match_stats`, with each player's team for that match. Admin-only.

```json
[{"id": 42, "name": "SomePlayer", "team_id": 100, "team_name": "SomeTeam"}, ...]
```

`team_id`/`team_name` are `null` if the player's `player_match_stats.team_id` didn't resolve to
an ingested team. The Set MVP modal (`#mvpPlayerList`, a 2-column grid) uses these to split
players into a left column (team 1) and right column (team 2); if the match's players don't
resolve to exactly two distinct teams, the modal falls back to one flat list spanning both
columns instead of guessing a split.

### `POST /admin/matches/{match_id}/mvp`

Sets or updates the MVP for a match. Admin-only alternative to the Twitch broadcaster flow.
Writes to the same `twitch_mvp` table and calls the same `_apply_mvp_bonus()` helper
(`backend/twitch.py`) `POST /twitch/mvp` uses — clearing the bonus and `is_mvp` flag from the
previous MVP if the match already had one and a different player is now selected, then applying
both to the new player's `player_match_stats` row. This is what makes the admin-set MVP show up
correctly in `mvp_count` (`GET /players`), match history's MVP column (`GET /players/{id}`), and
the Schedule tab's per-game MVP link (`GET /schedule`) — all of which read `is_mvp` directly, not
the `twitch_mvp` table. No token drop or Twitch PubSub/chat announcement fires from this path —
those are viewer-engagement mechanics specific to the Twitch extension.

```json
{ "player_id": 42 }
```

Returns `{ match_id, player_id, player_name }`.
Logged as `admin_set_mvp`.

### `PATCH /admin/matches/{match_id}/vod`

Sets, edits, or clears a match's caster VOD link, shown next to that match in every user's
Weekly Report (`core/weekly-summary.md`) — including weeks whose summary was generated before
the link was added, since report content is computed live rather than snapshotted.

```json
{ "vod_url": "https://youtube.com/watch?v=..." }
```

`vod_url: null` clears the link. A non-null value must start with `http://` or `https://`, or
the request is rejected with 422. Returns `{ match_id, vod_url }`. Logged as
`admin_match_vod_set`.

---

## Audit Log Entry

| Action | Trigger |
|---|---|
| `admin_set_mvp` | Admin set MVP for a match via the Matches tab |
| `admin_match_vod_set` | Admin set/edited/cleared a match's VOD link via the Matches tab |

