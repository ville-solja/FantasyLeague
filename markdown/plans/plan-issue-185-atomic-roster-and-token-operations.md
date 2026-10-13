# Plan: Atomic Roster and Token Operations

## Context
A tester got more cards into the active roster than the limit allows by acting quickly.

**The roster cause** *(corrected after implementation)*. The overfill came from the roster swap: `_swap_roster_atomic` activated the bench card before benching the outgoing card and never checked that the outgoing card was still active, so concurrent swaps onto one roster card (a double drop, two tabs) each added a card. Draws turned out to be serialised already, because the new card's insert takes SQLite's write lock before the count. The planning text below describes the draw path as first suspected; the draw duplicate-player gap it names was real and is fixed.

*As first planned:* Explicit roster changes are already atomic: `activate_card` and `swap_roster` use single conditional `UPDATE`s (`card_utils._activate_card_atomic` / `_swap_roster_atomic`, #125). But `draw_card` and `draw_booster` (`backend/routers/cards.py`) auto-activate the new card with a separate count and assignment:
```python
active_count = db.query(Card).filter(Card.owner_id == user_id, Card.is_active == True).count()
card.is_active = active_count < ROSTER_LIMIT
```
So two quick draws, or a draw and an activation, both read four active cards, and both activate. This auto-activation also skips the duplicate-player check. The Twitch panel's draws call the same functions.

**A sweep of other state changes found three more read-then-write patterns:**
- **Token credits:** event claims, promo codes, admin grants, MVP drops, weekly grants, player-removal refunds and the two soft-account merge paths all write `user.tokens = (user.tokens or 0) + n` through the ORM. That writes back a value read earlier, so a concurrent atomic `spend_tokens` (a draw) between the read and the write is overwritten: a spend or a credit is lost.
- **Promo use cap:** promo codes check `max_redemptions` with a count, then insert. Different users redeeming at the same moment can exceed the cap; only one redemption per user is enforced by a unique constraint.
- **Website buttons:** draw, booster, roster and redeem buttons don't lock while their request runs, so a double click sends two requests. The Twitch panel's buttons already lock.

**Practice this plan adopts:**
- The server is the source of truth. Every check that guards a change happens in the same statement as the change: a conditional `UPDATE … WHERE` or `INSERT … SELECT … WHERE`, with `rowcount` checked.
- Database constraints are the backstop for invariants that can be expressed that way.
- Balance changes use relative SQL (`tokens = tokens + :n`), never values read earlier.
- The client locks a button while its request runs. That is for usability only, never relied on for correctness.
- The #184 rate limits reduce bursts but don't prevent races.

SQLite runs one write transaction at a time, so a single conditional statement is atomic with respect to other requests.

Resolves GitHub issue #185.

## User Stories

### Draws Never Overfill the Roster
**User story**
As a player, I want a newly drawn card to join my active roster only when there is room and no other active card has the same player, so that fast draws can't push my roster past the limit or give me duplicates.

**Acceptance criteria**
- `draw_card` and `draw_booster` activate the new card only through `_activate_card_atomic` (roster count and duplicate-player check in the same `UPDATE`); if it returns `False`, the card stays on the bench and the draw still succeeds
- Ten concurrent draws for a player with an empty roster leave exactly `ROSTER_LIMIT` active cards, never more, and no two active cards with the same `player_id`
- A draw running concurrently with `POST /roster/{card_id}/activate` never leaves more than `ROSTER_LIMIT` active cards
- The Twitch panel's draw and booster draw (which call the same functions) get the same guarantee
- The draw response's `is_active` reflects what was actually stored

### The Database Refuses Duplicate Active Players
**User story**
As the operator, I want the database itself to refuse two active cards for the same player in one roster so that no future code path can bring the duplicate back.

**Acceptance criteria**
- A numbered migration repairs existing data first. Per owner, it deactivates extra active cards beyond `ROSTER_LIMIT`, and active duplicates of the same player, keeping the lowest `slot_index`, then the lowest `id`. It logs how many cards it moved to the bench, and writes an audit entry per affected user.
- The same migration then creates the partial unique index `ux_cards_owner_player_active ON cards(owner_id, player_id) WHERE is_active = 1`
- Any write that would create a second active card for the same owner and player fails with an integrity error. Routes turn it into the existing 409 "A card for this player is already active", never a 500.
- Weekly roster snapshots (`weekly_roster_entries`) of locked weeks are not changed by the repair

### Token Balances Change Atomically
**User story**
As a player, I want every token credit and spend applied as one database operation so that a reward arriving while I draw never makes tokens disappear or reappear.

**Acceptance criteria**
- A `credit_tokens(db, user_id, amount)` helper next to `spend_tokens` runs `UPDATE users SET tokens = COALESCE(tokens, 0) + :amount WHERE id = :uid`
- All eight ORM credits use it, or an equivalent relative update in bulk paths:
  - event claims (`routers/auth.py`)
  - promo redeem and admin grant (`routers/admin_users.py`)
  - MVP token drops (`twitch.py`)
  - weekly lock grants (`weeks.py`)
  - player-removal refunds (`routers/admin_players.py`)
  - the soft-account merge and reverse (`soft_accounts.py`)
- The merge moves the soft account's balance in one transaction with relative updates. It must not read the balance, then write both rows.
- A concurrent claim and draw on one account end with balance = start + credit − spend
- A test fails if any file under `backend/` (outside `database.py` and tests) assigns `.tokens =`

### Promo Codes Respect Their Use Cap Under Load
**User story**
As an admin, I want a promo code with a use cap to stop at exactly that many redemptions even when many players redeem it at once.

**Acceptance criteria**
- The redemption row is inserted with one `INSERT … SELECT … WHERE` that counts existing redemptions of the code below `max_redemptions` (unlimited when `NULL`); tokens are credited only when that insert's `rowcount` is 1
- Twenty concurrent redemptions of a code capped at 5, by different users, give exactly 5 redemptions and 5 credits; the rest get the existing 404 "invalid code" answer
- One user redeeming twice still gets the existing 409 "Code already redeemed"

### Concurrent Swaps Never Overfill the Roster
**User story**
As a player, I want two swaps onto the same roster card (a double drop, two tabs) to make exactly one change so that my roster never grows past the limit.

**Acceptance criteria**
- `_swap_roster_atomic` benches the outgoing card first, only while it is still active, and stops when that changes no row; only then does it activate the bench card, with the duplicate-player check in the same `UPDATE`
- Of several concurrent swaps onto one active card, exactly one succeeds; the others answer 404 "Card not found" and change nothing
- The roster never holds more than `ROSTER_LIMIT` active cards after concurrent swaps (`test_concurrent_swaps_onto_one_active_card_never_overfill`, which fails on the pre-#185 order)

### Website Actions Wait for Their Answer
**User story**
As a player, I want a button to stay disabled until its action finishes so that a double click doesn't send the same action twice.

**Acceptance criteria**
- Draw, booster draw, reroll confirm, activate, deactivate, swap (drag), reorder, redeem and Weekly Report reveal buttons are disabled from the click until the response is handled, then re-enabled. They stay disabled where the new state calls for it, e.g. no tokens.
- A second click during the request sends no second request
- A failed request re-enables the button and shows the error
- Roster drag-and-drop ignores new drops while a swap or reorder request is running

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/routers/cards.py` | `draw_card`, `draw_booster` activate via `_activate_card_atomic`; integrity errors → 409 in activate/swap |
| `backend/card_utils.py` | `_swap_roster_atomic`: bench the outgoing card first (checked `rowcount`), then activate the bench card (the actual overfill fix) |
| `backend/database.py` | `credit_tokens(db, user_id, amount)` |
| `backend/routers/auth.py`, `routers/admin_users.py`, `routers/admin_players.py`, `twitch.py`, `weeks.py`, `soft_accounts.py` | Replace ORM token arithmetic with `credit_tokens` / relative updates |
| `backend/routers/admin_users.py` | Promo redemption as a conditional insert |
| `backend/migrate.py` | Migration `037_cards_active_player_unique`: repair, then the partial unique index |
| `backend/models.py` | Declare the partial index (`Index(..., unique=True, sqlite_where=...)`) so new databases get it |
| `frontend/app-cards.js`, `frontend/app-roster.js`, `frontend/app-roster.js` (redeem), `frontend/app-weekly-summary.js` | In-flight guards |
| `backend/tests/test_issue_185_atomic_roster_and_token_operations.py` | Concurrency and static tests |
| `markdown/features/reference/atomic-roster-and-token-operations.md` | The pattern, the inventory, the migration |

### Step 1 — Draw activation
After `db.flush()` of the new card, call `_activate_card_atomic(db, card.id, user_id, player.id, ROSTER_LIMIT)`. Set the response's `is_active` from its result; `db.refresh(card)` if the ORM object is used afterwards. Remove the count and assignment in both functions.

### Step 2 — Partial unique index and repair (migration 037)
In `run_migrations()`, guarded by `PRAGMA index_list(cards)`:
1. Repair per owner with window functions (SQLite ≥ 3.25): rank active cards by `(slot_index IS NULL, slot_index, id)`, and set `is_active = 0` for duplicates of a player (rank > 1 within `(owner_id, player_id)`), then for ranks beyond `ROSTER_LIMIT` within `owner_id`. Read `ROSTER_LIMIT` from the environment like `routers/cards.py`.
2. Log the count, and write an audit entry per affected user.
3. `CREATE UNIQUE INDEX ux_cards_owner_player_active ON cards(owner_id, player_id) WHERE is_active = 1`.

Declare the same index in `models.py` for `create_all`. `tests/test_migrate.py` must still pass. The roster count limit can't be an index; it stays in the atomic `UPDATE`.

### Step 3 — Atomic token credits
```python
def credit_tokens(db, user_id: int, amount: int) -> None:
    db.execute(text("UPDATE users SET tokens = COALESCE(tokens, 0) + :amt WHERE id = :uid"),
               {"amt": amount, "uid": user_id})
```
- **Callers:** replace each `user.tokens = (user.tokens or 0) + n` with `credit_tokens(...)`, then `db.refresh(user)` where the value is returned.
- **Merge:** in the same transaction, add the soft account's tokens to the full account with `UPDATE … SET tokens = tokens + (SELECT tokens FROM users WHERE id = :soft)`, then zero the soft account. Reverse with relative updates.
- **Weekly grants:** one `UPDATE … WHERE id IN (…)`.
- **Guard test:** grep `backend/**/*.py` (excluding `database.py` and `tests/`) for `.tokens =` / `.tokens +=`.

### Step 4 — Promo redemption
```sql
INSERT INTO code_redemptions (code_id, user_id, redeemed_at)
SELECT :code_id, :user_id, :now
WHERE :max IS NULL OR (SELECT COUNT(*) FROM code_redemptions WHERE code_id = :code_id) < :max
```
If `rowcount` is 0, answer 404 with `INVALID_CODE_DETAIL`. An `IntegrityError` on the per-user unique constraint keeps answering 409. Credit only after a successful insert.

### Step 5 — Frontend in-flight guards
Add a small helper in `app-globals.js`:
```js
async function withBusy(btn, fn) { if (!btn || btn.disabled) return; btn.disabled = true; try { return await fn(); } finally { btn.disabled = false; } }
```
Use it for the listed actions. Where the follow-up render sets the disabled state (no tokens, booster complete), let that render run after `finally`. For drag-and-drop in `app-roster.js`, set a `_rosterBusy` flag and ignore drops while it is set.

### Step 6 — Tests
`backend/tests/test_issue_185_atomic_roster_and_token_operations.py`:
- **Setup:** use a file-based SQLite database in `tmp_path` with WAL, not in-memory `StaticPool` (one shared connection can't show races). Start N threads, each with its own session, all released at once by a `threading.Barrier`, calling the plain functions (`draw_card`, `activate_card`, `redeem_code`, `credit_tokens` + `spend_tokens`).
- **Roster:** after concurrent draws, at most `ROSTER_LIMIT` active cards and no duplicate active players.
- **Index:** the index refuses a duplicate active player.
- **Migration:** repairs a seeded over-limit roster with duplicates, as expected.
- **Tokens:** the balance after a concurrent credit and spend is exact; the promo cap holds under 20 concurrent users.
- **Static checks:** no `.tokens =` assignments; in-flight guards present in the frontend handlers.
- **Suite size:** keep `test_issue_85_split_admin_router.py`'s baseline in step.

### Step 7 — Documentation
`markdown/features/reference/atomic-roster-and-token-operations.md`:
- the pattern and rules from the Context, written for the next developer;
- an inventory of state-changing player operations and how each is made safe: atomic `UPDATE`, conditional `INSERT`, unique constraint, or idempotent;
- the migration and its repair rule.

Update `markdown/features/core/cards.md` (draw activation rule), `markdown/stories/team-tokens-scoring.md` and `markdown/lessons-learned.md`.

## Verification
- **Tests:** `cd backend && python3 -m pytest tests/ -q`, including the threaded concurrency tests (repeat them a few times locally; they must never flake).
- **Manual:** on test, with an empty roster, click Draw as fast as possible: never more than `ROSTER_LIMIT` active cards and the button ignores clicks while drawing. Repeat from two tabs at once.
- **Migration:** on a copy of the production database (`scripts/backup-db.sh` first), check the repair count before deploy. Expect zero or a handful of rosters; review the audit entries.
- **Promo cap:** a capped promo code stops at its cap when redeemed from several accounts at once.
