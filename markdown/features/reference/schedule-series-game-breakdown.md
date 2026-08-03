# Schedule Series Game Breakdown

Expands each resolved series in the Schedule tab's Results section from a single aggregate
score into a parent row with an expandable child row per individual game, showing duration,
each team's kills, and each team's hero picks. Visible to everyone (same audience as the
Schedule tab itself).

---

## Concept *(planned)*

A series (one row in the season schedule sheet) is resolved against the database to a list of
individual `match_id`s via `resolve_series_result()` in `backend/schedule.py`. Previously this
only surfaced as a flat row of bare "G1 ↗" / "G2 ↗" links next to the aggregate score. This
feature attaches per-game detail — duration, team kills, hero icons — to each resolved game, so
the series acts as a parent for its games rather than a single opaque result.

Team sides in each game are mapped to the series' own `team1`/`team2` (not raw Dota
radiant/dire), so hero icons and kills always render on the same side as the team name already
shown in the series header.

## Endpoints

### `GET /schedule` *(planned)*
Existing endpoint (`backend/routers/admin_ingest.py`); response shape gains a `games` array
per resolved series inside `series_result`:
```json
{
  "match_id": 8813824412,
  "duration": 2143,
  "team1_kills": 32, "team2_kills": 28,
  "team1_heroes": ["https://cdn.cloudflare.steamstatic.com/...png", null, ...],
  "team2_heroes": [...]
}
```
`duration` is `null` for matches ingested before the `Match.duration` column existed, until
re-ingested. Hero slots are padded to 5 with `null` when fewer than 5 heroes resolved.

---

*This document is a stub created at feature planning time. Fill in implementation details once
the feature is built.*
