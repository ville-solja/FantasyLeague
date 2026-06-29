# Plan: Monitored Leagues Admin Panel

## Context

The set of leagues whose matches are ingested is currently controlled only by the `AUTO_INGEST_LEAGUES` environment variable. Once the process starts, the list is fixed in memory and cannot be changed without a restart. There is no admin UI to see which leagues are being monitored, and accidentally ingesting a wrong league has no supported rollback path. This plan adds an admin panel element for viewing and managing monitored leagues at runtime, and a purge endpoint to undo a wrong ingest. Resolves GitHub issue #70.

---

## User Stories

### View Monitored Leagues
**User story**
As an admin, I want to see a list of leagues currently being auto-ingested so that I can verify the correct leagues are configured without reading environment variables.

**Acceptance criteria**
- The admin tab contains a "League Management" panel listing all leagues known to the database
- Each row shows: league ID, league name, match count, and whether the league is currently monitored
- The list refreshes when the Refresh button is clicked

### Add or Remove a League from Monitoring
**User story**
As an admin, I want to add or remove a league from the monitored set at runtime so that I can fix a configuration mistake without restarting the service.

**Acceptance criteria**
- An "Add" flow lets the admin enter an OpenDota league ID and marks it as monitored; the next poll cycle will ingest it
- A "Remove" button on each monitored league unsets the monitored flag; future poll cycles will not ingest it
- Adding a league that is already monitored returns a clear error
- Removing a league does not delete its existing match data — it only stops future polling

### Purge Wrongly Ingested League Data
**User story**
As an admin, I want to purge all match data ingested for a specific league so that I can roll back an accidental ingest of the wrong league.

**Acceptance criteria**
- A "Purge data" action is available for any league that has match data in the database
- The purge deletes all `player_match_stats`, `match_bans`, and `matches` rows for that league and sets `is_monitored = False`
- The purge does NOT delete player records (they may appear in other leagues)
- The purge returns counts of deleted rows so the admin can confirm scope
- After purge, the admin is reminded to use the existing Recalculate endpoint to refresh fantasy scores
- A confirmation modal is shown before the purge executes

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/models.py` | Add `is_monitored` column to `League` |
| `backend/migrate.py` | Migration m017: `ALTER TABLE leagues ADD COLUMN is_monitored` |
| `backend/main.py` | Seed `AUTO_INGEST_LEAGUES` into DB on startup; change poll loop to read `is_monitored` leagues from DB each cycle |
| `backend/routers/admin.py` | Four new endpoints: list, monitor, unmonitor, purge |
| `frontend/index.html` | New "League Management" admin panel + confirm modal |
| `frontend/app-admin.js` | `loadLeagues()` / `_renderLeagues()` / filter; open/close modals; API calls |
| `frontend/app-globals.js` | Wire `loadLeagues()` into admin tab init |

### Step 1 — Add `is_monitored` to `League` model

In `backend/models.py`, add:

```python
class League(Base):
    __tablename__ = "leagues"

    id          = Column(Integer, primary_key=True)
    name        = Column(String)
    is_monitored = Column(Boolean, default=False, nullable=False)
```

### Step 2 — Add migration m017

In `backend/migrate.py`, add inside `run_migrations()`:

```python
def _m017_leagues_is_monitored(conn):
    cols = {r[1] for r in conn.execute(text("PRAGMA table_info(leagues)"))}
    if "is_monitored" not in cols:
        conn.execute(text("ALTER TABLE leagues ADD COLUMN is_monitored INTEGER NOT NULL DEFAULT 0"))
```

Call it alongside the other migrations.

### Step 3 — Seed monitored leagues from env var on startup

In `backend/main.py`, after migrations run and before the poll thread starts, add a startup step that upserts each `AUTO_INGEST_LEAGUES` ID into the DB with `is_monitored=True`:

```python
def _seed_monitored_leagues(league_ids: list[int]):
    db = SessionLocal()
    try:
        for lid in league_ids:
            league = db.get(League, lid)
            if not league:
                league = League(id=lid, name="(pending ingest)", is_monitored=True)
                db.add(league)
            else:
                league.is_monitored = True
        db.commit()
    finally:
        db.close()
```

Call `_seed_monitored_leagues(_league_ids)` before starting the poll thread.

### Step 4 — Change poll loop to read from DB each cycle

In `_ingest_poll_loop`, instead of using the fixed `league_ids` list, query the DB at the start of each cycle:

```python
def _ingest_poll_loop():
    while True:
        try:
            db = SessionLocal()
            try:
                monitored = db.query(League).filter(League.is_monitored == True).all()
                ids = [l.id for l in monitored]
            finally:
                db.close()
            _auto_ingest(ids)
        except Exception:
            logger.exception("Unexpected error in ingest poll loop")
        time.sleep(poll_interval)
```

Pass no `league_ids` argument when starting the thread.

### Step 5 — Admin endpoints in `backend/routers/admin.py`

```python
# GET /admin/leagues
@router.get("/admin/leagues")
def list_leagues(db=Depends(get_db), admin=Depends(require_admin)):
    leagues = db.query(League).all()
    result = []
    for l in leagues:
        match_count = db.query(Match).filter(Match.league_id == l.id).count()
        result.append({
            "id": l.id,
            "name": l.name or "(unknown)",
            "is_monitored": l.is_monitored,
            "match_count": match_count,
        })
    return result

# POST /admin/leagues/{league_id}/monitor
class AddLeagueBody(BaseModel):
    league_id: int = Field(..., gt=0)

@router.post("/admin/leagues/{league_id}/monitor")
def add_monitored_league(league_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    league = db.get(League, league_id)
    if league and league.is_monitored:
        raise HTTPException(status_code=409, detail="League is already monitored")
    if not league:
        league = League(id=league_id, name="(pending ingest)", is_monitored=True)
        db.add(league)
    else:
        league.is_monitored = True
    db.commit()
    _audit(db, "admin_league_add_monitor", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"league_id={league_id}")
    return {"status": "ok", "league_id": league_id}

# DELETE /admin/leagues/{league_id}/monitor
@router.delete("/admin/leagues/{league_id}/monitor")
def remove_monitored_league(league_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    league = db.get(League, league_id)
    if not league or not league.is_monitored:
        raise HTTPException(status_code=404, detail="League is not currently monitored")
    league.is_monitored = False
    db.commit()
    _audit(db, "admin_league_remove_monitor", actor_id=admin["user_id"],
           actor_username=admin["username"], detail=f"league_id={league_id}")
    return {"status": "ok", "league_id": league_id}

# DELETE /admin/leagues/{league_id}/data
@router.delete("/admin/leagues/{league_id}/data")
def purge_league_data(league_id: int, db=Depends(get_db), admin=Depends(require_admin)):
    from sqlalchemy import text as sa_text
    match_ids = [r[0] for r in db.execute(
        sa_text("SELECT id FROM matches WHERE league_id = :lid"), {"lid": league_id}
    ).fetchall()]
    deleted_stats = 0
    deleted_bans = 0
    if match_ids:
        placeholders = ",".join(str(m) for m in match_ids)
        deleted_stats = db.execute(
            sa_text(f"DELETE FROM player_match_stats WHERE match_id IN ({placeholders})")
        ).rowcount
        deleted_bans = db.execute(
            sa_text(f"DELETE FROM match_bans WHERE match_id IN ({placeholders})")
        ).rowcount
    deleted_matches = db.execute(
        sa_text("DELETE FROM matches WHERE league_id = :lid"), {"lid": league_id}
    ).rowcount
    league = db.get(League, league_id)
    if league:
        league.is_monitored = False
    db.commit()
    _audit(db, "admin_league_purge", actor_id=admin["user_id"],
           actor_username=admin["username"],
           detail=f"league_id={league_id} matches={deleted_matches} stats={deleted_stats}")
    return {
        "status": "ok",
        "league_id": league_id,
        "deleted_matches": deleted_matches,
        "deleted_stats": deleted_stats,
        "deleted_bans": deleted_bans,
        "note": "Run /recalculate to refresh fantasy scores after purge",
    }
```

### Step 6 — Frontend panel in `frontend/index.html`

Add a "League Management" panel to the left admin column, after Player Pool. Use the same header-row-with-buttons pattern:

```html
<!-- League Management panel -->
<div class="admin-panel" id="leagueManagementPanel">
  <div class="panel-header-row">
    <h2>League Management</h2>
    <button onclick="openAddLeagueModal()">Add</button>
    <button onclick="loadLeagues()">Refresh</button>
  </div>
  <table id="leagueTable">
    <thead><tr>
      <th>ID</th><th>Name</th><th>Matches</th><th>Monitored</th><th>Actions</th>
    </tr></thead>
    <tbody id="leagueTableBody"></tbody>
  </table>
</div>

<!-- Add League modal -->
<div id="addLeagueModal" class="modal-overlay" style="display:none" onclick="if(event.target===this)closeAddLeagueModal()">
  <div class="modal-box">
    <h3>Add League to Monitoring</h3>
    <label>OpenDota League ID<br>
      <input type="number" id="addLeagueIdInput" placeholder="e.g. 19368">
    </label>
    <div class="modal-actions">
      <button onclick="submitAddLeague()">Add</button>
      <button onclick="closeAddLeagueModal()">Cancel</button>
    </div>
  </div>
</div>

<!-- Purge League confirmation modal -->
<div id="purgeLeagueModal" class="modal-overlay" style="display:none" onclick="if(event.target===this)closePurgeLeagueModal()">
  <div class="modal-box">
    <h3>Purge League Data</h3>
    <p id="purgeLeagueDescription"></p>
    <p>This deletes all matches and stats for this league and stops monitoring. Fantasy scores must be recalculated manually afterwards.</p>
    <div class="modal-actions">
      <button onclick="confirmPurgeLeague()">Purge</button>
      <button onclick="closePurgeLeagueModal()">Cancel</button>
    </div>
  </div>
</div>
```

### Step 7 — Frontend JS in `frontend/app-admin.js`

Follow the `loadPlayerPool` / `_renderPlayerPool` pattern:

```javascript
let _leaguesCached = [];
let _purgeTargetLeagueId = null;

async function loadLeagues() {
    const resp = await authedFetch('/admin/leagues');
    _leaguesCached = await resp.json();
    _renderLeagues();
}

function _renderLeagues() {
    const tbody = document.getElementById('leagueTableBody');
    tbody.innerHTML = '';
    for (const l of _leaguesCached) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${l.id}</td>
            <td>${l.name}</td>
            <td>${l.match_count}</td>
            <td>${l.is_monitored ? 'Yes' : 'No'}</td>
            <td>
                ${l.is_monitored
                    ? `<button onclick="unmonitorLeague(${l.id})">Unmonitor</button>`
                    : `<button onclick="monitorLeague(${l.id})">Monitor</button>`
                }
                ${l.match_count > 0
                    ? `<button onclick="openPurgeLeagueModal(${l.id}, '${l.name}')">Purge data</button>`
                    : ''
                }
            </td>`;
        tbody.appendChild(tr);
    }
}

function openAddLeagueModal() { document.getElementById('addLeagueModal').style.display = 'flex'; }
function closeAddLeagueModal() { document.getElementById('addLeagueModal').style.display = 'none'; }

async function submitAddLeague() {
    const id = parseInt(document.getElementById('addLeagueIdInput').value);
    if (!id) return alert('Enter a valid league ID');
    const resp = await authedFetch(`/admin/leagues/${id}/monitor`, { method: 'POST' });
    if (!resp.ok) { alert((await resp.json()).detail); return; }
    closeAddLeagueModal();
    loadLeagues();
}

async function monitorLeague(id) {
    await authedFetch(`/admin/leagues/${id}/monitor`, { method: 'POST' });
    loadLeagues();
}

async function unmonitorLeague(id) {
    await authedFetch(`/admin/leagues/${id}/monitor`, { method: 'DELETE' });
    loadLeagues();
}

function openPurgeLeagueModal(id, name) {
    _purgeTargetLeagueId = id;
    document.getElementById('purgeLeagueDescription').textContent =
        `League: ${name} (ID ${id})`;
    document.getElementById('purgeLeagueModal').style.display = 'flex';
}
function closePurgeLeagueModal() {
    document.getElementById('purgeLeagueModal').style.display = 'none';
    _purgeTargetLeagueId = null;
}
async function confirmPurgeLeague() {
    if (!_purgeTargetLeagueId) return;
    const resp = await authedFetch(`/admin/leagues/${_purgeTargetLeagueId}/data`, { method: 'DELETE' });
    const data = await resp.json();
    alert(`Purged: ${data.deleted_matches} matches, ${data.deleted_stats} stats. ${data.note}`);
    closePurgeLeagueModal();
    loadLeagues();
}
```

Wire into `app-globals.js` alongside the existing admin tab init calls.

---

## Verification

- After startup with `AUTO_INGEST_LEAGUES=19368,19369`, the League Management panel shows both leagues with `is_monitored = Yes`
- Adding a new league ID via the modal marks it monitored; the next poll cycle ingests it
- Unmonitoring a league stops future ingests but leaves match data intact
- Purging a league's data removes all its matches and stats and sets `is_monitored = False`; clicking Recalculate afterwards rebuilds scores correctly
- Purging a league that has no match data shows 0 counts and no error
- The migration test (`test_all_model_columns_present_after_migration`) passes after adding migration m017
- All existing pytest tests continue to pass
