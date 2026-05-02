# Twitch MVP Series Window

Changes the MVP selection panel to show the 5 most recent series with ingested match data
(regardless of week boundaries) and adds a faster ingest polling interval for live-stream use.

---

## Endpoint Change

### `GET /twitch/matches/current` *(updated)*

Previously returned matches from the current or most-recently-locked week only. After this
change, returns the 5 most recent series (team-pair groups) that have at least one match
with ingested `player_match_stats` rows, looking back across a 30-day rolling window.

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
          "players": [...],
          "mvp_player_id": null,
          "mvp_player_name": null
        }
      ]
    }
  ]
}
```

Series are sorted most-recently-played first. At most 5 series are returned.

---

## Ingest Polling

Two intervals are now configurable:

| Variable | Default | When used |
|---|---|---|
| `INGEST_LIVE_POLL_INTERVAL` | `120` | Active (unlocked, currently-running) week exists |
| `INGEST_POLL_INTERVAL` | `900` | No active week (off-season / between weeks) |

The ingest loop checks for an active week at the end of each cycle and selects the
appropriate interval for the next sleep.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `INGEST_LIVE_POLL_INTERVAL` | `120` | Seconds between ingest polls during a live week |

---

Implemented in `backend/twitch.py` (`current_matches`), `backend/main.py` (`_ingest_poll_loop`), and `twitch-extension/live_config.js`.
