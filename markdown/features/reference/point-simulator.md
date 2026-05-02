# Point Simulator

The point simulator allows statisticians and analysts to compute fantasy scores for any ingested match using custom per-stat weights, without affecting live season scoring. It is designed as a standalone tool that external tooling can integrate with programmatically.

## Endpoints

### `GET /simulate`

Returns machine-readable documentation describing the simulation endpoint — its parameters, request body schema, response shape, and error codes. No authentication required.

Intended for tooling authors who want to introspect the API without reading source code.

### `POST /simulate/{match_id}`

Runs a fantasy score simulation for every player in the specified match.

**Path parameter**

| Parameter | Type | Description |
|-----------|------|-------------|
| `match_id` | integer | OpenDota match ID that has been ingested into the system |

**Request body** (JSON, all fields optional)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `kills` | float | DB default | Points awarded per kill |
| `last_hits` | float | DB default | Points per last hit |
| `denies` | float | DB default | Points per deny |
| `gold_per_min` | float | DB default | Points per GPM |
| `obs_placed` | float | DB default | Points per observer ward placed |
| `towers_killed` | float | DB default | Points per tower destroyed |
| `roshan_kills` | float | DB default | Points per Roshan kill |
| `teamfight_participation` | float | DB default | Participation scalar where `1.0 = 100%` |
| `camps_stacked` | float | DB default | Points per camp stacked |
| `rune_pickups` | float | DB default | Points per rune picked up |
| `firstblood_claimed` | float | DB default | Points for claiming first blood (0/1) |
| `stuns` | float | DB default | Points per second of stuns applied |
| `death_pool` | float | DB default | Base points awarded for 0 deaths |
| `death_deduction` | float | DB default | Points deducted per death (floored at 0) |

Any field that is omitted falls back to the current season weight stored in the database. Only the stats you want to test need to be included.

**Response**

```json
{
  "match_id": 8123456789,
  "weights_used": {
    "kills": 0.3,
    "last_hits": 0.003,
    "denies": 0.0003,
    "gold_per_min": 0.002,
    "obs_placed": 0.5,
    "towers_killed": 1.0,
    "roshan_kills": 1.0,
    "teamfight_participation": 3.0,
    "camps_stacked": 0.5,
    "rune_pickups": 0.25,
    "firstblood_claimed": 4.0,
    "stuns": 0.05,
    "death_pool": 3.0,
    "death_deduction": 0.3
  },
  "players": [
    {
      "player_id": 123456789,
      "player_name": "SomePlayer",
      "team_name": "SomeTeam",
      "fantasy_points": 34.5,
      "stats": {
        "kills": 8,
        "deaths": 2,
        "last_hits": 260,
        "denies": 10,
        "gold_per_min": 650.0,
        "obs_placed": 3,
        "towers_killed": 1,
        "roshan_kills": 0,
        "teamfight_participation": 0.6,
        "camps_stacked": 2,
        "rune_pickups": 4,
        "firstblood_claimed": 0,
        "stuns": 10.0
      }
    }
  ]
}
```

Players are returned sorted by `fantasy_points` descending. The `weights_used` object always reflects the full merged weight map (defaults + overrides), so results are reproducible from the response alone.

**Errors**

| Status | Meaning |
|--------|---------|
| 404 | Match ID not found — the match has not been ingested |
| 422 | Validation error — a non-numeric weight value was supplied |

## Design notes

- **No authentication required.** The endpoint is intentionally public so statisticians can call it without an account.
- **No side effects.** Simulation never writes to the database or affects live scoring.
- **Modifier-free.** Card rarities and per-card stat modifiers are not applied — the simulator operates on raw match stats and weight values only, matching the base `fantasy_score()` formula.
- **Rarity and card modifiers excluded by design.** Those are user-specific and per-card; the simulator is about evaluating stat weights across the whole match, not individual card performance.

## Scoring formula

```
fantasy_points = kills × kills_weight
               + last_hits × last_hits_weight
               + denies × denies_weight
               + gold_per_min × gpm_weight
               + obs_placed × obs_weight
               + towers_killed × tower_weight
               + roshan_kills × roshan_weight
               + teamfight_participation × participation_weight   (where 1.0 = 100%)
               + camps_stacked × stack_weight
               + rune_pickups × rune_weight
               + firstblood_claimed × firstblood_weight
               + stuns × stun_weight
               + max(0, death_pool − deaths × death_deduction)
```

## Configuring season weights

Weights used as defaults in the simulator (and in live scoring) are set via the `WEIGHTS_JSON` environment variable. Changes take effect on the next restart. Example:

```
WEIGHTS_JSON={"kills": 0.3, "death_pool": 3.0, "death_deduction": 0.3}
```

Keys not present in `WEIGHTS_JSON` retain their hardcoded defaults. See `backend/seed.py` for the full default value list.
