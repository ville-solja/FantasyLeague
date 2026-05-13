# Token Grant Event

Admin-configurable time-bounded token distribution: every logged-in player automatically
receives a fixed token amount once during the active window, with no action required on
their part.

---

## Overview

An admin creates an event with a token amount, start time, and end time. When any
authenticated player hits `POST /claim-events` during the active window, the backend
grants the tokens and records a claim. The unique claim guard prevents double-granting
regardless of how many requests are made during the window.

Removing an event cancels future claims but does not claw back tokens already granted.

---

## Endpoints

### `GET /admin/token-grant-events` Returns all events ordered by start time descending. Each row includes a `claim_count`
of players who have claimed.

### `POST /admin/token-grant-events` Body: `{ amount: int, start_time: int, end_time: int }`. Admin only. Creates a new event.
Validates amount ≥ 1, end_time > start_time.

### `DELETE /admin/token-grant-events/{id}` Admin only. Deletes the event. Existing claims and granted tokens are unaffected.

### `POST /claim-events` Auth required. Checks all currently active events, grants tokens for any unclaimed,
returns `{ granted: N }`. Called automatically on page load for logged-in users.

---

## Data model

`token_grant_events` — one row per event (amount, start_time, end_time, created_by).

`token_grant_claims` — one row per (event_id, user_id) pair; unique constraint prevents
duplicate grants at the database level.

---

## Frontend

Admin panel — "Token Grant Events" section lets admins create events (amount + datetime
pickers) and delete existing ones with a live claim count display.

`claimTokenEvents()` is called on every login, register, and page-load for logged-in
users. If `granted > 0`, the token balance is refreshed via `loadMe()`.
