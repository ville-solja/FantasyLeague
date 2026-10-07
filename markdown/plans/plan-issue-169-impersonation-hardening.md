# Plan: Impersonation Hardening

## Context
Issue #169 (items 16 and 17 of the hardening issue #163) makes it harder to pass yourself off as someone else on Kana Cards.
- **Usernames:** names are ASCII-only, but uniqueness is case-sensitive, so `Ville` and `ville` can both exist. Names like `admin`, `kanaliiga`, `support` or `moderator` are allowed, and renames need no re-auth and have no limit.
- **Player ids:** `GET /profile/{user_id}` shows the name and avatar of whatever `player_id` the user typed in, and returns the numeric id. Anyone can claim a well-known league player's id and get a profile with that player's name and picture. The numeric id is also the Steam32 id, so every profile leads straight to a Steam profile and its public inventory: a ready target list for Steam phishing.

**The outcome:**
- **Unique, protected names:** usernames are unique regardless of case, and new names can't contain reserved words, including disguised forms such as `4dmin`.
- **Admin badge:** real admins carry a badge wherever usernames appear.
- **Profiles:** the claimed player's avatar shows only when the player id is verified through Steam. The numeric id is visible only to the player and to admins.
- **Renames:** once per 7 days by default.

**What exists today:**
- **Name format:** `backend/auth.py::check_username` applies `_USERNAME_RE = [A-Za-z0-9_-]+`. It is used by `POST /register` (`routers/auth.py`), `PUT /profile/username` (`routers/profile.py`) and the Steam sign-up `POST /auth/steam/signup` (`steam_openid.py`, #150).
- **Uniqueness:** each of these checks with an exact `User.username == name` query. So do the env admin seeding (`seed.py`) and demo seeding (`admin_demo.py`).
- **Profile response:** returns `player_id`, `player_name`, `player_avatar_url`, `twitch_linked`, `tags` and `past_seasons`.
- **Verified player ids (#150):** an account with `users.steam_id` has `player_id` set from the verified Steam id. Without `steam_id`, the id is self-reported.
- **Leaderboards:** rows (`routers/leaderboard.py`: roster, season, weekly) carry `id`, `username` and `tags`, and never `player_id`.
- **Tags:** user tags (`markdown/stories/user-tags.md`) already show as badges, but admins grant tags, so a tag can't prove admin status.
- **Data check:** the local copy of the database has 25 users, no case-insensitive collisions, and no names containing the default reserved words. Production must be checked the same way before the index is added (Step 1).

**Assumptions** (flagged for review):
- **Reserved words are matched as substrings of a normalised name.** The name is lower-cased, look-alikes are mapped (`0→o`, `1→i`, `3→e`, `4→a`, `5→s`, `7→t`, `rn→m`, `vv→w`), and `_` and `-` are removed. So `SuperAdmin1`, `4dmin`, `Kana_Liiga` and `rn0d` are refused.
- **The defaults come from the issue:** `admin`, `kana`, `liiga`, `support`, `official`, `staff`, `mod`. Short words also catch ordinary names: `mod` blocks `Modric`, and `kana` blocks `Kanata`. The list is configurable through `RESERVED_USERNAME_WORDS`, and only new names and renames are checked. Existing names, and a user saving their own unchanged name, are never refused.
- **Uniqueness ignores case only,** not the look-alike mapping, so `Ville` and `VilIe` can both exist. The admin badge and verified player ids cover that case. Normalised uniqueness would refuse too many ordinary names.
- **The admin badge** is a boolean `is_admin` on every row that shows a username to other users: leaderboards and profiles. Admin status is meant to be visible, so exposing it is intended. Demo accounts can't be admins (#150).
- **Self-reported player ids:** for other viewers, the profile keeps the player's in-game name (labelled "self-reported"), but drops the numeric id and the avatar. A verified id (the account has `steam_id`) shows the name, the avatar and "Verified with Steam", still without the number. The player and admins always see the id.
- **The rename cooldown is 7 days by default.** Set by `USERNAME_CHANGE_COOLDOWN_DAYS`, where `0` turns it off. A new `users.username_changed_at` column records the last rename, and the first change after this ships is never blocked. Admins aren't exempt, because no admin rename tool exists.
- **No re-auth for renames.** The issue only notes its absence, and the cooldown limits the abuse. This could be added later.
- **The case-insensitive index is skipped if collisions exist.** If production already has case-insensitive duplicates, migration `034` skips the unique index with a warning naming the user ids. The app-level check still blocks new duplicates, and the index can be added once an admin has resolved the pair.

Resolves GitHub issue #169.

## User Stories

### Usernames Are Unique Regardless of Case
**User story**
As a player, I want nobody else to register a name that differs from mine only in letter case, so that people can't pose as me with `ville` when I'm `Ville`.

**Acceptance criteria**
- `POST /register`, `PUT /profile/username`, `POST /auth/steam/signup`, env admin seeding and demo seeding treat names that differ only in case as the same name. A taken name is refused with 409 "Username already taken".
- A shared helper, `auth.username_taken(db, name, exclude_user_id=None)`, compares `lower(username)`, and every one of these places uses it.
- Migration `034` adds a unique index on `lower(username)`. It first checks for case-insensitive duplicates; if any exist, it skips the index and logs a warning naming the user ids.
- Twitch viewer soft accounts, which have no username, are unaffected.
- **Failure path:** registering `ville` while `Ville` exists answers 409 and creates nothing. Renaming yourself from `Ville` to `VILLE` is allowed, because the account excluded from the check is your own.

### Reserved Words Can't Be Used in New Names
**User story**
As an admin, I want names like `admin`, `kanaliiga` or `support` to be unavailable, so that players can't pose as staff or the league.

**Acceptance criteria**
- `auth.check_reserved`, called by the handlers, refuses a new name whose normalised form contains a reserved word, with 422 "This name is reserved". `check_username` (the Pydantic field validator) keeps only the ASCII format check. The normalised form is lower-case, with `0→o`, `1→i`, `3→e`, `4→a`, `5→s`, `7→t`, `rn→m`, `vv→w`, and `_` and `-` removed.
- The list comes from `RESERVED_USERNAME_WORDS` (comma-separated). Default: `admin,kana,liiga,support,official,staff,mod`. Entries are trimmed and lower-cased; empty entries are ignored. An unset or blank variable uses the default, so an empty value never turns the check off.
- The check applies to registration, renames, the Steam sign-up and demo seeding. It doesn't apply to env admin seeding, so an operator can still name a seeded admin `admin`.
- Existing accounts keep their names. They still log in, and saving the unchanged name on Profile succeeds: a rename skips the reserved check when the new name equals the current one ignoring case.
- **Failure path:** `SuperAdmin1`, `4dmin`, `Kana_Liiga` and `rn0d` are refused. An existing account named `admin_old` still logs in.

### Real Admins Carry a Badge
**User story**
As a player, I want to see at a glance who is really an admin, so that a look-alike name can't fool me.

**Acceptance criteria**
- Every response row that shows another user's name carries `is_admin` (boolean): the roster, season and weekly leaderboards, the season archive standings, and `GET /profile/{user_id}`. Roster leaderboard rows also gain the user `id`.
- The website shows an **ADMIN** badge next to those usernames: the season and weekly leaderboards, past season standings, and the player's own Profile (the website has no view of another user's profile). It uses the design system (display type, uppercase, the accent colour, a 2 px radius, no pill), and is visually distinct from user tags.
- No user or tag can produce the same badge: tags with the key or label `admin` are refused at tag creation.
- **Failure path:** a non-admin named `Admin_Helper` (an existing name) shows no badge.

### Profiles Don't Lend Out Other Players' Identities
**User story**
As a league player, I want my picture and Steam-linked id not to appear on someone else's profile just because they typed in my player id, so that nobody can pose as me or pull my Steam profile from Kana Cards.

**Acceptance criteria**
- `GET /profile/{user_id}` for another user:
  - never returns the numeric `player_id`;
  - returns `player_name` and `player_verified`, true when the account has a `steam_id`;
  - returns `player_avatar_url` only when `player_verified` is true.
- The profile shows the in-game name with "Verified with Steam" or "Self-reported", and the avatar only when verified.
- The player themselves (`GET /profile/{own id}`) and admins (checked against the database, not the session) still see the numeric id and the avatar. `GET /me` is unchanged regarding `player_id`.
- No other endpoint returns another user's `player_id`. A test checks every response that carries other users' data (leaderboards, weekly report, season archive, profile with its tags) and asserts that no row carrying a user identity (`id`/`user_id` with `username`) has a `player_id` key; card rows carrying a league player's id are fine. Another user's roster view stays admin-only.
- The privacy page says that a linked player id identifies a Steam account, and that Kana Cards shows it only to the player and to admins.
- **Failure path:** a profile with a self-reported id of a well-known player shows "Self-reported" and that player's name, with no avatar and no number.

### Renames Are Limited
**User story**
As an admin, I want players to be able to rename at most once a week, so that a name can't keep changing to imitate whoever is active.

**Acceptance criteria**
- `PUT /profile/username` refuses a change within `USERNAME_CHANGE_COOLDOWN_DAYS` (default 7) of the last one, with 429 and the date it becomes possible again.
- A successful change sets `users.username_changed_at`, a new column added in migration `034`.
- Saving the unchanged name, or changing only its letter case, doesn't count as a change.
- `USERNAME_CHANGE_COOLDOWN_DAYS=0` turns the limit off.
- `GET /me` and `PUT /profile/username` return `username_change_available_at` (Unix time, or null when a rename is allowed now or the cooldown is off). Profile shows "You can rename again on <date>" when it is set.
- **Failure path:** a second rename two days after the first answers 429 and keeps the current name.

## Implementation

### Critical Files
| File | Change |
|---|---|
| `backend/auth.py` | `normalise_username`, `reserved_words()` (reads `RESERVED_USERNAME_WORDS` at call time), `is_reserved`, `check_reserved(name)` (HTTPException 422), `username_taken(db, name, exclude_user_id=None)`; `check_username` unchanged |
| `backend/models.py` | `User.username_changed_at` (Integer, nullable) |
| `backend/migrate.py` | Migration `034_username_case_and_rename_time`: the column, PRAGMA-guarded, then the unique index on `lower(username)` after a collision check (skipped with a warning if needed) |
| `backend/routers/auth.py` | Register uses `username_taken` and the reserved check |
| `backend/routers/profile.py` | Rename: `username_taken`, reserved check, cooldown. Profile response: `player_verified`, no `player_id` for others, avatar only when verified, `is_admin` (self/admin decided with `deps.is_admin_fresh`). `GET /me`: `username_change_available_at` |
| `backend/steam_openid.py` | Sign-up uses `username_taken` and the reserved check |
| `backend/seed.py`, `backend/routers/admin_demo.py` | `username_taken` (seeding skips the reserved check; demo names pass it) |
| `backend/routers/leaderboard.py` | `is_admin` on rows that show a username (roster, season, weekly, and the archived standings in `GET /leaderboard/seasons/{season_id}`); roster rows also gain `id` |
| `backend/routers/admin_tags.py` | Refuse a tag whose key or label is `admin` (any case) |
| `frontend/app-globals.js`, `frontend/app-auth.js`, `frontend/app-leaderboard.js`, `frontend/app-profile.js` (own Profile; the website has no view of another user's profile), `frontend/index.html`, `frontend/style.css` | Admin badge (`adminBadgeHtml`); Verified/Self-reported label; avatar only when verified; next-rename date |
| `frontend/privacy.html` | Player id identifies a Steam account; shown only to the player and admins |
| `.env.example` | `RESERVED_USERNAME_WORDS`, `USERNAME_CHANGE_COOLDOWN_DAYS` |
| `backend/tests/test_issue_169_impersonation_hardening.py` | New tests |

### Step 1 — Check production data
Before deploying, run this on a copy of production. It lists case-insensitive duplicates and existing names that contain reserved words:

```bash
sqlite3 <db> "select lower(username), group_concat(id) from users where username is not null group by lower(username) having count(*) > 1;"
```

Existing reserved-word names are fine, because they keep working. Duplicates are resolved by renaming one account before the deploy, or the index is added in a later deploy.

### Step 2 — Name rules
```python
_LOOKALIKE = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})

def normalise_username(name: str) -> str:
    s = name.lower().replace("_", "").replace("-", "").translate(_LOOKALIKE)
    return s.replace("rn", "m").replace("vv", "w")

def username_taken(db, name: str, exclude_user_id: int | None = None) -> bool:
    q = db.query(User.id).filter(func.lower(User.username) == name.lower())
    if exclude_user_id is not None:
        q = q.filter(User.id != exclude_user_id)
    return q.first() is not None
```

`check_username` keeps only the ASCII pattern: it is a Pydantic field validator, so it can't return the plain 422 detail or see the current user. The handlers (register, rename, Steam sign-up, demo seeding) call `auth.check_reserved(name)`, which raises `HTTPException(422, "This name is reserved")`. Rename skips it when the new name equals the current one, ignoring case. Env admin seeding skips it.

### Step 3 — Migration and cooldown
- Migration `034`: add `username_changed_at`. Then run the duplicate query; if it returns nothing, run `CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username_lower ON users (lower(username))`, otherwise log a warning with the ids.
- **Rename:** compare against `username_changed_at`, and set it on a real change.

### Step 4 — Profile and badge
- **Profile response:** viewer is self or admin → as today, plus `player_verified` and `is_admin`. Anyone else → drop `player_id`, and keep `player_avatar_url` only when verified.
- **Leaderboards and archive:** add `u.is_admin` to the rows.
- **Frontend:** render the badge and the label.

### Step 5 — Docs
- Update `core/auth.md` (name rules, cooldown), `reference/player-linking-and-tag-visibility.md` (verified vs self-reported), `ui_description/profile.md` and `leaderboards.md`, and the privacy page.
- Fill in the feature doc.

## Decisions
Applied during implementation (2026-10-07):
1. The reserved-word check runs in the handlers through `auth.check_reserved`, not in the `check_username` field validator. Rename skips it for the current name ignoring case; env admin seeding skips it.
2. `/leaderboard/roster` rows gain `id` as well as `is_admin`.
3. `GET /me` is unchanged regarding `player_id`; the own profile (`GET /profile/{own id}`) already returns it.
4. The no-leak test checks that no row carrying a user identity (`id`/`user_id` with `username`) has a `player_id` key; card rows with league-player ids are fine.
5. `GET /me` returns `username_change_available_at` (Unix time, or null when a rename is allowed now or the cooldown is off); Profile shows "You can rename again on <date>".
6. `get_profile` uses `deps.is_admin_fresh` to decide whether an admin viewer gets `player_id`.
7. An unset or blank `RESERVED_USERNAME_WORDS` uses the default list, so an empty variable never turns the check off.
8. If migration `034` skips the index because of duplicates, it is recorded as applied; after resolving the pair, the operator runs `CREATE UNIQUE INDEX ix_users_username_lower ON users (lower(username))` (the warning prints it).

## Verification
- **Names:**
  - `ville` refused when `Ville` exists, on register, rename and Steam sign-up;
  - `Ville` → `VILLE` allowed for the same account;
  - `SuperAdmin1`, `4dmin`, `Kana_Liiga` and `rn0d` refused;
  - an existing `admin_old` still logs in and can save its unchanged name;
  - the env admin seed can still be called `admin`;
  - a custom `RESERVED_USERNAME_WORDS` replaces the defaults.
- **Profile, viewed by another user:**
  - self-reported id: no `player_id` and no `player_avatar_url`, `player_verified` false;
  - verified id: avatar, still no `player_id`.
  - Self and admin views still include the id.
- **No leak elsewhere:** no endpoint returning other users' rows contains another user's `player_id`.
- **Badge:** leaderboard and profile rows carry `is_admin`; a tag keyed `admin` is refused.
- **Cooldown:** a second rename within 7 days answers 429; a case-only change and an unchanged name don't count; `USERNAME_CHANGE_COOLDOWN_DAYS=0` disables the limit.
- **Migration:** `034` on a database with a case-insensitive duplicate skips the index with a warning; on a clean database the index exists. `tests/test_migrate.py` passes.
- **Manual:** run Step 1 on a production copy; check the badge and the profile labels in a browser.
- Run the full suite and update the suite-size check in `tests/test_issue_85_split_admin_router.py`.
