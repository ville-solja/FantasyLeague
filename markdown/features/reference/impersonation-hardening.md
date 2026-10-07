# Impersonation Hardening

Makes it harder to pass yourself off as another player, an admin or the league: usernames are unique regardless of case, reserved words are blocked, real admins carry a badge, and profiles no longer lend out another player's picture or Steam-linked id. Resolves issue #169 (part of #163).

---

## Usernames

- **Uniqueness ignores case.** `auth.username_taken(db, name, exclude_user_id=None)` compares `lower(username)`. Every place that creates or changes a name uses it: `POST /register`, `PUT /profile/username`, `POST /auth/steam/signup`, env admin seeding (`seed.seed_admin_from_env`) and demo seeding (`POST /admin/demo/seed-accounts`). A taken name answers 409 "Username already taken". Renaming yourself to a case variant of your own name is allowed. `POST /login` still looks names up exactly.
- **Database index.** Migration `034_username_case_and_rename_time` adds the unique index `ix_users_username_lower` on `lower(username)`. If case-insensitive duplicates already exist, it skips the index and logs a warning naming the user ids; the migration still counts as applied. After renaming one account of each pair, run the statement the warning prints: `CREATE UNIQUE INDEX ix_users_username_lower ON users (lower(username))`. Twitch soft accounts (username `NULL`) are unaffected.
- **Reserved words.** `auth.check_reserved(name)` refuses a name whose normalised form contains a reserved word, with 422 "This name is reserved". `auth.normalise_username` lower-cases, removes `_` and `-`, maps `0→o`, `1→i`, `3→e`, `4→a`, `5→s`, `7→t`, then `rn→m` and `vv→w`. So `SuperAdmin1`, `4dmin`, `Kana_Liiga` and `rn0d` are refused.
  - The handlers call it: register, rename, Steam sign-up and demo seeding. `auth.check_username`, the Pydantic field validator, still checks only the ASCII format.
  - Env admin seeding skips it, so an operator can still name a seeded admin `admin`.
  - Existing names keep working: they log in, and a rename to the current name (ignoring case) skips the check.
  - Short words also catch ordinary names: `mod` blocks `Modric`, `kana` blocks `Kanata`.
- **Rename cooldown.** `PUT /profile/username` allows one rename per `USERNAME_CHANGE_COOLDOWN_DAYS`, tracked in `users.username_changed_at` (Unix time, set on each real rename). A rename within the cooldown answers 429 "You can change your username again on YYYY-MM-DD HH:MM UTC" with a `Retry-After` header, and keeps the name. Saving the unchanged name or changing only the letter case doesn't count. The first rename after this shipped is never blocked (the column starts `NULL`). Admins aren't exempt. There is no re-authentication for renames.
- **Next rename time.** `GET /me` and `PUT /profile/username` return `username_change_available_at`: the Unix time the next rename is possible, or `null` when a rename is allowed now or the cooldown is off. Profile shows "You can rename again on <date>" under the username field.

## Admin badge

Rows that show another user's name carry `is_admin` (boolean), read from `users.is_admin`:

| Endpoint | Rows |
|---|---|
| `GET /leaderboard/roster` | each row (which also gains the user `id`) |
| `GET /leaderboard/season` | each row (also `compute_season_standings`, used by End Season) |
| `GET /leaderboard/weekly?week_id=` | each row |
| `GET /leaderboard/seasons/{season_id}` | each `standings[]` entry (current admin status of `user_id`) |
| `GET /profile/{user_id}` | the profile |

The website shows an outlined **ADMIN** badge (`adminBadgeHtml` in `frontend/app-globals.js`, class `.admin-badge`) next to the name on the season and weekly leaderboards, past season standings, and the player's own Profile. It is built only from `is_admin`, never from tags. `POST /admin/tags` refuses a tag whose key or label is `admin` (any case) with 422 "This tag name is reserved".

## Player ids on profiles

A player id is a Steam32 id, so it leads to a Steam profile. `GET /profile/{user_id}` returns:

| Field | Self or admin viewer | Anyone else |
|---|---|---|
| `player_id` | yes | never (key absent) |
| `player_name` | yes | yes |
| `player_verified` | yes | yes: true when the account has a `steam_id` (#150) and a player id |
| `player_avatar_url` | yes | only when `player_verified` is true; otherwise `null` |
| `is_admin` | yes | yes |

Whether the viewer is an admin is checked with `deps.is_admin_fresh`, so a demoted admin loses the id on the next request. `GET /me` is unchanged regarding `player_id`. No leaderboard, weekly report, season archive or tag response carries a user's `player_id`; card rows carry league player ids, which are public. Another user's roster (`GET /roster/{user_id}`) stays admin-only.

On Profile, the linked player's name carries "Verified with Steam" or "Self-reported", and the avatar shows only for a verified id. The privacy page states that a linked player id identifies a Steam account and is shown only to the player and admins.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `RESERVED_USERNAME_WORDS` | `admin,kana,liiga,support,official,staff,mod` | Comma-separated words new usernames can't contain (after look-alike normalisation). Entries are normalised like names (so `m0d` or `kana_liiga` still match); empty entries are ignored. A value with no usable entry (unset, blank or only commas) uses the default. Read at call time. Adding a word that matches the demo names (`demo`) makes demo seeding fail with 422. |
| `USERNAME_CHANGE_COOLDOWN_DAYS` | `7` | Days between renames; `0` turns the limit off. Read at call time. |

## Before deploying

Check a copy of production for case-insensitive duplicates; migration `034` skips the index while any exist:

```bash
sqlite3 <db> "select lower(username), group_concat(id) from users where username is not null group by lower(username) having count(*) > 1;"
```

## Tests

`backend/tests/test_issue_169_impersonation_hardening.py`.
