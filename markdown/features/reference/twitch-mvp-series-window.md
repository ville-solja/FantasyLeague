# Twitch MVP Series Window

Changes the MVP selection panel to show the 5 most recent series with ingested match data
(regardless of week boundaries) and adds a faster ingest polling interval for live-stream use.

---

## Endpoint Change

### `GET /twitch/matches/current` *(updated)*

Previously returned matches from the current or most-recently-locked week only. After this
change, returns the 5 most recent series (team-pair groups) that have at least one match
with ingested `player_match_stats` rows or, since issue #139, a provisional live match (see
`early-mvp-selection.md`), with no lower time bound — a stale first week with no
subsequent ingest activity would still surface here indefinitely.

Since issue #139 a series can also contain **provisional** matches: games seen in OpenDota's
`/live` feed (table `live_matches`) whose stats are not ingested yet. A provisional match's
`start_time` is when it was first seen live, its players come from the live feed with
`fantasy_points: 0`, and a live game with no team ids is grouped by its team names. See
[Early MVP Selection](early-mvp-selection.md).

Response shape (simplified — `week` key removed):

```json
{
  "series": [
    {
      "team1_name": "Team A",
      "team2_name": "Team B",
      "matches": [
        {
          "match_id": 123456,
          "match_number": 1,
          "start_time": 1746000000,
          "provisional": false,
          "live": false,
          "players": [...],
          "mvp_player_id": null,
          "mvp_player_name": null
        }
      ]
    }
  ]
}
```

`provisional` is `true` for a match listed from the live feed, and `live` is `true` while
that game is still in `/live` (always `false` for an ingested match).

Series are sorted most-recently-played first. At most 5 series are returned.

The selection lives in `twitch._current_series()`. Since issue #135 it is also the MVP
eligibility window: `POST /twitch/mvp` returns 403 for a match outside it. The window can move
between listing and confirming (a newer series pushes the oldest out), in which case the Live
Config panel shows the 403 detail ("Match is not in the current series window") in its banner.

---

## Ingest Polling

Two intervals are now configurable:

| Variable | Default | When used |
|---|---|---|
| `INGEST_LIVE_POLL_INTERVAL` | `120` | Active (unlocked, currently-running) week exists |
| `INGEST_POLL_INTERVAL` | `900` | No active week (off-season / between weeks) |

The ingest loop checks for an active week at the end of each cycle and selects the
appropriate interval for the next sleep. A live monitored game, or one that ended less than
`INGEST_POST_MATCH_FAST_POLL_MINUTES` (default 20) ago and is not yet ingested, takes priority
and uses `INGEST_LIVE_MATCH_POLL_INTERVAL` (30 s) — see
[OpenDota Query Prioritization](opendota-query-prioritization.md) and
[Early MVP Selection](early-mvp-selection.md).

## Configuration

| Variable | Default | Description |
|---|---|---|
| `INGEST_LIVE_POLL_INTERVAL` | `120` | Seconds between ingest polls during a live week |
| `INGEST_POST_MATCH_FAST_POLL_MINUTES` | `20` | Minutes after a monitored game ends during which the fast live-match interval is kept, until it is ingested |

---

Implemented in `backend/twitch.py` (`current_matches`), `backend/main.py` (`_ingest_poll_loop`), and `twitch-extension/live_config.js`.
