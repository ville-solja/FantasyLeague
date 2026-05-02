# Plan: Architecture Improvements

## Context

A systems architecture review surfaced 9 findings (0 High, 3 Medium, 6 Low) across data
layer, observability, background jobs, and frontend. None are blocking but the three Medium
issues will degrade performance as the season progresses: missing indexes cause full-table
scans on every roster load and every draw; `print()` in the two busiest modules bypasses
Python logging entirely; and an N+1 query in the Twitch endpoint fires per-match during
live broadcasts. This plan addresses all 9 in priority order.

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/models.py` | Add `Index` declarations for 4 hot query paths |
| `backend/database.py` | Enable WAL journal mode at engine startup |
| `backend/opendota_client.py` | Replace all `print()` with `logger.*` |
| `backend/enrich.py` | Replace `print()` in `enrich_players()` with `logger.*` |
| `backend/twitch.py` | Bulk-fetch `PlayerMatchStats` before series loop in `current_matches()`; extract token-drop logic into helper; add explicit `allow_credentials=False` note |
| `backend/main.py` | Add explicit `allow_credentials=False` to `CORSMiddleware` |
| `backend/routers/cards.py` | Use module-level `ROSTER_LIMIT` constant in `activate_card()` |
| `backend/requirements.txt` | Remove `pytest`; add `backend/requirements-dev.txt` |
| `frontend/app-init.js` | Call `loadWeeks()` once and share result with both consumers |

---

### Step 1 — Database indexes (`backend/models.py`)

Add four `Index` declarations after the model definitions they cover. SQLAlchemy's
`create_all()` will create the index DDL on next startup; existing SQLite databases
get the indexes without a migration (SQLite supports `CREATE INDEX IF NOT EXISTS`).

```python
from sqlalchemy import Index

# After PlayerMatchStats class
Index('ix_pms_player_id', PlayerMatchStats.player_id)
Index('ix_pms_match_id',  PlayerMatchStats.match_id)

# After Card class
Index('ix_cards_owner_id',   Card.owner_id)
Index('ix_cards_player_id',  Card.player_id)

# After WeeklyRosterEntry class
Index('ix_wre_user_week', WeeklyRosterEntry.user_id, WeeklyRosterEntry.week_id)

# After TwitchPresence class
Index('ix_presence_channel_seen', TwitchPresence.channel_id, TwitchPresence.seen_at)
```

These cover: roster queries, card draw dedup, weekly snapshot reads, heartbeat upserts,
and the active-pool query for token drops.

---

### Step 2 — SQLite WAL mode (`backend/database.py`)

Add a connection event listener so every new connection runs `PRAGMA journal_mode=WAL`.
WAL allows concurrent readers alongside a single writer — the three background threads
no longer need to wait on each other for reads.

```python
from sqlalchemy import event

@event.listens_for(engine, "connect")
def set_wal_mode(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()
```

---

### Step 3 — Replace `print()` with `logger.*` (`backend/opendota_client.py`)

`opendota_client.py` uses `print()` for all `[WARN]`, `[ERROR]`, and `[RATE LIMIT]`
messages. Replace with a module logger:

```python
logger = logging.getLogger(__name__)
```

Mapping:
- `print(f"[WARN] ...")` → `logger.warning(...)`
- `print(f"[ERROR] ...")` → `logger.error(...)`
- `print(f"[RATE LIMIT] ...")` → `logger.warning(...)`

---

### Step 4 — Replace `print()` with `logger.*` (`backend/enrich.py`)

`enrich_players()` uses `print()` for `[ENRICH]`, `[PLAYER]`, and `[ERROR]` messages.
The module already has `logger = logging.getLogger(__name__)` at the top — the fix is
replacing the `print()` calls with `logger.info/warning/error()` calls. The
`run_enrichment()` function is similarly affected.

---

### Step 5 — Fix N+1 in `current_matches()` (`backend/twitch.py`)

In `current_matches()` (around line 354), a `db.query(PlayerMatchStats, Player, Team)`
is issued inside the inner loop over `series_matches`. With 10 matches in a week this
is 10 separate JOIN queries.

Replace with a single bulk fetch before the loop:

```python
# Bulk-fetch all player stats for the week's matches in one query
all_match_ids = [m.match_id for m in matches]
stats_by_match: dict[int, list] = {}
if all_match_ids:
    all_stats = (
        db.query(PlayerMatchStats, Player, Team)
        .join(Player, PlayerMatchStats.player_id == Player.id)
        .join(Team, PlayerMatchStats.team_id == Team.id)
        .filter(PlayerMatchStats.match_id.in_(all_match_ids))
        .all()
    )
    for pms, p, t in all_stats:
        stats_by_match.setdefault(pms.match_id, []).append((pms, p, t))
```

Then replace the inner `db.query(...)` with `stats_by_match.get(m.match_id, [])`.

---

### Step 6 — Extract token-drop helper (`backend/twitch.py`)

The token-drop block in `set_mvp()` (lines 492–519) is a distinct operation: select
random winners, grant tokens, write the drop record, write the audit log. Extract into:

```python
def _execute_token_drop(
    db: Session, channel_id: str, match_id: int, weights: dict
) -> tuple[list[str], int]:
    """Grant tokens to a random sample of present linked viewers. Returns (winner_names, pool_size)."""
    ...
```

`set_mvp()` calls this and uses the return value. This also makes the token-drop path
independently testable.

---

### Step 7 — Explicit `allow_credentials=False` in CORS (`backend/main.py`)

The current `CORSMiddleware` with `allow_origins=["*"]` is safe only because
`allow_credentials` defaults to `False`. Make this explicit so a future contributor
doesn't accidentally add `allow_credentials=True` without understanding the risk:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,  # Must stay False with allow_origins="*" — see twitch.py comment
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
```

---

### Step 8 — Use `ROSTER_LIMIT` constant in `activate_card()` (`backend/routers/cards.py`)

`activate_card()` re-reads `ROSTER_LIMIT` from env inline. Replace:

```python
# Before
roster_limit = int(os.getenv("ROSTER_LIMIT", "5"))

# After
roster_limit = ROSTER_LIMIT  # module-level constant defined at top of file
```

---

### Step 9 — Move `pytest` to dev requirements (`backend/requirements.txt`)

Create `backend/requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.0,<9.0
```

Remove `pytest` from `requirements.txt`. Update the CI workflow (`pytest` step) to
install from `requirements-dev.txt` instead.

---

### Step 10 — Single `loadWeeks()` call in `init()` (`frontend/app-init.js`)

`init()` currently calls `loadWeeks()` twice, firing two parallel `GET /weeks` requests
and writing to `_weeks` twice:

```javascript
// Before
if (activeUserId) {
    loadDeck();
    loadWeeks().then(() => loadRoster(_rosterWeekId));
}
loadWeeks().then(() => { _populateLbWeekSelect(); loadSeasonLeaderboard(); });
```

```javascript
// After
if (activeUserId) {
    loadDeck();
    loadWeeks().then(() => {
        loadRoster(_rosterWeekId);
        _populateLbWeekSelect();
        loadSeasonLeaderboard();
    });
} else {
    loadWeeks().then(() => { _populateLbWeekSelect(); loadSeasonLeaderboard(); });
}
```

---

## Verification

- After startup, confirm SQLite index DDL in `.schema` output: `sqlite3 data/fantasy.db ".indexes"`
- Confirm WAL mode: `sqlite3 data/fantasy.db "PRAGMA journal_mode;"` → `wal`
- Start app with `LOG_LEVEL=DEBUG` or equivalent and confirm OpenDota rate-limit
  messages appear via Python logging (visible in structured log output, respects log level)
- `GET /twitch/matches/current` — verify response time does not grow with match count;
  confirm single DB roundtrip replaces N queries (add a temporary query counter or check
  SQLAlchemy echo output)
- Run `python -m pytest tests/ -v` from `backend/requirements-dev.txt` install — all
  104 tests should pass
- In browser: open My Team tab and confirm roster + leaderboard week selector both
  populate correctly after a single `GET /weeks` request (check Network tab in devtools)
