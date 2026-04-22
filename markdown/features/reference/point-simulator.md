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
| `assists` | float | DB default | Points awarded per assist |
| `deaths` | float | DB default | Points per death (typically negative) |
| `gold_per_min` | float | DB default | Points per GPM |
| `obs_placed` | float | DB default | Points per observer ward placed |
| `sen_placed` | float | DB default | Points per sentry ward placed |
| `tower_damage` | float | DB default | Points per tower damage dealt |

Any field that is omitted falls back to the current season weight stored in the database. Only the stats you want to test need to be included.

**Response**

```json
{
  "match_id": 8123456789,
  "weights_used": {
    "kills": 3.0,
    "assists": 2.0,
    "deaths": -1.5,
    "gold_per_min": 0.02,
    "obs_placed": 1.0,
    "sen_placed": 1.5,
    "tower_damage": 0.002
  },
  "players": [
    {
      "player_id": 123456789,
      "player_name": "SomePlayer",
      "team_name": "SomeTeam",
      "fantasy_points": 34.5,
      "stats": {
        "kills": 8,
        "assists": 12,
        "deaths": 2,
        "gold_per_min": 650.0,
        "obs_placed": 3,
        "sen_placed": 5,
        "tower_damage": 4200
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
               + assists × assists_weight
               + deaths × deaths_weight
               + gold_per_min × gpm_weight
               + obs_placed × obs_weight
               + sen_placed × sen_weight
               + tower_damage × tower_dmg_weight
```

## Configuring season weights

Weights used as defaults in the simulator (and in live scoring) are set via the `WEIGHTS_JSON` environment variable. Changes take effect on the next restart. Example:

```
WEIGHTS_JSON={"kills": 3.0, "deaths": -1.5, "gold_per_min": 0.025}
```

Keys not present in `WEIGHTS_JSON` retain their hardcoded defaults. See `backend/seed.py` for the full default value list.
