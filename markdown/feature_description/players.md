# Players & Teams

Read-only endpoints that expose the ingested players and teams with fantasy point aggregates and match history. All endpoints are public — no authentication required.

---

## Players

### `GET /players`

Returns all ingested players sorted by total fantasy points descending. Each entry reflects stats across all ingested matches for the season.

```json
[
  {
    "id": 123456789,
    "name": "SomePlayer",
    "avatar_url": "https://...",
    "team_name": "SomeTeam",
    "team_id": 42,
    "matches": 18,
    "avg_points": 28.4,
    "total_points": 511.2
  }
]
```

`team_name` and `team_id` are resolved from the player's most recent ingested match.

---

### `GET /players/{player_id}`

Returns full detail for a single player, including a complete per-match history sorted by most recent first.

```json
{
  "id": 123456789,
  "name": "SomePlayer",
  "avatar_url": "https://...",
  "team_name": "SomeTeam",
  "team_id": 42,
  "matches": 18,
  "avg_points": 28.4,
  "total_points": 511.2,
  "best_match": {
    "match_id": 8001,
    "fantasy_points": 52.1,
    "start_time": 1741560000
  },
  "match_history": [
    {
      "match_id": 8001,
      "start_time": 1741560000,
      "fantasy_points": 52.1,
      "kills": 12,
      "assists": 8,
      "deaths": 1,
      "gold_per_min": 720.0,
      "obs_placed": 2,
      "last_hits": 310,
      "denies": 10,
      "towers_killed": 1,
      "roshan_kills": 0,
      "teamfight_participation": 0.58,
      "camps_stacked": 3,
      "rune_pickups": 2,
      "firstblood_claimed": 0,
      "stuns": 38.2,
      "team_id": 42,
      "team_name": "SomeTeam"
    }
  ]
}
```

Note: additional columns may exist on `player_match_stats` in the database for display/context (e.g. `sen_placed`, `tower_damage`), but `GET /players/{player_id}` only returns the fields selected by the API (the scoring stat set + assists + observer wards + team metadata).

Returns 404 if the player has not been ingested.

---

## Teams

### `GET /teams`

Returns all ingested teams sorted by match count descending.

```json
[
  { "id": 42, "name": "SomeTeam", "matches": 18, "player_count": 5 }
]
```

---

### `GET /teams/{team_id}`

Returns a team's details and the roster of players who have appeared in a match for that team, ordered by total fantasy points.

```json
{
  "id": 42,
  "name": "SomeTeam",
  "matches": 18,
  "players": [
    {
      "id": 123456789,
      "name": "SomePlayer",
      "avatar_url": "https://...",
      "matches": 18,
      "avg_points": 28.4,
      "total_points": 511.2
    }
  ]
}
```

Returns 404 if the team has not been ingested.
