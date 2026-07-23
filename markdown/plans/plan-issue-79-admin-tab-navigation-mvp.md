# Plan: Admin Tab Navigation and MVP Match View

## Context

The admin panel currently renders all management sections in a single vertical column, which
becomes unwieldy as more features are added. Issue #79 requests two related improvements: a
tab-based navigation layout for the admin view, and a match table that lets admins set the
MVP for any ingested match directly — without requiring the broadcaster Twitch session. This
gives operators a second, always-available path for MVP selection alongside the Twitch
extension flow.

Resolves GitHub issue #79.

---

## User Stories

### Admin Tab Navigation

**User story**
As an admin, I want the admin panel organised into named tabs so that I can navigate directly
to the management area I need without scrolling through every section.

**Acceptance criteria**
- Admin panel shows a tab bar with the following tabs: **Week Management**, **Player Pool**,
  **Audit Log**, **Settings** (combines League management, Token Balances, Tag Definitions),
  and **Matches**
- Clicking a tab shows only that tab's content; all other sections are hidden
- The active tab is visually highlighted
- Tab selection is preserved within the page session (switching away and back remembers the
  active tab)
- Non-admin users never see the tab navigation

---

### Admin Match Table

**User story**
As an admin, I want to view all ingested matches in a table so that I have a complete
picture of the data that has been imported from OpenDota.

**Acceptance criteria**
- Matches tab shows a table with columns: League, Series ID, Team 1, Team 2, Start Time,
  Duration, MVP
- Matches are ordered by start time descending (most recent first)
- The MVP column shows the current MVP player name, or "—" if no MVP has been set
- The table loads from a new admin endpoint `GET /admin/matches`

---

### Admin MVP Selection

**User story**
As an admin, I want to set the MVP for any match from the admin panel so that MVP bonuses
can be applied even when a Twitch broadcaster session is unavailable.

**Acceptance criteria**
- Each match row in the Matches tab has a "Set MVP" button
- Clicking the button opens a selection UI listing the 10 players who participated in that
  match (fetched from `player_match_stats` for that match)
- Selecting a player and confirming calls `POST /admin/matches/{match_id}/mvp`
- The MVP column updates immediately to reflect the new selection
- The action is logged to the audit log as `admin_set_mvp`
- Setting MVP via the admin panel uses the same `twitch_mvp` table row as the Twitch
  broadcaster flow — setting it here makes the fantasy bonus apply correctly

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/routers/admin.py` | Add `GET /admin/matches` and `POST /admin/matches/{match_id}/mvp` endpoints |
| `backend/models.py` | No new model required — reuse `TwitchMVP` and `PlayerMatchStats` |
| `frontend/app-admin.js` | Add tab navigation logic; add Matches tab with match table and MVP selection UI |
| `frontend/index.html` | Add tab bar HTML to the admin section |

---

### Step 1 — Backend: `GET /admin/matches`

Add a new endpoint to `backend/routers/admin.py` that returns all ingested matches with MVP info:

```python
@router.get("/matches")
def list_matches(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    matches = db.query(Match).order_by(Match.start_time.desc()).all()
    result = []
    for m in matches:
        mvp = db.query(TwitchMVP).filter(TwitchMVP.match_id == m.match_id).first()
        mvp_name = None
        if mvp:
            p = db.query(Player).filter(Player.id == mvp.player_id).first()
            mvp_name = p.name if p else None
        result.append({
            "match_id": m.match_id,
            "league_id": m.league_id,
            "series_id": m.series_id,
            "team1": m.team1,
            "team2": m.team2,
            "start_time": m.start_time,
            "duration": m.duration,
            "mvp_player_name": mvp_name,
            "mvp_player_id": mvp.player_id if mvp else None,
        })
    return result
```

Also add a sub-endpoint to fetch the 10 players for a specific match:

```python
@router.get("/matches/{match_id}/players")
def match_players(
    match_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    stats = db.query(PlayerMatchStats).filter(
        PlayerMatchStats.match_id == match_id
    ).all()
    players = []
    for s in stats:
        p = db.query(Player).filter(Player.id == s.player_id).first()
        if p:
            players.append({"id": p.id, "name": p.name})
    return players
```

---

### Step 2 — Backend: `POST /admin/matches/{match_id}/mvp`

Add an admin endpoint that sets or updates the MVP for a match, reusing the same `TwitchMVP`
table the Twitch flow writes to:

```python
class AdminMVPRequest(BaseModel):
    player_id: int

@router.post("/matches/{match_id}/mvp")
def admin_set_mvp(
    match_id: int,
    body: AdminMVPRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    match = db.query(Match).filter(Match.match_id == match_id).first()
    if not match:
        raise HTTPException(status_code=404, detail="Match not found")
    player = db.query(Player).filter(Player.id == body.player_id).first()
    if not player:
        raise HTTPException(status_code=404, detail="Player not found")

    existing = db.query(TwitchMVP).filter(TwitchMVP.match_id == match_id).first()
    if existing:
        existing.player_id = body.player_id
    else:
        db.add(TwitchMVP(match_id=match_id, player_id=body.player_id))

    _audit(db, "admin_set_mvp", admin.username,
           f"match {match_id} → player {body.player_id} ({player.name})")
    db.commit()
    return {"match_id": match_id, "player_id": body.player_id, "player_name": player.name}
```

---

### Step 3 — Frontend: Tab navigation structure

In `frontend/index.html`, wrap the admin section content in a tab-based layout. Add a tab
bar above the admin content area with buttons for each tab. All existing admin section `<div>`
blocks get a `data-admin-tab="..."` attribute; only the active tab's div is shown.

Tab structure:
- `week-management` — Week Management
- `player-pool` — Player Pool
- `audit-log` — Audit Log
- `settings` — Settings (League mgmt + Token Balances + Tag Definitions)
- `matches` — Matches (new)

All existing admin section content maps into these tabs:
- Week records → `week-management`
- Player pool → `player-pool`
- Audit log → `audit-log`
- League monitoring, token grant events, notifications, promo codes, weights, user tags → `settings`
- Match table (new) → `matches`
- User management (grant tokens, tester toggle) — keep in a permanent top section above tabs

---

### Step 4 — Frontend: Tab switching logic in `app-admin.js`

Add a `initAdminTabs()` function that wires click handlers to the tab buttons. On click:
- Remove `active` class from all tab buttons
- Add `active` class to the clicked button
- Hide all `[data-admin-tab]` divs
- Show the div matching the clicked tab
- Store the active tab in `sessionStorage` so navigating away and back remembers it

Call `initAdminTabs()` from the admin panel render path after the admin check passes.

---

### Step 5 — Frontend: Matches tab

Add a new `<div data-admin-tab="matches">` containing:
- A `<table id="admin-matches-table">` with columns: League, Series, Team 1 vs Team 2, Start Time, Duration, MVP, Action
- An "MVP" cell showing the current MVP player name or "—"
- A "Set MVP" button per row; clicking opens a modal

When the matches tab is activated, call `loadAdminMatches()` which fetches `GET /admin/matches`
and populates the table.

The MVP selection modal:
- Fetches `GET /admin/matches/{match_id}/players`
- Shows each player as a radio-button row
- "Confirm" button POSTs to `POST /admin/matches/{match_id}/mvp`
- On success, refresh the row's MVP cell and close the modal

---

## Verification

- Navigate to the Admin tab — tab bar appears with all five tabs
- Clicking each tab shows only that section's content; others are hidden
- Navigate to another app tab and back — previous admin tab is still selected
- Matches tab loads and shows all ingested matches with correct team names and start times
- A match with no MVP shows "—" in the MVP column
- Click "Set MVP", select a player, confirm — MVP column updates to the selected player name
- Audit log entry `admin_set_mvp` appears with the correct match and player detail
- Setting MVP via admin does not break Twitch extension MVP reading (same `twitch_mvp` row)
- Non-admin users do not see the admin tab bar
