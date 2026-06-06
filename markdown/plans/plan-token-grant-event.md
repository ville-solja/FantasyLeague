# Plan: Token Grant Event

## Context

Promo codes distribute tokens reactively — a player must know a code exists and actively
redeem it. There is no way to push a one-time token reward to every player at once, for
example at season start, as a holiday gift, or to compensate for a service disruption.
This plan adds an admin-configured token grant event: a time-bounded window during which
every player who opens the app automatically receives a fixed token amount, with a
single-claim guard so multiple logins during the window do not multiply the reward.
Removing a live event cancels future claims but does not claw back tokens already granted.
Resolves GitHub issue #46.

---

## User Stories

### Create a Token Grant Event
**User story**
As an admin, I want to configure a one-time token grant event with a fixed amount and
active time window so that all players are automatically rewarded on their next login
during that period.

**Acceptance criteria**
- Admin tab shows a "Token Grant Events" section listing active and upcoming events
- A form accepts: token amount (integer ≥ 1), start datetime, end datetime
- Submitting calls `POST /admin/token-grant-events` and the new event appears in the list
- Validation rejects end time ≤ start time and amount < 1
- Event is logged to the audit log as `admin_token_grant_event_created`

### Claim Tokens on Login During Active Event
**User story**
As a player, I want to automatically receive my event tokens on my next page load during
an active grant window so that I do not need to take any extra action.

**Acceptance criteria**
- On any authenticated request during an active event, the backend checks whether the
  player has already claimed this event
- If not yet claimed, tokens are added and the claim is recorded
- Tokens are granted at most once per player per event regardless of how many requests
  are made during the window
- No tokens are granted for requests after the event's end time
- The grant is logged to the audit log as `token_grant_event_claim`

### Remove a Token Grant Event
**User story**
As an admin, I want to remove a configured grant event (including a live one) so that I
can cancel a mistaken configuration without penalising players who have already claimed.

**Acceptance criteria**
- Each event row has a "Remove" button that calls `DELETE /admin/token-grant-events/{id}`
- Removing a live event immediately stops new claims; already-granted tokens are kept
- The removal is logged to the audit log as `admin_token_grant_event_deleted`
- Removed events disappear from the admin list

---

## Implementation

### Critical Files

| File | Change |
|---|---|
| `backend/models.py` | Add `TokenGrantEvent` model; add `TokenGrantClaim` model |
| `backend/migrate.py` | No manual migration needed — `create_all()` handles new tables |
| `backend/routers/admin.py` | Add `POST /admin/token-grant-events`, `DELETE /admin/token-grant-events/{id}`, `GET /admin/token-grant-events` |
| `backend/routers/auth.py` | Add claim check to `GET /me` (or a new `POST /claim-events` endpoint called on load) |
| `frontend/index.html` | Add token grant events section to admin tab |
| `frontend/app-admin.js` | Render event list, create form, remove button |
| `frontend/app-init.js` | Call claim endpoint after login / on init when user is logged in |

---

### Step 1 — Models (`backend/models.py`)

```python
class TokenGrantEvent(Base):
    __tablename__ = "token_grant_events"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    amount     = Column(Integer)           # tokens to grant per player
    start_time = Column(Integer)           # Unix timestamp
    end_time   = Column(Integer)           # Unix timestamp
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(Integer)           # Unix timestamp


class TokenGrantClaim(Base):
    __tablename__ = "token_grant_claims"

    id       = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(Integer, ForeignKey("token_grant_events.id"))
    user_id  = Column(Integer, ForeignKey("users.id"))
    claimed_at = Column(Integer)           # Unix timestamp
```

Add a unique constraint on `(event_id, user_id)` to enforce single-claim at the DB level:

```python
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_claim_event_user"),)
```

---

### Step 2 — Admin endpoints (`backend/routers/admin.py`)

`GET /admin/token-grant-events` — returns all events ordered by start_time desc, with
a `claim_count` field (COUNT of TokenGrantClaim rows per event).

`POST /admin/token-grant-events` — body: `{amount: int, start_time: int, end_time: int}`.
Validates amount ≥ 1 and end_time > start_time. Inserts row. Audit log entry.

`DELETE /admin/token-grant-events/{id}` — 404 if not found. Deletes the event row.
Existing TokenGrantClaim rows are kept (orphaned by cascade). Audit log entry.

---

### Step 3 — Claim endpoint (`backend/routers/auth.py` or new router)

Add `POST /claim-events` — requires auth (`Depends(get_current_user)`):

```python
now = int(time.time())
active_events = db.query(TokenGrantEvent).filter(
    TokenGrantEvent.start_time <= now,
    TokenGrantEvent.end_time   >= now,
).all()

granted = 0
for event in active_events:
    already = db.query(TokenGrantClaim).filter_by(
        event_id=event.id, user_id=user.id
    ).first()
    if already:
        continue
    user.tokens = (user.tokens or 0) + event.amount
    db.add(TokenGrantClaim(event_id=event.id, user_id=user.id, claimed_at=now))
    db.add(AuditLog(..., action="token_grant_event_claim",
                    detail=f"event={event.id} amount={event.amount}"))
    granted += event.amount

db.commit()
return {"granted": granted}
```

The unique constraint on `token_grant_claims` acts as a race-condition guard.

---

### Step 4 — Frontend call (`frontend/app-init.js`)

After `loadMe()` confirms a logged-in user, call `POST /claim-events`. If `granted > 0`,
show a brief banner: *"You received N tokens!"* and refresh the token display.

---

### Step 5 — Admin UI (`frontend/app-admin.js` + `frontend/index.html`)

Add a "Token Grant Events" section to the admin tab:
- Table: Amount | Start | End | Claims | Actions
- "New event" form: amount input, start datetime picker, end datetime picker, Create button
- Each row: Remove button (confirms before calling DELETE)
- Datetimes displayed in local time; stored and sent as Unix timestamps

---

## Verification

- Create an event with a 5-minute window; log in as a regular user → tokens increase by
  the specified amount; audit log shows `token_grant_event_claim`
- Log in again during the same window → tokens do not increase again
- Log in after event expiry → no tokens granted
- Remove a live event → subsequent logins during the original window grant nothing
- Create an event with end_time ≤ start_time → rejected with 422
- Two simultaneous requests during an active event → exactly one claim recorded (unique
  constraint prevents double-grant)
