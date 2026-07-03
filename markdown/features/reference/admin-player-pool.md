# Admin Player Pool Management

Admin-only feature for controlling which players exist in the known player pool — adding new
players by OpenDota ID (individually or via CSV), and removing players with automatic token
refunds to card holders.

---

## Concept

The `players` table is the source of truth for which players exist in the app. Normally it is
populated through data ingestion, but admins can add players ahead of ingest or remove players
who have left the league. Removed players are **soft-deleted** (`is_active = false`) so that
historical `player_match_stats` records and card history remain intact.

When a player is removed, every active `Card` referencing that player is also deactivated, and
the card's owner receives 1 refund token per deactivated card.

## Endpoints

### `GET /admin/players`
Returns all players (active and inactive) ordered by name, with `id`, `name`, `is_active`, and
`active_card_count`. Admin only (`Depends(require_admin)`).

**Response shape:**
```json
[
  {"id": 12345, "name": "Player Name", "is_active": true, "active_card_count": 3}
]
```

### `POST /admin/players`
Adds a single player by OpenDota account ID. Validates against `https://api.opendota.com/api/players/{id}` to confirm the player exists and populate name and avatar URL.

**Request body:**
```json
{"player_id": 12345}
```

**Responses:**
- `200` — `{"id": 12345, "name": "Player Name"}` — player created and marked active
- `409` — player already exists in pool (active or inactive)
- `422` — ID not found on OpenDota (profile key absent or HTTP error)

**Audit event:** `admin_player_added` with `detail=f"player_id={player_id}"`

### `POST /admin/players/bulk`
Accepts a comma-separated string of OpenDota account IDs (max 2000 chars). Processes each ID
independently: valid new IDs are added; invalid integers, already-present IDs, and IDs that
fail OpenDota lookup are skipped with a reason.

**Request body:**
```json
{"player_ids": "12345,67890,notanint"}
```

**Response shape:**
```json
{"added": 2, "skipped": [{"id": "notanint", "reason": "not an integer"}]}
```

**Audit event:** `admin_player_bulk_added` with `detail=f"added={count}"` (only logged when at
least one player was added).

### `POST /admin/players/remove`
Accepts a list of player IDs. For each active player in the list:
1. Sets `Player.is_active = False`
2. Finds all `Card` rows with `player_id == pid AND is_active == True`
3. Sets each card's `is_active = False`
4. Groups cards by owner, increments `User.tokens` by the card count
5. Logs `admin_player_refund_issued` per affected user (inside the owner loop)
6. Logs `admin_player_removed` after all refunds for that player are issued

Players that are already inactive or not found are silently skipped.
Historical `PlayerMatchStats` rows are untouched.

**Request body:**
```json
{"player_ids": [12345, 67890]}
```

**Response:** `{"ok": true}`

**Audit events:**
- `admin_player_removed` — `detail=f"player_id={pid}"`
- `admin_player_refund_issued` — `detail=f"player_id={pid} user_id={uid} tokens={count}"`

## Model Change

| Model | Column | Type | Default | Migration |
|---|---|---|---|---|
| `Player` | `is_active` | `Boolean` | `True` | `016_players_is_active` — `ALTER TABLE players ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1` |

## Audit Log Events

| Event | Trigger |
|---|---|
| `admin_player_added` | Single-player add confirmed |
| `admin_player_bulk_added` | Bulk add completed (at least one added) |
| `admin_player_removed` | Player soft-deleted |
| `admin_player_refund_issued` | Tokens granted to a card holder after player removal |

## Frontend

The admin tab includes a "Player Pool" section with:
- A table (`#playerPoolTable`) listing all players with checkbox, Name, OpenDota ID, Active Cards columns
- "Add Player" button — opens a popup to enter a single OpenDota ID
- "Bulk Add" button — opens a popup to paste a CSV of IDs
- "Remove Selected" button — disabled until at least one checkbox is checked; shows a confirmation popup with selected player names before calling `POST /admin/players/remove`

Functions in `frontend/app-admin.js`:
- `loadPlayerPool()` — `GET /admin/players`, renders table
- `addPlayer(playerId)` — `POST /admin/players`
- `bulkAddPlayers(csv)` — `POST /admin/players/bulk`
- `removeSelectedPlayers()` — `POST /admin/players/remove` with checked IDs

Called from the admin tab init in `frontend/app-globals.js` alongside other admin sections.
