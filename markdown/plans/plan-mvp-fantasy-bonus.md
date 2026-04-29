# Plan: MVP Fantasy Bonus

## Context

When a broadcaster selects the MVP of a match via the Twitch extension, the designated player receives a configurable percentage bonus on their fantasy score for that specific match. The bonus is retroactive — it is applied (or re-applied) each time the MVP changes, and persists across `/recalculate` runs. The bonus magnitude is stored in the existing weights system (`mvp_bonus_pct`) so admins can tune it from the admin panel alongside rarity bonuses and stat weights without any code changes.

The key architectural constraint is that scoring currently aggregates `PlayerMatchStats.fantasy_points` across all matches in a week. The MVP bonus must therefore be stored on the `PlayerMatchStats` row itself (via an `is_mvp` flag + adjusted `fantasy_points`) so it is naturally included in all existing leaderboard, roster, and season-total queries with no further changes.

---

## User Stories

### MVP Fantasy Score Bonus
**User story**
As a fantasy league player, I want the designated MVP of a match to earn an extra percentage on their fantasy score for that match so that the broadcast MVP appointment has real in-game value.

**Acceptance criteria**
- When a broadcaster confirms an MVP via the Twitch extension, that player's `fantasy_points` for that specific match is multiplied by `(1 + mvp_bonus_pct / 100)`
- If the broadcaster later changes the MVP to a different player for the same match, the old player's bonus is removed and the new player receives it
- The bonus is reflected immediately in roster point totals, leaderboard standings, and the player match history
- An MVP match is visually distinguishable from a regular match in the player detail modal

### Configurable MVP Bonus Weight
**User story**
As an admin, I want to configure the MVP fantasy bonus percentage from the admin weights panel so I can tune its value without code changes.

**Acceptance criteria**
- A weight key `mvp_bonus_pct` (label: "MVP bonus (%)") is present in the admin weights panel with a default of `10.0`
- Changing the value and running `POST /recalculate` re-applies the updated bonus to all MVP-flagged matches
- `mvp_bonus_pct = 0` effectively disables the bonus without removing the MVP flag from past matches

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/models.py` | Add `is_mvp` boolean column to `PlayerMatchStats` |
| `backend/migrate.py` | Migration: add `is_mvp` column to `player_match_stats` |
| `backend/seed.py` | Add `mvp_bonus_pct` to `DEFAULT_WEIGHTS` |
| `backend/twitch.py` | On MVP confirm: clear previous MVP flag, set new flag, recalculate both affected `fantasy_points` rows |
| `backend/main.py` | Update `POST /recalculate` to apply MVP bonus for `is_mvp=True` rows; update ingest so newly ingested matches inherit the MVP flag if a `TwitchMVP` record already exists |
| `frontend/app.js` | Show MVP badge in player detail modal match history |

---

### Step 1 — Model: `is_mvp` column on `PlayerMatchStats`

In `backend/models.py`, add to `PlayerMatchStats`:

```python
is_mvp = Column(Boolean, default=False)
```

---

### Step 2 — Migration

In `backend/migrate.py`, inside `run_migrations()`:

```python
pms_cols = [r[1] for r in conn.execute(text("PRAGMA table_info(player_match_stats)")).fetchall()]
if "is_mvp" not in pms_cols:
    conn.execute(text("ALTER TABLE player_match_stats ADD COLUMN is_mvp BOOLEAN DEFAULT 0"))
    conn.commit()
    logger.info("Migration: player_match_stats — added is_mvp column")
```

---

### Step 3 — Weight: `mvp_bonus_pct`

In `backend/seed.py`, add to `DEFAULT_WEIGHTS`:

```python
{"key": "mvp_bonus_pct", "label": "MVP bonus (%)", "value": 10.0},
```

This immediately makes the weight visible and editable in the admin panel via `GET /weights`.

---

### Step 4 — Helper: apply/remove MVP bonus

Add a helper in `backend/main.py` (near the other scoring helpers):

```python
def _apply_mvp_bonus(db, player_id: int, match_id: int, set_mvp: bool):
    """Set or clear the MVP flag on a PlayerMatchStats row and adjust fantasy_points."""
    row = db.query(PlayerMatchStats).filter_by(player_id=player_id, match_id=match_id).first()
    if not row:
        return
    weights = {w.key: w.value for w in db.query(Weight).all()}
    base_pts = fantasy_score({
        "kills": row.kills, "assists": row.assists, "deaths": row.deaths,
        "gold_per_min": row.gold_per_min, "obs_placed": row.obs_placed,
        "sen_placed": row.sen_placed, "tower_damage": row.tower_damage,
    }, weights)
    bonus_pct = weights.get("mvp_bonus_pct", 10.0)
    if set_mvp:
        row.fantasy_points = round(base_pts * (1 + bonus_pct / 100), 4)
        row.is_mvp = True
    else:
        row.fantasy_points = round(base_pts, 4)
        row.is_mvp = False
```

---

### Step 5 — Update `POST /twitch/mvp`

In `backend/twitch.py`, in the MVP endpoint handler, after saving the new MVP and before the token drop:

1. Look up the previous MVP for this match (if any) from the `TwitchMVP` table.
2. If a previous MVP exists and differs from the new one, call `_apply_mvp_bonus(db, old_player_id, match_id, set_mvp=False)` to remove the old bonus.
3. Call `_apply_mvp_bonus(db, new_player_id, match_id, set_mvp=True)` to apply the new bonus.
4. Commit.

The import of `_apply_mvp_bonus` from `main.py` would create a circular import — define the helper in a new thin module `backend/scoring_utils.py`, or inline it in `twitch.py` with a direct DB query.

**Simpler alternative**: define `_set_mvp_bonus(db, player_id, match_id, set_flag)` directly in `twitch.py` using raw `SessionLocal` — consistent with how twitch.py currently operates as a standalone router.

---

### Step 6 — Update `POST /recalculate`

In `backend/main.py`, after the existing loop over all `PlayerMatchStats`:

```python
bonus_pct = weights.get("mvp_bonus_pct", 10.0)
for stat in stats:
    if stat.is_mvp:
        stat.fantasy_points = round(stat.fantasy_points * (1 + bonus_pct / 100), 4)
```

The recalculate flow becomes: (1) recompute base `fantasy_points` for all rows, then (2) apply MVP bonus to `is_mvp=True` rows. This ensures bonus always uses the current weight value.

---

### Step 7 — Ingest: inherit existing MVP flag

In the ingest pipeline (`backend/ingest.py`), after a new `PlayerMatchStats` row is committed for a match that already has a `TwitchMVP` record, set `is_mvp=True` and apply the bonus:

```python
from models import TwitchMVP
mvp = db.query(TwitchMVP).filter_by(match_id=match_id).first()
if mvp:
    pms_row = db.query(PlayerMatchStats).filter_by(
        player_id=mvp.player_id, match_id=match_id
    ).first()
    if pms_row:
        # apply bonus inline using current weights
        ...
        pms_row.is_mvp = True
```

---

### Step 8 — Frontend: MVP badge in match history

In `frontend/app.js`, in the player detail modal match history render function, add a small "MVP" badge (text label, no emoji) next to the fantasy points cell when `match.is_mvp === true`.

The `GET /players/{player_id}` endpoint response already returns `match_history` rows sourced from `player_match_stats`. Add `is_mvp` to that row's fields in the SQL query so the frontend can read it.

---

## Verification

- Select MVP via Twitch extension for match X, player Y. Confirm `player_match_stats.fantasy_points` for (Y, X) is `base × 1.1` (at default 10%).
- Confirm `player_match_stats.is_mvp = 1` for that row.
- Confirm the roster point total for a user with card Y increases by the expected amount.
- Change the MVP to player Z for the same match. Confirm Y's `is_mvp` clears and `fantasy_points` returns to base; Z's `is_mvp` is set.
- Set `mvp_bonus_pct = 20` in admin weights. Run `POST /recalculate`. Confirm MVP row now reflects 20% bonus.
- Set `mvp_bonus_pct = 0`. Run `POST /recalculate`. Confirm MVP row returns to base score (flag remains `is_mvp = 1`).
- Ingest a match where a `TwitchMVP` record already exists. Confirm the newly created `PlayerMatchStats` row immediately has `is_mvp = 1` and the bonus applied.
- Confirm `GET /players/{id}` match history includes `is_mvp: true` for the MVP match.
- Confirm no existing non-MVP rows are affected by any of the above operations.
