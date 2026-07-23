# Admin Tab Navigation and MVP Match View

Admin-only feature that restructures the admin panel into a tab-based layout and adds a Matches
tab where admins can view all ingested matches and set the MVP for any match without requiring
a Twitch broadcaster session.

---

## Tab Navigation

The admin panel is divided into five tabs:

| Tab | Contents |
|---|---|
| **Week Management** | Week CRUD (create, edit, delete unlocked weeks) |
| **Player Pool** | Player pool management (add, bulk-add, remove with refund) |
| **Audit Log** | Chronological audit log of all admin and user actions |
| **Settings** | League monitoring, Token Grant Events, Notifications, Promo Codes, Scoring Weights, User Tags, Token Balances |
| **Matches** | Ingested match table with MVP selection |

User management (grant tokens, tester toggle) remains in a persistent top section above the tab bar, always visible.

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
    "mvp_player_id": 42
  }
]
```

`team1` and `team2` are resolved from the `teams` table by `radiant_team_id`/`dire_team_id` — `null` if the team is not in the local DB. `mvp_player_name` and `mvp_player_id` are `null` when no MVP has been set.

Note: the `Match` model does not store `duration` or `series_id` — those fields are not available in this endpoint.

### `GET /admin/matches/{match_id}/players`

Returns the players who participated in the specified match, sourced from
`player_match_stats`. Admin-only.

```json
[{"id": 42, "name": "SomePlayer"}, ...]
```

### `POST /admin/matches/{match_id}/mvp`

Sets or updates the MVP for a match. Admin-only alternative to the Twitch broadcaster flow.
Writes to the same `twitch_mvp` table, so fantasy bonuses apply correctly regardless of
which path was used.

```json
{ "player_id": 42 }
```

Returns `{ match_id, player_id, player_name }`.
Logged as `admin_set_mvp`.

---

## Audit Log Entry

| Action | Trigger |
|---|---|
| `admin_set_mvp` | Admin set MVP for a match via the Matches tab |

