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
    "total_points": 511.2,
    "mvp_count": 2
  }
]
```

`team_name` and `team_id` are resolved from the player's most recent ingested match. `mvp_count`
is the number of that player's `player_match_stats` rows with `is_mvp = true` — the same flag
`POST /twitch/mvp` sets (see `core/twitch-extension.md`) — and is `0`, not omitted, for players
never named MVP. `matches` counts every match. `avg_points` and `total_points` skip matches an
admin excluded from scoring (see `reference/unparseable-match-handling.md`).

---

### `GET /players/{player_id}`

Returns full detail for a single player, including a complete per-match history sorted by most recent first.

```json
{
  "id": 123456789,
  "name": "SomePlayer",
  "avatar_url": "https://...",
  "rank_tier": 54,
  "leaderboard_rank": null,
  "rank_fetched_at": 1760000000,
  "team_name": "SomeTeam",
  "team_id": 42,
  "matches": 18,
  "avg_points": 28.4,
  "total_points": 511.2,
  "best_match": {
    "match_id": 8001,
    "fantasy_points": 52.1,
    "start_time": 1741560000,
    "opponent_team_name": "OtherTeam"
  },
  "match_history": [
    {
      "match_id": 8001,
      "start_time": 1741560000,
      "fantasy_points": 52.1,
      "kills": 12, "assists": 8, "deaths": 1,
      "gold_per_min": 720.0,
      "obs_placed": 0,
      "last_hits": 260,
      "denies": 10,
      "towers_killed": 1,
      "roshan_kills": 0,
      "teamfight_participation": 0.6,
      "camps_stacked": 2,
      "rune_pickups": 4,
      "firstblood_claimed": 0,
      "stuns": 10.0,
      "is_mvp": false,
      "parse_status": "parsed",
      "excluded_from_scoring": false,
      "team_id": 42, "team_name": "SomeTeam",
      "opponent_team_id": 99, "opponent_team_name": "OtherTeam",
      "sen_placed": 1, "tower_damage": 3100, "duration": 2140,
      "hero_id": 14, "hero_name": "Pudge", "hero_icon_url": "https://cdn.cloudflare.steamstatic.com/...",
      "won": true,
      "week_label": "W3",
      "points_breakdown": {"kills": 3.6, "assists": 2.4, "farm": 0.9, "gpm": 3.6, "vision": 0.0,
                           "objectives": 1.0, "teamfight": 1.8, "stuns": 0.5, "jungle_runes": 1.4,
                           "first_blood": 0.0, "survival": 2.7, "mvp_bonus": 0.0}
    }
  ],
  "summary": {"wins": 11, "losses": 7, "mvps": 3, "avg_rank": {"rank": 7, "of": 84}},
  "league_avg_points": 21.3,
  "points_sources": [
    {"key": "kills", "label": "Kills", "avg": 4.2, "share": 14.8, "league_avg": 3.1}
  ],
  "modifier_values": {"bonus_pct": 10.0, "stats": [
    {"stat": "gold_per_min", "label": "GPM", "base": 4.32, "value": 0.43}
  ]},
  "league_comparison": {"population": 84, "stats": {
    "kills": {"label": "Kills", "value": 6.2, "percentile": 85, "median": 5.1, "lower_is_better": false},
    "deaths": {"label": "Deaths", "value": 3.0, "percentile": 80, "median": 4.4, "lower_is_better": true}
  }},
  "heroes": [
    {"hero_id": 14, "hero_name": "Pudge", "icon_url": "https://...", "games": 5, "wins": 3, "losses": 2, "avg_points": 27.9}
  ],
  "seasons_played": 3, "seasons": ["Season 16", "Season 15", "Season 14"], "titles": [], "seasons_counted_from": 4,
  "accolades": [], "current_season": "Season 16", "current_season_matches": 18,
  "holo_unlocked": false
}
```

`opponent_team_id`/`opponent_team_name` are resolved from whichever of the match's
`radiant_team_id`/`dire_team_id` is not the player's own `team_id` for that row — both are
`null` if the opponent team hasn't been ingested.

`parse_status` is `parsed`, `unparsed`, `unparseable` or `null`. `match_history` lists every
match, including excluded ones (`excluded_from_scoring: true`). `matches` counts every match.
`avg_points`, `total_points` and `best_match` skip excluded matches. See
`reference/unparseable-match-handling.md`.

**Popup insights (issue 208),** all computed live with the scoring code and the current
weights (`card_points._current_weights`); helpers in `backend/player_insights.py`:
- Per match: `hero_id`, `hero_name` and `hero_icon_url` (from the cached OpenDota hero
  constants, never fetched inline; null when unknown or the cache is still cold), `won`
  (`radiant_win` against the player's side, null when either is unknown), `duration`,
  `sen_placed`, `week_label` (the scoring week from `weeks.scoring_week_for`, honouring
  `week_override_id`; "Week 3" becomes "W3") and `points_breakdown` (points per source, MVP
  bonus included; the parts add up to `fantasy_points` within rounding).
- `summary`: wins, losses and MVPs over scored matches, and `avg_rank` among the comparison
  population (null when the player is not in it).
- `league_avg_points` and each source's `league_avg`: averages per scored match over every
  player's scored matches. League figures are cached in process until the data or weights
  change (60 s at most).
- `points_sources`: every source with its average per scored match, share of the player's
  average (percent) and the league average. `modifier_values`: per stat (deaths included),
  what a `modifier_bonus_pct` card modifier is worth per match, highest first; `base` is the
  stat's average points, so a modifier with its own bonus is worth `base × bonus / 100`.
- `league_comparison`: percentiles (mid-rank, ties count half) for Kills, Deaths, Assists,
  GPM, Last hits, Wards, Stuns and Teamfight % against players with at least 3 scored
  matches; Deaths are ranked lower-is-better. Null when the player has fewer than 3.
- `heroes`: this season's heroes, most played first; matches without a `hero_id` count in
  no row.

Excluded matches stay in `match_history` but count in none of these figures; partial-stat
matches count. The response carries no viewer data. See
`reference/player-popup-visualizations.md`.

**Accolades (issue 50):** `seasons_played`, `seasons`, `titles`, `accolades`,
`current_season`, `current_season_matches` and `holo_unlocked`; see
`reference/season-winners-and-holo-cards.md`.

Returns 404 if the player has not been ingested.

---

### `GET /players/{player_id}/profile`

Returns an enriched player profile payload (if present) containing derived facts and an optional AI-generated bio. This endpoint is used by the player detail modal to show extra context beyond raw match history.

Returns 404 if the player does not yet have an enriched profile.

See `markdown/features/reference/player-profile-enrichment.md` for how profiles are generated and refreshed.

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

Each player's `matches` counts every match. `avg_points` and `total_points` skip matches an admin
excluded from scoring.

Returns 404 if the team has not been ingested.
