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

Both team endpoints are built by `backend/team_insights.py` (issue 211). Matches an admin excluded from scoring count in no figure; partial-stat matches count. Every `logo_url` passes through `logo_hosts.safe_logo_url` (allowlisted https hosts only, else `null`). The schedule feed is read failure-safe: when it is down, series figures are empty or zero and the endpoints still answer 200. Ownership is an aggregate percentage; no user ids or usernames appear in either response.

### `GET /teams`

Returns every ingested team, Div 1 first, then Div 2, then unknown; within a division by series wins, then game wins.

```json
[
  {
    "id": 42, "name": "SomeTeam",
    "logo_url": "https://steamcdn-a.akamaihd.net/.../42.png",
    "division": "div1",
    "series_wins": 3, "series_losses": 1, "series_draws": 0,
    "wins": 8, "losses": 5, "matches": 13,
    "points_per_game": 61.2,
    "player_count": 6,
    "titles": [{"kind": "champion", "division": "div1", "season": "Season 16",
                "season_short": "S16", "team_name": "SomeTeam", "label": "S16 Div 1 Champion"}]
  }
]
```

- `division`: from the leagues of the team's matches (`accolades.league_division`: "Lower" in the name is Div 2), the division of most of them; `null` when no league is known.
- `series_*`: played series in the schedule feed that involve the team (by `team1_id`/`team2_id`, or `schedule.find_team_id` on the names).
- `wins`, `losses`, `matches`: scored matches the team played.
- `points_per_game`: the team's players' summed scored points divided by `matches`.
- `titles`: champion accolades from every season whose `team_name` matches the team's name, ignoring case and extra whitespace; one per season and division, newest first.

---

### `GET /teams/{team_id}`

The team popup's data.

```json
{
  "id": 42, "name": "SomeTeam", "logo_url": null, "division": "div1", "season": "Season 17",
  "titles": [ ...as in GET /teams... ],
  "matches": 13,
  "summary": {"series_wins": 3, "series_losses": 1, "series_draws": 0, "games": 13, "wins": 8,
              "losses": 5, "points_per_game": 61.2, "avg_game_length": 1925, "mvps": 4},
  "series": [{"week": "Week 1", "week_short": "W1", "division": "div1",
              "opponent": {"id": 7, "name": "Other", "logo_url": null},
              "datetime_iso": "2026-09-10T19:00:00", "wins": 2, "losses": 1, "result": "W",
              "start_time": 1757530800, "match_ids": [1, 2, 3]}],
  "upcoming": [{"week": "Week 5", "week_short": "W5", "division": "div1",
                "opponent": {"id": 9, "name": "Next", "logo_url": null},
                "datetime_iso": "2026-10-22T19:00:00", "date": null, "time": null, "scheduled": true,
                "stream_url": "https://www.twitch.tv/...", "stream_label": null}],
  "players": [{"id": 123456789, "name": "SomePlayer", "avatar_url": "https://...", "role": "Core",
               "games": 12, "matches": 12, "team_games": 13, "avg_points": 20.5, "total_points": 246.0,
               "mvps": 2, "share": 34.6, "owned_pct": 25, "also_played": false,
               "accolades": [ ...GET /accolades shape... ], "tags": [{"key": "caster", "label": "Caster"}]}],
  "points_sources": [{"key": "kills", "label": "Kills", "avg": 14.0, "share": 22.9, "league_avg": 12.6}],
  "modifier_values": {"bonus_pct": 10.0, "stats": [{"stat": "kills", "label": "Kills", "base": 14.0, "value": 1.4}]},
  "heroes": [{"hero_id": 2, "hero_name": "Axe", "icon_url": "https://...", "games": 4, "wins": 3,
              "losses": 1, "avg_points": 20.0, "players": [{"id": 123456789, "name": "SomePlayer", "games": 3}]}]
}
```

- `season`: `accolades.current_season_label`.
- `summary.avg_game_length`: seconds, `null` without durations. `mvps`: MVPs earned by the team's players.
- `series`: played feed series, oldest first; `result` is `W`, `L` or `D` (a drawn series). The score is the feed's, as on the Schedule tab. `upcoming`: unplayed series whose time has not passed, soonest first.
- `players`: one row per player with a scored match for the team, by total points. `role` follows the player popup's rule (Support when average wards are 3 or more and GPM is under 450). `share` is the percentage of the team's points. `also_played` is true below 30 % of `team_games`. `owned_pct` is the whole percentage of managers (full, non-tester, non-demo accounts with at least one active card) who hold an active card of the player; it is `null` for every player, with `"ownership_hidden": true` on the response, while fewer than 10 managers have cards.
- `points_sources` and `modifier_values`: `player_insights.points_sources` / `modifier_values` over the team's stat rows, divided per team game. `league_avg` is the average team's value per team game (cached, see below).
- `heroes`: the six most picked heroes (`player_insights.hero_rows`), with the players who played each.

The `GET /teams` list is cached in-process (`team_insights.cached_team_list`) until the stats, matches, teams, champion accolades, weights or the feed's `cached_at` change, at most 60 s. League figures (average team sources and ownership counts) are cached in-process by `team_insights.cached_league_numbers`, keyed on the weights, the stats fingerprint (`player_insights._data_version`) and the active cards; `team_insights.clear_league_cache()` empties it.

Returns 404 `"Team not found"` if the team has not been ingested.
