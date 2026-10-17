# Plan: Steam-Verified Player Links Only

## Context
An account is linked to a league player through `users.player_id`. Today that link can come from two places:
- **Steam:** Steam sign-in or Link Steam (`steam_openid.py`) sets it from the Steam id. This is verified.
- **Typed in:** in `LOGIN_METHOD=password` mode, `PUT /profile/player-id` lets a user type any OpenDota id. This is self-reported and unchecked.

Some features already trust only verified links:
- the own player card (`own_card.is_candidate`, #188);
- the Fantasy Winner pip (`accolades._linked_users`, #50).

Others still trust any link, so a user can claim someone else's player:
- **Tag stickers on card images:** the card image route (`backend/routers/cards.py`) composites the stickers of the first user whose `player_id` matches the card's player. It doesn't check that link, so a claimant's tags appear on a stranger's cards.
- **Profile panel:** it shows a typed-in player (read-only "Self-reported" in Steam modes, an editable field in password mode).
- **Unlinking Steam:** `steam_openid.unlink` clears `steam_id` but **keeps** `player_id`, which silently turns a verified link into a self-reported one.

**Decisions** (change them in review if needed):
- **One rule:** a player link exists only when `steam_id` and `player_id` are both set. One shared helper answers "which player is this user verifiably?" and every reader uses it.
- **Remove manual entry:** `PUT /profile/player-id`, its Profile field and the "self_reported" panel state go.
- **Password mode has no player linking:** with `LOGIN_METHOD=password` Steam is off, so the Player identity panel shows "Player linking needs Steam sign-in" and nothing else. Operators who want linking run `both` or `steam_signup`. Production is expected to run a Steam mode; the README's `LOGIN_METHOD` note says so.
- **Existing typed-in links are cleared,** not kept and ignored. That leaves one rule and no dead state. Migration 041 sets `player_id = NULL` where `steam_id IS NULL`, writes one audit entry with the count, and is idempotent. It is irreversible, so `scripts/backup-db.sh` runs before the deploy.
- **Unlinking Steam clears `player_id` too,** in the same transaction, audited.
- **Kept:** the admin "Superseded player id claims" table (`GET /admin/player-id-claims`) is history and stays as it is. Leaderboard tag chips belong to the user, not the player, so they're unchanged.

Resolves GitHub issue #209.

## User Stories

### Only Steam Links an Account to a Player
**User story**
As a league player, I want my player identity to come only from Steam, so that nobody can claim my player and show their tags or titles on my cards.

**Acceptance criteria**
- **Route removed:** `PUT /profile/player-id` no longer exists; a request gets 404 in every login mode. Its Profile field and save button are gone.
- **Steam sets the link:** Steam sign-in and Link Steam still set `player_id` from the Steam id, unchanged.
- **Unlinking Steam:** clears `player_id` in the same transaction. The `steam_unlinked` audit detail adds `player_id_cleared=1` when one was set.
- **Panel without a verified link:** in a Steam mode, an account without a verified link sees the existing "not linked" state with **Link Steam**. There is no "Self-reported" state any more.
- **Password mode:** the panel shows "Player linking needs Steam sign-in", and no field or button.

### Every Feature Trusts Only Verified Links
**User story**
As the operator, I want one rule for "this account is this player", used everywhere, so that no feature quietly trusts an unverified claim.

**Acceptance criteria**
- **One helper:** a shared helper (`player_links.py`) gives the verified player of a user, and the users verified for a player: `steam_id` and `player_id` set, on a full, non-demo account (the existing `own_card.is_candidate` rule).
- **Every reader uses it:**
  - the card image tag stickers (`routers/cards.py`);
  - `GET /profile/{user_id}` (`player_name`, `player_avatar_url`, `player_team_name`, and `player_id` for the owner and admins);
  - `own_card.is_candidate`;
  - `accolades._linked_users`.
- **Tag stickers:** a card's tag stickers come only from a user with a verified link to that player. An account holding a stale `player_id` without Steam adds none.
- **Guard test:** a test fails when backend code outside the helper reads `users.player_id` or `User.player_id` without `steam_id`. The allow-list is the helper, Steam linking (`steam_openid.py`), the migration and `admin_users.py`'s claims history.

### Typed-in Links Are Cleared Once
**User story**
As the operator, I want the old typed-in links removed on upgrade, so that the database holds only verified links and nothing depends on legacy claims.

**Acceptance criteria**
- **Migration `041_clear_unverified_player_links`:** sets `player_id = NULL` for every user with `player_id` set and `steam_id` NULL.
- **Audit:** it writes one `player_links_cleared` entry with `count=N`, and none when N is 0.
- **Idempotent:** a second run changes nothing and writes no entry.
- **Verified links stay:** accounts with Steam keep their `player_id`.
- **Deploy note:** the PR and the migration doc say to run `scripts/backup-db.sh` first, because the cleared values can't be restored otherwise.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/player_links.py` (new) | `verified_player_id(user)`, `verified_users_for_player(db, player_id)`, `verified_links(db)` (user id → player id), and the shared SQL condition |
| `backend/routers/profile.py` | Remove `update_player_id` and `PUT /profile/player-id`; `get_profile` uses the helper; `UpdatePlayerIdBody` removed if unused |
| `backend/steam_openid.py` | `unlink` clears `player_id` and records it in the audit detail. `_supersede_player_id_claims` stays (it already clears others' claims when Steam verifies a player) |
| `backend/routers/cards.py` | Tag-sticker lookup through `verified_users_for_player` |
| `backend/own_card.py` | `is_candidate` delegates to the helper |
| `backend/accolades.py` | `_linked_users` delegates to the helper |
| `backend/migrate.py` | Migration `041_clear_unverified_player_links` (data only, idempotent, audited) |
| `frontend/app-profile.js` | Remove the id form handler and the `"password"` and `"self_reported"` states; add the password-mode note |
| `frontend/index.html` | Remove `#playerIdForm` and `#identityLegacyHint`; add the password-mode note |
| `markdown/features/reference/player-linking-and-tag-visibility.md`, `markdown/ui_description/profile.md`, `markdown/features/reference/steam-login.md`, `README.md` (`LOGIN_METHOD` note) | Docs |
| `backend/tests/test_issue_209_steam_verified_player_links.py` | Tests, including the guard test |

No new env var. Existing tests that call `PUT /profile/player-id`, pin the "self_reported" state or rely on typed-in links (#150, #169, #188 and the tag sticker tests) get updated to a Steam-verified setup. Each such change is listed in the developer report.

### Step 1 — Helper
Add `player_links.py` with the rule, and move `own_card.is_candidate` and `accolades._linked_users` onto it.

### Step 2 — Readers
Card image tag stickers and `GET /profile/{user_id}` use the helper.

### Step 3 — Remove manual entry and fix unlink
Delete the route, its body model and its frontend. `unlink` clears `player_id`.

### Step 4 — Migration 041
Clear the unverified links, write the audit entry, and test it on a legacy-schema engine (the `_legacy_engine` pattern in `test_migrate.py`).

### Step 5 — Profile UI
Remove the states; the Steam modes keep "linked", "linked_no_match" and "not_linked". Password mode shows the note.

### Step 6 — Docs and tests
**Docs:** rewrite the linking doc's "verified vs self-reported" sections as history ("before #209"), and update the UI spec and the README note.

**Tests:**
- the route is gone (404 in all three modes);
- unlink clears the link and audits it;
- the profile response hides a stale unverified `player_id`;
- tag stickers only through a verified link;
- the migration: counts, idempotent, keeps Steam links, audit entry;
- the guard test;
- the panel states (Node harness).

## Verification
- **On a test copy with typed-in links:** after deploy the migration log shows `041_clear_unverified_player_links` and an audit entry with the count. Those accounts' panels show "not linked" with Link Steam.
- **A Steam-linked account:** keeps its player and own card, and its tags still show on its player's cards.
- **Unlink Steam:** the panel shows "not linked", and that player's cards lose the user's tag stickers.
- **`LOGIN_METHOD=password` (local):** the panel shows the Steam note, and `PUT /profile/player-id` gets 404.
- **Deploy:** includes migration 041, so run `bash scripts/backup-db.sh` first.
