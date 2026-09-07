# Admin Player Add Progress

Live progress reporting for the admin Player Pool "Bulk Add" flow, plus a pending-state
indicator on the single "Add Player" popup, so admins can see each outbound OpenDota lookup
and its outcome as a batch add runs instead of waiting silently for the whole request.

---

## Concept

`POST /admin/players/bulk` (see `admin-player-pool.md`) processes a comma-separated list of
OpenDota account IDs one at a time, each requiring a network round-trip to OpenDota. A batch of
a dozen or more IDs — especially under OpenDota rate limiting — can take long enough that the
admin has no way to tell the request is progressing rather than hung.

This feature streams a result per ID as soon as it is resolved, so the frontend can render a
live progress panel (per-ID status: pending/added/skipped/error) and a running "X of N
processed" counter, rather than blocking on the full batch. The single-player Add Player flow
gets a lighter-weight pending/loading state on its Confirm button for the same reason, without
a streaming response (there is only one item to process).

## Endpoints

### `POST /admin/players/bulk`
Implemented in `backend/routers/admin_players.py`. Signature unchanged
(`body: BulkAddPlayersBody, db=Depends(get_db), admin=Depends(require_admin)`), but the handler
now returns `StreamingResponse(_bulk_add_stream(raw_ids, db, admin), media_type="application/x-ndjson")`
instead of a buffered JSON object. `_bulk_add_stream()` is a generator performing the same
per-ID logic as before (integer parsing, existing-ID dedupe, OpenDota lookup via
`opendota_get_json`, `Player` insert), `yield`ing a JSON line after each ID resolves:

- One line per input ID: `{"id": ..., "status": "added"|"skipped"|"error", "reason": "...", "index": i, "total": N}`
  (`reason` is present on `skipped`/`error` lines only; `index`/`total` drive the "X of N
  processed" counter)
- A final summary line: `{"done": true, "added": N, "skipped": [...]}`, preserving the shape of
  the original non-streaming response for any caller that only reads the last line

Each successful insert is committed immediately, right after its `added` line is yielded —
not batched to a single commit at the end. This matters because the stream is tied 1:1 to the
live HTTP request: if the admin closes the browser tab (as opposed to just closing the popup,
which does not abort the underlying `fetch` — see Frontend below) mid-batch, Starlette cancels
the generator once the in-flight ID finishes, and processing does not resume for the remaining
IDs. Per-item commits mean only that unprocessed tail is lost, not the players already reported
as "added". The `admin_player_bulk_added` audit event is still recorded once per batch (at the
final commit), so an interrupted batch has committed `Player` rows but no matching audit entry.

Both this endpoint and `POST /admin/players` call `opendota_get_json()` with a fail-fast
profile (`_INTERACTIVE_RETRIES = 2`, `_INTERACTIVE_BACKOFF = 2.0`, `_INTERACTIVE_TIMEOUT = 6.0`
in `admin_players.py`) instead of the module default (5 retries, 10s base backoff, 30s timeout)
used by the background enrichment and ingest-poll loops. Every OpenDota consumer shares one
55-req/min rate-limit budget (`opendota_client.throttle()`), and every retry attempt — even a
failing one — consumes a slot from that budget; the background loops' long exponential backoff
can otherwise starve an in-flight admin request for minutes when OpenDota is slow. The shorter
interactive profile bounds a single failing ID to a few seconds so the batch keeps moving; a
failed ID is reported as an `error` line and the admin can retry it manually.

### `POST /admin/players`
No response-contract change — see `admin-player-pool.md`. The frontend Confirm button gains a
pending/loading state while the request is in flight, and the OpenDota lookup uses the same
fail-fast retry/timeout profile described above.

## Frontend

- Bulk Add popup: a progress panel (per-ID rows + "X of N processed" counter) appears on
  Confirm and fills in as each streamed line arrives; the player pool table refreshes once the
  final summary line is received. The Confirm button and CSV input are disabled while a batch is
  streaming, so a second overlapping request can't be started against the same progress panel.
  The Cancel button is deliberately left enabled: hiding the popup does not abort the underlying
  `fetch` — `bulkAddPlayers()` keeps reading the stream and still calls `loadPlayerPool()` when it
  finishes, even while the modal is hidden. Only closing/reloading the browser tab aborts it.
- Add Player popup: Confirm button and Close action are disabled with a loading indicator while
  the single-ID request is in flight, then re-enabled on success or error

Functions in `frontend/app-admin-players.js` (the admin-players module the player pool tab
actually loads; the plan referred to this as `app-admin.js`, an older undivided name):
- `bulkAddPlayers()` — reads the CSV from `#bulkAddIdsInput`, disables `#bulkAddConfirmBtn` and
  the input for the duration of the request, shows the progress panel, and reads the streamed
  `POST /admin/players/bulk` response via `response.body.getReader()`, splitting the decoded text
  on newlines and calling `renderBulkAddProgress(evt)` for each parsed line except the final
  `{done: true, ...}` summary line, which refreshes the player pool table via `loadPlayerPool()`
  once `added > 0`; re-enables the button/input in a `finally` block
- `renderBulkAddProgress(evt)` — creates or updates the `<li data-progress-id="...">` row for
  `evt.id` in `#bulkAddProgressList` with its status/reason, and updates `#bulkAddProgressCounter`
  from `evt.index`/`evt.total`
- `_resetBulkAddProgress()` — clears the progress panel and hides it; called on popup open and
  again right before a new bulk-add request starts
- `addPlayer()` — disables `#addPlayerConfirmBtn` (label becomes "Adding…"), `#addPlayerCloseBtn`,
  and `#addPlayerIdInput` before the `POST /admin/players` call, re-enabling all three in a
  `finally` block regardless of success or error

Markup added in `frontend/index.html`:
- Bulk Add popup (`#bulkAddPlayersModal`) gained `#bulkAddConfirmBtn` on its Confirm button and
  `#bulkAddProgressPanel` (hidden by default), containing `#bulkAddProgressCounter` and the
  `#bulkAddProgressList` `<ul>`
- Add Player popup (`#addPlayerModal`)'s Confirm and Cancel buttons gained ids
  `addPlayerConfirmBtn` / `addPlayerCloseBtn` so `addPlayer()` can target them directly

## Tests

`backend/tests/test_issue_99_admin_player_add_progress.py` exercises `_bulk_add_stream`'s logic
via a replicated generator helper (`_bulk_add_players_stream`), following the same
helper-function pattern as `test_admin_player_pool.py` (FastAPI is not importable in the local
test environment). Covers: event ordering/counter correctness, continuing past an OpenDota
failure mid-batch, the full NDJSON line/summary shape plus single audit-event recording, and
invalid-integer handling — plus two tests confirming `POST /admin/players`'s success/error
response contract is unchanged.
