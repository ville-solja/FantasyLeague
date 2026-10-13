# Uniform Twitch Starter Tokens

Every Twitch account brings its starter tokens exactly once, and every website account receives at most one Twitch starter, whichever path the player takes: joining in the Twitch panel, or connecting Twitch on the website. Resolves GitHub issue #187.

Code: `backend/soft_accounts.py` (`starter_grant_hash`, `record_starter_grant`, `has_received_twitch_starter`, `starter_bonus_received`, Join, `merge_soft_into`, `reverse_merge`), `backend/twitch_oauth.py` (`connect_bonus_tokens`, `connect_account`, `connection_status`, `merge_confirm`), `backend/migrate.py` (`_m038_twitch_starter_grants_backfill`), `frontend/app-profile.js` (`_TWITCH_RETURN_MESSAGES.connected_bonus`, `_starterDeductedNote`).

---

## Paths

| Path | Website starter | Twitch starter | Total (defaults) |
|---|---|---|---|
| Website account, then Connect Twitch (no panel collection) | `INITIAL_TOKENS` | the Twitch starter bonus (`TWITCH_CONNECT_BONUS_TOKENS`) on connect | 10 |
| Website account, Join in the panel, then Connect and merge | `INITIAL_TOKENS` | the soft account's starter, moved by the merge | 10 |
| Website account, Connect Twitch (bonus), and later a panel collection is merged | `INITIAL_TOKENS` | the Twitch starter bonus; the merge leaves that many of the soft account's tokens behind | 10 |

Before #187 the first path ended at 5: `connect_account` stored the Twitch id and granted nothing.

## Grant record

`twitch_starter_grants` (new table, `create_all`) holds one row per Twitch account:

| Column | Meaning |
|---|---|
| `twitch_id_hash` | HMAC-SHA256 (hex) of the Twitch user id, unique, not null. Never the id itself |
| `user_id` | Account that got the starter (no foreign key: the soft account it names may be deleted later) |
| `source` | `join` (the starter came with the panel's Join) or `connect` (Connect Twitch paid the Twitch starter bonus) |
| `amount` | Tokens credited, on `connect` rows; NULL on `join` rows |
| `granted_at` | Unix time |

**Hash.** `soft_accounts.starter_grant_hash(twitch_id)` keys HMAC-SHA256 with a key derived from `SECRET_KEY` (the local-dev fallback `dev-secret-change-me` when unset, as in `main.py`). The row survives Disconnect, Leave, admin deletion and retention, which otherwise remove the Twitch ids (see `frontend/privacy.html`, "Data retention and deletion"); the hash can't be turned back into the id. **Rotating `SECRET_KEY` changes every hash, so the once-per-Twitch-account check starts over** (the once-per-website-account check below still holds, since it uses `user_id`).

`soft_accounts.record_starter_grant(db, twitch_id, user_id, source, amount=None) -> bool` runs `INSERT … ON CONFLICT DO NOTHING` and returns `True` only when it added the row (`rowcount == 1`), the #185 claim pattern.

- **Join:** a soft account records `join` when it is created with the identity share (`get_or_create_soft_account`), or when its Twitch id becomes known later (`record_twitch_account_id`). A website account that gets an id through the panel records nothing. If the id already has a row (for example a `connect` row), nothing changes.
- **Connect:** `connect_account` returns `connected_bonus` when it stores the id with no soft account holding it, `TWITCH_CONNECT_BONUS_TOKENS` is above 0, the website account never received a Twitch starter (`has_received_twitch_starter`: no `connect` row with its `user_id`, and `merged_soft_account_at` unset), and the `connect` row was added. It then credits the Twitch starter bonus with `database.credit_tokens` and audits `twitch_starter_bonus` (`user_id=… amount=…`, never the Twitch id), all in the connect's single commit. Otherwise it returns `connected` and records no row, so a Twitch account refused because of the website account can still earn the bonus on another website account. A `merge_ready` connect grants nothing: the soft account's starter arrives with the merge, and stays in the panel if the merge never happens.
- Only `connect` rows count for the website-account check: `join` rows name soft-account ids, which SQLite can hand to a later account after the soft account is deleted.
- Rows are never deleted: disconnect, reconnecting to the same or another website account, a merge reversal and soft-account deletion all leave them. Two simultaneous callbacks for one id credit once; the unique column decides.
- The partial unique index `ux_twitch_starter_grants_connect_user` (`user_id` WHERE `source = 'connect'`, on the model and created by migration 038's create path too) allows one `connect` row per website account, so two different Twitch accounts connecting to one website account at the same time credit once. The insert is `ON CONFLICT DO NOTHING` without a target, which covers both unique constraints; a refused insert means no Twitch starter bonus.

## Merge after a Twitch starter bonus

A soft account that joined without the identity share has no row. If its owner connects on the website first, the connect pays the Twitch starter bonus; a later identity share makes the soft account the pending merge. The same applies when the website account got the bonus for a different Twitch account earlier. The merge then takes the bonus back in full, so the account still ends with one Twitch starter, even when the soft account's starter was spent on cards:

- `soft_accounts.merge_token_split(soft_tokens, website_tokens, deduct)` with `deduct = starter_bonus_received(db, website_user_id)` (the `amount` of the account's `connect` row): first `from_soft = min(soft tokens, deduct)`, then `from_website = min(website balance, deduct - from_soft)`. The website account gains `soft tokens - from_soft - from_website`, which can be negative, and never goes below 0.
- `merge_soft_into` takes SQLite's write lock with a no-op `UPDATE` of the website row, then reads the bonus received and both balances under it (from `merge_confirm`, `expect_pending=True` also re-checks there that the website account still waits for this soft account and hasn't merged; otherwise `SoftAccountGone`, answered 404), and applies the change in one relative `UPDATE … SET tokens = COALESCE(tokens, 0) + :delta`. `from_soft` is zeroed and deleted with the soft account.
- `twitch_account_merged` audit detail has `starter_deducted=N from_website=M` (N = `from_soft + from_website`, what was actually taken).
- `POST /twitch/merge/confirm` returns `{merged, cards, tokens, starter_deducted, from_website}`. `GET /twitch/connection`'s `pending_merge` is `{cards, tokens, starter_deducted, balance_change}`: `tokens` is what the collection adds, `balance_change` the net change, negative when the merge removes tokens.
- Profile's prompt adds "Adding it removes N tokens from your balance: this account already received the Twitch starter bonus, and the collection's starter tokens were spent." when `balance_change` is negative, otherwise "(N Twitch starter tokens stay behind: this account already received the Twitch starter bonus.)" when tokens stay behind. After the merge: "… tokens added. M tokens were removed from your balance: this account already received the Twitch starter bonus." when `from_website > 0`, otherwise the same stay-behind note.
- The undo log's snapshot keeps the soft account's whole balance and `starter_from_website`. `reverse_merge` gives the recreated soft account its whole balance back, takes `tokens_moved` from the website account (never below 0, shortfall reported as before) and gives back `starter_from_website`. The `twitch_merge_reversed` audit has `starter_restored=` (the part taken from the soft tokens) and `from_website=`; the reply has `starter_restored` and `from_website_restored`. Merge, reverse and merge again ends where the first merge did.

## Backfill

Migration `038_twitch_starter_grants_backfill` (data only, one transaction; it creates the table first when `create_all` hasn't):

1. `join` rows for every soft account holding a Twitch id, every website account holding an id that merged a soft account (`merged_soft_account_at`) or has one waiting (`pending_merge_user_id`), and every id in the `twitch_merge_log` snapshots (merged, then disconnected).
2. For each other website account holding an id (no merge, nothing waiting, no `connect` row yet) whose Twitch account has no row: a `connect` row and `TWITCH_CONNECT_BONUS_TOKENS` (relative update), with one `twitch_starter_bonus` audit entry each (`migration=038 user_id=… amount=…`, actor `system`). At most one credit per website account.
3. Logs `Migration 038: credited the Twitch starter bonus (N tokens) to M account(s)`.

Rows hold the hash, computed with the `SECRET_KEY` the server starts with. The migration registry runs it once; the grant rows also make a direct second run credit nothing. With `TWITCH_CONNECT_BONUS_TOKENS=0` at migration time the `join` rows are recorded, nobody is credited, and the migration still counts as applied.

## Profile

`GET /config` returns `twitch_connect_bonus_tokens`. Profile maps `connected_bonus` to "Twitch connected. You received N Twitch starter tokens." with N from it, or "Twitch connected. You received your Twitch starter tokens." when the value isn't a positive integer. The header balance comes from `GET /me` on the same page load.

## Known gaps

- Join doesn't check grants: a Twitch account whose Twitch starter bonus was paid, then disconnected, can still Join in the panel and get the soft-account starter (Join's starter is unchanged by #187). If that soft account is later merged into the same website account, the merge takes the bonus back. Collecting the bonus again elsewhere needs a different website account each time (one Twitch starter per website account), and each Twitch account only earns the bonus once.
- Both balances spent before the merge (accepted, left for a product decision): when the soft account's starter and the website account's balance (bonus included) were both spent on cards before the merge, there is nothing left to take back, so `starter_deducted` can be 0 and one website account ends up with both starters as cards. Closing this would need a debt mechanism (a negative balance, or a hold against future token grants).
- After a merge the undo log (`twitch_merge_log.soft_snapshot`) keeps the raw Twitch user id for up to 30 days, as before #187; only `twitch_starter_grants` is hashed.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `TWITCH_CONNECT_BONUS_TOKENS` | `INITIAL_TOKENS` (5) | Tokens of the Twitch starter bonus, credited once per Twitch account and once per website account when Twitch is connected on the website without a panel collection. `0` turns it off (nothing credited or recorded); negative values are clamped to 0, so they also turn it off. Invalid (non-integer) values fall back to the default. |
| `SECRET_KEY` | (required outside dev) | Also keys the `twitch_starter_grants` hash; rotating it resets the once-per-Twitch-account check |
