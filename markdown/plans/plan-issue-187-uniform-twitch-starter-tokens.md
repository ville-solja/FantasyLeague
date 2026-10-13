# Plan: Uniform Twitch Starter Tokens

## Context
Players end up with different free tokens depending on the path they took:

| Path | Website starter | Twitch starter | Total |
|---|---|---|---|
| Website account, Join in the Twitch panel, then Connect Twitch and merge | `INITIAL_TOKENS` (5) | `INITIAL_TOKENS` from the soft account (`soft_accounts.py`), moved by the merge | 10 |
| Website account, Connect Twitch on Profile, never joined in the panel | 5 | none | 5 |

`twitch_oauth.connect_account` only stores the Twitch id, or sets up a pending merge when a soft account holds it. It never grants anything, so the second path is 5 tokens short.

This plan gives every Twitch account its starter tokens exactly once, whichever path it takes. A website account that connects Twitch without a panel collection to merge gets a one-time **Twitch starter bonus** equal to the soft-account starter. The grant is keyed by the Twitch user id, so disconnecting and connecting again, or connecting the same Twitch account to another website account, never grants it twice.

Assumption: the issue asks to raise the shorter path to match the longer one ("they currently do not receive the same 5 bonus tokens"), so both paths end at 10. `TWITCH_CONNECT_BONUS_TOKENS` (default `INITIAL_TOKENS`) sets the amount, and `0` turns the bonus off. To level down instead (5 for everyone, no starter on the Twitch side once a website account exists), the merge would have to drop the soft starter. That is a different, larger change, not planned here.

Resolves GitHub issue #187.

## User Stories

### Connecting Twitch Gives the Twitch Starter Once
**User story**
As a player who connects Twitch on my Profile without having joined in the panel, I want the same Twitch starter tokens a panel player gets so that the way I signed up doesn't cost me tokens.

**Acceptance criteria**
- When Connect Twitch stores a Twitch id and no soft account holds that id ("connected", not "merge_ready"), the website account is credited `TWITCH_CONNECT_BONUS_TOKENS` (default `INITIAL_TOKENS`, 5) with `credit_tokens` (#185)
- The grant is recorded per Twitch user id in a new `twitch_starter_grants` table (`twitch_account_id` unique, `user_id`, `source` = `join` or `connect`, `granted_at`). A Twitch id that already has a row gets no bonus
- Profile shows "Twitch connected. You received N Twitch starter tokens." when a bonus was granted, and the usual "Twitch connected." otherwise
- `TWITCH_CONNECT_BONUS_TOKENS=0` turns the bonus off; nothing is recorded
- An audit entry `twitch_starter_bonus` names the user and amount, never the Twitch id

### The Panel Path Isn't Doubled
**User story**
As the operator, I want a player who already got the Twitch starter in the panel not to get it again on connect, so that every path ends at the same total.

**Acceptance criteria**
- When a soft account with an identity share is created by Join, a `twitch_starter_grants` row with `source = join` is recorded for its Twitch id. A soft account without an identity share gets one when its Twitch id becomes known
- Connecting a Twitch id that a soft account holds ("merge_ready") grants no bonus; the soft account's tokens, including its starter, arrive with the merge as today
- If that merge never happens (declined, or the account's one merge already used), still no bonus: the starter stays with the panel collection
- Totals after each path:
  - website account plus Connect Twitch: `INITIAL_TOKENS` + bonus;
  - website account plus Join, then merge: `INITIAL_TOKENS` + soft starter.

  These are equal at the defaults.

### No Farming by Reconnecting
**User story**
As the operator, I want the bonus tied to the Twitch account, not the website account, so that disconnecting and reconnecting, or moving one Twitch account between website accounts, can't collect it repeatedly.

**Acceptance criteria**
- Disconnect, then Connect the same Twitch account to the same or another website account: no second bonus (the `twitch_starter_grants` row stays after disconnect)
- Two simultaneous connect callbacks for one Twitch id grant once. The `twitch_account_id` unique constraint decides; the loser credits nothing
- A merge reversal (`reverse_merge`) leaves the grant row, so the Twitch id can't earn the starter again

### Existing Players Are Treated the Same
**User story**
As a player who connected Twitch on the website before this change, I want the starter I missed so that early players aren't worse off.

**Acceptance criteria**
- A one-time data migration records `source = join` rows for existing soft accounts with a Twitch id, and for website accounts that merged a soft account (`merged_soft_account_at` set)
- It then credits the bonus once, with a `connect` row, to each website account that has a `twitch_account_id`, no grant row for that id, and no merge
- The migration logs the count and writes one `twitch_starter_bonus` audit entry per credited user (`detail` includes `migration=038`). A second run credits nothing

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/models.py` | New `TwitchStarterGrant` table (`twitch_starter_grants`), created by `create_all` |
| `backend/soft_accounts.py` | Record a `join` grant when a soft account gets its Twitch id |
| `backend/twitch_oauth.py` | `connect_account`: on "connected", record a `connect` grant (insert on conflict do nothing) and credit the bonus when the insert added the row; message key `connected_bonus` |
| `backend/migrate.py` | `038_twitch_starter_grants_backfill` (data only), guarded so it runs once |
| `frontend/app-profile.js` | `_TWITCH_RETURN_MESSAGES.connected_bonus` with the amount from `GET /twitch/connection` or the redirect key |
| `.env.example` | `TWITCH_CONNECT_BONUS_TOKENS` |
| `markdown/features/reference/twitch-account-connection.md`, `markdown/features/reference/twitch-extension-policy-compliance.md`, `markdown/ui_description/profile.md` | Docs |
| `backend/tests/test_issue_187_uniform_twitch_starter_tokens.py` | Tests |

A new table needs no migration (CLAUDE.md); the backfill is a numbered data migration.

### Step 1 — Grant table and helper
`TwitchStarterGrant(id, twitch_account_id unique not null, user_id, source, granted_at)`. A helper `record_starter_grant(db, twitch_id, user_id, source) -> bool` runs `INSERT … ON CONFLICT (twitch_account_id) DO NOTHING` and returns whether a row was added, as in #185's claim pattern.

### Step 2 — Join and connect
- **Join:** where `soft_accounts.py` creates a soft account with a Twitch id, or sets the id after the identity share, call `record_starter_grant(..., "join")`.
- **Connect:** in `connect_account`, after storing the id with no holder, call `record_starter_grant(..., "connect")` when the bonus is above 0. When it returns `True`, run `credit_tokens(db, user.id, bonus)`, write the audit entry, and return `connected_bonus`. Keep the single commit.

### Step 3 — Backfill migration 038
Order matters: record the `join` rows first (soft accounts, merged website accounts), then credit the `connect` bonus to connected, unmerged website accounts without a row. Guard on a marker, for example the table being non-empty or a `migrations` marker, so a second run credits nothing.

### Step 4 — Profile message and docs
- **Frontend:** `handleTwitchReturn` maps `connected_bonus` to "Twitch connected. You received N Twitch starter tokens.", with N from `/config` `twitch_connect_bonus_tokens`.
- **Docs:** describe the rule and the table of paths.

### Step 5 — Tests
- connect without a soft account → bonus once;
- connect with a soft account → no bonus, merge brings the starter;
- disconnect and reconnect → no second bonus;
- connect the same Twitch id to another website account → no bonus;
- simultaneous callbacks (file-based SQLite and `threading.Barrier`, as in #185) → one bonus;
- `TWITCH_CONNECT_BONUS_TOKENS=0` → nothing;
- Join records a `join` row;
- migration 038 backfills as described and is idempotent;
- the audit entry holds no Twitch id;
- the Profile message key.

Keep `test_issue_85`'s suite-size baseline in step, and `test_migrate.py` passing.

## Verification
- **Fresh website account, Connect Twitch on test:** the balance goes 5 → 10 and Profile names the bonus. Disconnect and connect again: still 10.
- **Panel first:** Join in the panel (5 in the panel), connect on the website and merge: the website account ends at 10, with no extra bonus.
- **Migration:** on a copy of production (`scripts/backup-db.sh` first), run it and check the credited count against the connected, unmerged accounts. Review the `twitch_starter_bonus` audit entries.
- **Tests:** `cd backend && python3 -m pytest tests/ -q`.
