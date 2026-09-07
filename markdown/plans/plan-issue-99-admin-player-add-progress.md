# Plan: Admin Player Add Progress

## Context
Adding players to the pool (`POST /admin/players` and `POST /admin/players/bulk`) currently
blocks with no visible feedback until the entire request completes. For bulk add, this is
particularly painful: each ID triggers a separate OpenDota lookup, and OpenDota throttling can
stretch a batch of a dozen IDs into a long silent wait, leaving the admin unsure whether the
button click registered at all. This plan adds live, per-ID progress reporting to the bulk add
flow (the primary pain point, since it processes an admin-supplied list) and a lightweight
pending-state indicator to the single add flow, so admins can watch each outbound OpenDota
request and its outcome as it happens, including throttling/error responses. *Resolves GitHub
issue #99.*

## User Stories

### Live Progress for Bulk Player Add
**User story**
As an admin, I want to see real-time progress when bulk-adding players by OpenDota ID, so
that I can confirm the button is working and monitor which IDs succeed or fail as OpenDota
is queried.

**Acceptance criteria**
- The Bulk Add popup shows a progress panel immediately after Confirm is clicked, before any
  ID has finished processing
- The panel lists each submitted ID with a status indicator: pending, added, skipped, or failed
- A running counter shows "X of N processed"
- The panel updates incrementally as each ID's OpenDota lookup and DB write completes, not all
  at once after the whole batch finishes
- If OpenDota throttles or errors on a request, that ID is marked failed with the error reason
  shown, and processing continues with the next ID
- Closing the popup after completion returns the player pool table already refreshed with the
  newly added players

### Endpoint Streams Per-ID Results
**User story**
As a backend maintainer, I want the bulk-add endpoint to stream a result line per processed
player ID rather than buffering the full response, so that the frontend can render progress
live and admins can diagnose failures such as OpenDota rate limiting mid-batch.

**Acceptance criteria**
- `POST /admin/players/bulk` responds with a stream of newline-delimited JSON objects: one
  line per input ID, followed by a final summary line
- Each per-ID line includes the ID, the resulting status (`added`/`skipped`/`error`), and a
  reason for any non-added outcome
- The final line includes the total added count and the full skipped list, preserving today's
  `{"added": N, "skipped": [...]}` shape for anything relying on the summary
- The `admin_player_bulk_added` audit event is still recorded exactly once per batch, not once
  per ID
- Existing behaviour (dedupe against existing player IDs, OpenDota validation, invalid-integer
  handling, 2000-char CSV limit) is unchanged

### Add Player Button Shows Pending State
**User story**
As an admin, I want the "Add Player" confirm button to show a pending/loading state while the
OpenDota lookup for a single ID is in flight, so that I know my click registered even though
there is only one item to process.

**Acceptance criteria**
- Clicking Confirm on the single Add Player popup disables the button and Close action and
  shows a loading indicator until the response returns
- The button, input, and Close action are re-enabled after success or error
- The underlying `POST /admin/players` request/response contract is unchanged

---

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/admin_players.py` | Convert `bulk_add_players` to a `StreamingResponse` that yields one NDJSON line per processed ID plus a final summary line |
| `frontend/app-admin.js` | `bulkAddPlayers()` reads the streamed response via `response.body.getReader()`, updates a progress list per line; `addPlayer()` toggles a pending state on the Confirm button |
| `frontend/index.html` | Bulk Add popup gains a progress panel (per-ID rows + "X of N" counter); Add Player popup's Confirm button gets a loading state |
| `backend/tests/test_admin_players.py` (or equivalent) | Update/extend bulk-add tests to consume the streamed body and assert per-line and summary shapes |

### Step 1 — Stream the bulk endpoint

In `backend/routers/admin_players.py`, replace the buffered loop in `bulk_add_players` with a
generator wrapped in `fastapi.responses.StreamingResponse` (`media_type="application/x-ndjson"`).
The generator performs the same per-ID logic as today (integer parsing, existing-ID dedupe,
OpenDota lookup, `Player` insert) but `yield`s a JSON line after each ID is resolved:

```python
import json
from fastapi.responses import StreamingResponse

def _bulk_add_stream(raw_ids, db, admin):
    added, skipped = [], []
    total = len(raw_ids)
    for i, raw in enumerate(raw_ids, start=1):
        try:
            pid = int(raw)
        except ValueError:
            skipped.append({"id": raw, "reason": "not an integer"})
            yield json.dumps({"id": raw, "status": "error",
                               "reason": "not an integer", "index": i, "total": total}) + "\n"
            continue
        if db.get(Player, pid):
            skipped.append({"id": pid, "reason": "already exists"})
            yield json.dumps({"id": pid, "status": "skipped",
                               "reason": "already exists", "index": i, "total": total}) + "\n"
            continue
        result = opendota_get_json(f"{OPEN_DOTA_URL}/players/{pid}", label=f"player {pid}")
        if not result or not result.get("profile"):
            skipped.append({"id": pid, "reason": "not found on OpenDota"})
            yield json.dumps({"id": pid, "status": "error",
                               "reason": "not found on OpenDota", "index": i, "total": total}) + "\n"
            continue
        data = result["profile"]
        db.add(Player(id=pid, name=data.get("personaname", str(pid)),
                       avatar_url=data.get("avatarfull", ""), is_active=True))
        added.append(pid)
        yield json.dumps({"id": pid, "status": "added", "index": i, "total": total}) + "\n"

    if added:
        _audit(db, "admin_player_bulk_added", actor_id=admin["user_id"],
               actor_username=admin["username"], detail=f"added={len(added)}")
    db.commit()
    yield json.dumps({"done": True, "added": len(added), "skipped": skipped}) + "\n"


@router.post("/admin/players/bulk")
def bulk_add_players(body: BulkAddPlayersBody, db=Depends(get_db),
                     admin=Depends(require_admin)):
    raw_ids = [s.strip() for s in body.player_ids.split(",") if s.strip()]
    return StreamingResponse(_bulk_add_stream(raw_ids, db, admin),
                              media_type="application/x-ndjson")
```

Note: `db.commit()` happens once at the end (matching current behaviour) so a mid-batch crash
still rolls back cleanly; only the HTTP response is incremental, not the DB write.

### Step 2 — Frontend: consume the stream

In `frontend/app-admin.js`, replace the current `bulkAddPlayers()` implementation (a plain
`await fetch(...).then(r => r.json())`) with a reader loop:

```js
async function bulkAddPlayers(csv) {
  const res = await fetch(`${API}/admin/players/bulk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ player_ids: csv }),
  });
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let summary = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();  // last (possibly incomplete) line stays in buffer
    for (const line of lines) {
      if (!line) continue;
      const evt = JSON.parse(line);
      if (evt.done) { summary = evt; } else { renderBulkAddProgress(evt); }
    }
  }
  return summary;
}
```

`renderBulkAddProgress(evt)` updates the row for `evt.id` in the progress panel (status +
reason) and the "X of N processed" counter from `evt.index`/`evt.total`.

### Step 3 — Frontend: popup markup and single-add pending state

In `frontend/index.html`, add a progress list (`<ul id="bulkAddProgress">` or a small table) and
a counter element inside the existing Bulk Add popup, hidden until Confirm is clicked. Add a
spinner/disabled state to the Add Player popup's Confirm button.

In `frontend/app-admin.js`, wire `addPlayer(playerId)` to disable the Confirm/Close controls
and show a loading label before calling `fetch`, re-enabling them in a `finally` block.

---

## Verification
- Bulk-add a CSV of 5-10 real OpenDota IDs (mix of new, already-existing, and invalid) —
  progress rows appear one at a time in order, each settling into added/skipped/error, and the
  "X of N" counter advances with each line
- Simulate an OpenDota failure (e.g. temporarily point `OPEN_DOTA_URL` at an unreachable host
  for one ID, or use a known-bad ID) — that row shows an error status and reason, and the
  remaining IDs still process
- Confirm the final summary line matches the pre-existing `{"added": N, "skipped": [...]}`
  shape, and the player pool table refreshes with the newly added rows once the stream ends
- Confirm `admin_player_bulk_added` appears exactly once in the audit log per batch (not once
  per ID) when at least one player was added
- Single Add Player: click Confirm and verify the button shows a pending state and cannot be
  clicked twice before the response returns
- Run `cd backend && python -m pytest tests/ -v` — existing and updated tests pass
