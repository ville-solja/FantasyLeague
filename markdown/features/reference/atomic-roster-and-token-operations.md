# Atomic Roster and Token Operations

How player state changes stay correct when requests arrive at the same moment: double clicks, two tabs, the Twitch panel and the website together. Resolves GitHub issue #185. Extends the roster limit race fix (#125) and `spend_tokens`.

---

## Rules

- **Check and change in one statement.** A guard that decides whether a change may happen is part of the change itself: a conditional `UPDATE … WHERE …` or `INSERT … SELECT … WHERE …`, followed by a check of `rowcount`. A separate `SELECT` followed by a write is a race.
- **Balances change relatively.** Use `tokens = tokens + :n` / `tokens - :n` in SQL (`credit_tokens`, `spend_tokens`), never `user.tokens = <value read earlier>`. A test fails when a file under `backend/` (outside `database.py` and the tests) assigns `.tokens =` or `.tokens +=`.
- **Constraints are the backstop.** Invariants a constraint can express are enforced by the database: unique claims, one redemption per user, one active card per player per roster.
- **The client lock is a courtesy.** Buttons are disabled while their request runs, but the server never relies on it.
- **Rate limits (#184) reduce bursts but do not replace atomicity.**

SQLite runs one write transaction at a time, so a single conditional statement is atomic with respect to other requests. A transaction holds the write lock from its first write until it commits, so reads after that first write see a value no other request can change before the commit. `merge_soft_into` and `reverse_merge` rely on this (see Token credits).

## Draw activation

`draw_card` and `draw_booster` (`backend/routers/cards.py`) insert the new card on the bench, then call `_activate_new_card`, which runs `_activate_card_atomic(db, card.id, user_id, card.player_id, ROSTER_LIMIT)`: one `UPDATE` that activates the card only while the owner has fewer than `ROSTER_LIMIT` active cards and no other active card of the same player. When it returns `False` the card stays on the bench and the draw still succeeds. The response's `is_active` is that result. The Twitch panel's draws (`twitch.draw`, `twitch.draw_team`) call the same functions.

Before #185 a drawn card was activated whenever fewer than `ROSTER_LIMIT` cards were active, without the duplicate-player check, so a draw could put a second card of one player into the roster.

## Roster swap

`_swap_roster_atomic` (`backend/card_utils.py`) benches the outgoing card first, with `WHERE … AND is_active = 1`, and stops (`False`) when that changed no row; the route rolls back and answers 404 "Card not found", as its own zone check does. Only then does it activate the bench card, with the duplicate-player check in the same `UPDATE`.

Before #185 the order was reversed and the outgoing card's `rowcount` was not checked. Two swaps onto the same roster card at once (a double drop, two tabs) both passed the route's checks; the second activated its bench card without benching anything, so each extra swap added a card beyond the limit. The order also matters for the unique index below: activating a bench card of the same player while the outgoing card is still active would violate it.

## One active card per player

Migration `037_cards_active_player_unique` (`backend/migrate.py`), skipped when the index already exists (new databases get it from `create_all`, declared in `models.py` with `sqlite_where`):

1. **Repair.** Per owner, ranks active cards by `slot_index IS NULL, slot_index, id` (window functions). First it moves active duplicates of a player (rank > 1 within `owner_id, player_id`) to the bench, then active cards ranked beyond `ROSTER_LIMIT` within `owner_id`. Benched cards get `is_active = 0, slot_index = NULL`. `ROSTER_LIMIT` is read from the environment (default 5), like `routers/cards.py`.
2. **Report.** Logs `Migration 037: moved N card(s) of M user(s) to the bench` and writes one audit entry per affected user: action `roster_repair_benched`, actor `system`, detail `migration=037 user_id=<id> card_ids=<ids>`.
3. **Index.** `CREATE UNIQUE INDEX ux_cards_owner_player_active ON cards (owner_id, player_id) WHERE is_active = 1`.

`weekly_roster_entries` (locked-week snapshots) is never touched. The roster count limit can't be an index; it stays in the atomic `UPDATE`.

`activate_card` and `swap_roster` turn an `IntegrityError` from the index into the existing 409 `"A card for this player is already active"`.

Before deploying, take a backup (`bash scripts/backup-db.sh`) and check the repair count in the startup log on a copy of the production database; expect zero or a handful of rosters, and review the `roster_repair_benched` audit entries.

## Token credits

`credit_tokens(db, user_id, amount)` in `backend/database.py`, next to `spend_tokens`:

```sql
UPDATE users SET tokens = COALESCE(tokens, 0) + :amt WHERE id = :uid
```

An unknown `user_id` changes nothing. It bypasses the ORM identity map; callers `db.refresh(user)` when they return the balance.

| Credit | Where | How |
|---|---|---|
| Event claim | `routers/auth.py` `claim_events` | Per event, `INSERT … ON CONFLICT (event_id, user_id) DO NOTHING` into `token_grant_claims`, then `credit_tokens` only when that inserted the row. Returns `{granted, tokens}`. A simultaneous claim never fails and never double-credits |
| Promo redeem | `routers/admin_users.py` `redeem_code` | `credit_tokens` after the conditional insert (below) |
| Admin grant | `routers/admin_users.py` `grant_tokens` | `credit_tokens` |
| MVP token drop | `twitch.py` `_execute_token_drop` | `credit_tokens` per winner |
| Weekly lock grant | `weeks.py` `auto_lock_weeks` | One `UPDATE users SET tokens = coalesce(tokens, 0) + 1 WHERE id IN (…)` |
| Player-removal refund | `routers/admin_players.py` `remove_players` | `UPDATE players SET is_active = 0 WHERE id = :pid AND is_active = 1`; only when that changed the row, `credit_tokens` per owner. Two simultaneous removes refund once |
| Soft-account merge | `soft_accounts.py` `merge_soft_into` | `UPDATE … SET tokens = COALESCE(tokens, 0) + COALESCE((SELECT COALESCE(tokens, 0) FROM users WHERE id = :soft), 0)` on the website account, then the soft balance is read (the write lock is held) for the log, then zeroed. When the soft row is already gone (a simultaneous merge won), it raises `SoftAccountGone`; `POST /twitch/merge/confirm` rolls back and answers 404 "That Twitch collection is gone; refresh the page" |
| Merge reverse | `soft_accounts.py` `reverse_merge` | After the new soft account's insert holds the write lock: read the balance, `taken = min(balance, tokens_moved)`, `UPDATE … SET tokens = COALESCE(tokens, 0) - :taken`. The shortfall is reported as before |

## Promo use cap

`redeem_code` checks the code exists and has not expired (`_code_open`, now expiry only), and that this user has not redeemed it (409 `"Code already redeemed"`). It then inserts the redemption with:

```sql
INSERT INTO code_redemptions (code_id, user_id, redeemed_at)
SELECT :code_id, :user_id, :now
WHERE :max IS NULL
   OR (SELECT COUNT(*) FROM code_redemptions WHERE code_id = :code_id) < :max
```

`rowcount` 0 means the cap is reached: 404 `INVALID_CODE_DETAIL` ("Invalid or expired code"). An `IntegrityError` on the unique `(code_id, user_id)` constraint (the same user redeeming twice at once) answers 409. Tokens are credited only after a successful insert, in the same transaction.

A user who already redeemed a code that has since reached its cap now gets 409 rather than 404, since the cap is checked at the insert.

## Website in-flight guards

`withBusy(btn, fn)` in `frontend/app-globals.js` returns at once when `btn` is disabled, disables it, awaits `fn` and re-enables it in `finally`, also when `fn` throws. With no button it just runs `fn`. A render that should leave a button disabled (no tokens, picker closed) runs after it returns.

| Action | Handler | Guard |
|---|---|---|
| Draw | `drawCard` (`app-cards.js`) | `withBusy(#drawBtn)` |
| Team draw | `drawBooster` | `withBusy(#boosterDrawBtn)`; the picker closes afterwards |
| Repeat team draw from the reveal | `_drawBoosterForTeam` | `_boosterDrawInFlight` flag (no button) |
| Reroll confirm | `confirmReroll` | `withBusy(#rerollConfirmBtn)` |
| Activate / deactivate (Enter or Space on a card) | `activateCard`, `deactivateCard` (`app-roster.js`) | `_withRosterMutationGuard` + `withBusy` on the card image |
| Drag-and-drop swap, reorder, bench, activate | drop handlers in `_initDragAndDrop` | `_rosterBusy` flag: every drop handler returns early while set |
| Redeem | `redeemCode` | `withBusy(#redeemBtn)` |
| Weekly Report "Reveal results" | `revealAllWeeklySummaries` (`app-weekly-summary.js`) | `withBusy(#weeklySummaryRevealBtn)` |

Errors still show through `setStatus` / `textContent`. The Twitch panel's buttons already locked.

## Inventory

| Operation | How it is safe |
|---|---|
| Spend tokens (draws, rerolls) | `spend_tokens`: conditional `UPDATE` |
| Activate | `_activate_card_atomic`: conditional `UPDATE` (#125) |
| Swap | `_swap_roster_atomic`: bench the outgoing card only if still active, then conditional activate |
| Draw / team draw auto-activate | `_activate_card_atomic` |
| Duplicate active player | Partial unique index `ux_cards_owner_player_active` |
| Token credits | `credit_tokens` / relative bulk `UPDATE` |
| Event claim | Unique `(event_id, user_id)` + `INSERT … ON CONFLICT DO NOTHING`, credit only on insert |
| Player removal refund | Conditional `UPDATE players … WHERE is_active = 1` |
| Soft-account merge | Relative updates; abort when the soft row is gone |
| Promo redemption | Unique `(code_id, user_id)`; cap via conditional `INSERT … SELECT … WHERE` |
| MVP token drop | Unique `(channel_id, series_id)` |
| Twitch MVP per match | Unique `match_id` |
| Notification dismiss, Weekly Report seen/reveal | Unique rows / idempotent |
| Deactivate, reorder | Idempotent single-row updates |

## Tests

`backend/tests/test_issue_185_atomic_roster_and_token_operations.py`. The concurrency tests use a file-based SQLite database in WAL mode, one session per thread and a `threading.Barrier` releasing all threads at once: concurrent draws, team draws, Twitch panel draws, a draw racing activations, swaps onto one roster card, credits racing spends and draws, a merge racing spends, two merges of one soft account, event claims racing each other, simultaneous removes of one player, and 20 users redeeming a code capped at 5.

A draw inserts the card before it activates it, so the insert already holds SQLite's write lock and draws were serialised before #185 as well: the concurrent draw tests guard the invariant rather than reproduce an old failure. The swap test does reproduce one: with the old swap order, all six concurrent swaps succeeded.
