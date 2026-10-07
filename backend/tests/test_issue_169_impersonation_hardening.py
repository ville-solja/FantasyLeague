"""
Tests for plan-issue-169-impersonation-hardening.md (resolves GitHub issue #169).

Makes it harder to pose as someone else: usernames unique regardless of case
(`auth.username_taken`, a unique index on `lower(username)`), reserved words refused
in new names after look-alike normalisation (`auth.normalise_username`,
`RESERVED_USERNAME_WORDS`), an `is_admin` badge on every row that shows another user's
name, profiles that drop another user's numeric `player_id` and show the avatar only
for a Steam-verified id (`player_verified`), and a rename cooldown
(`USERNAME_CHANGE_COOLDOWN_DAYS`, `users.username_changed_at`). One class per user
story; one test per acceptance criterion plus the primary failure path.

Decisions applied by the developer (see the plan's "Decisions" section): the
reserved-word check runs in the handlers through `auth.check_reserved` (422 "This name is
reserved"); `check_username` keeps only the ASCII format check. `/leaderboard/roster`
rows gain `id` and `is_admin`. `GET /me` returns `username_change_available_at`.

Developer notes
---------------

  State of the code this builds on
    - #150 is implemented: `users.steam_id` holds the verified Steam64 id (an account
      with it has a verified `player_id`); `users.is_demo` marks demo accounts.
      `POST /auth/steam/signup` (`steam_openid.signup`, body `SteamSignupBody`) applies
      `auth.check_username` and an exact `User.username == name` check.
    - The latest migration is `033_users_steam_id`; this plan's is
      `034_username_case_and_rename_time` (column + collision-checked index).
    - `auth.check_username` / `_USERNAME_RE` is a Pydantic field-validator body: a
      ValueError there becomes FastAPI's 422 with a list-shaped `detail`, not the plain
      string "This name is reserved". It also cannot see the current user, so "rename
      skips the reserved check when the new name equals the current one, ignoring case"
      must happen in the handler (e.g. validate the charset in the model, and run the
      reserved check in `update_username` / `register` / `signup` with
      `HTTPException(422, "This name is reserved")`). Tests below assert the string
      detail, so pick one shape and keep it consistent.
    - Register: `routers/auth.py` (`RegisterBody`, `POST /register`).
      Rename: `routers/profile.py` `PUT /profile/username` (writes a `username_changed`
      audit row only when the name changes). Profile: `GET /profile/{user_id}`.
      Leaderboards: `routers/leaderboard.py` — `/leaderboard/roster` (no `id` today,
      only `username`), `/leaderboard/season` (via `compute_season_standings`),
      `/leaderboard/weekly?week_id=`, archived `GET /leaderboard/seasons/{season_id}`
      (`standings[].user_id/username`). Tags: `routers/admin_tags.py` `POST /admin/tags`.
      Env admin seeding: `seed.seed_admin_from_env` (exact `filter_by(username=)`).
      Demo seeding: `routers/admin_demo.seed_demo_accounts` (a `demo%` LIKE set, exact
      membership test).
    - Login (`POST /login`) still looks names up exactly; the plan does not change it.

  Reuse
    - `_Web` / `_acting` from tests/test_issue_160 and the `web` fixture / `_add` /
      `_signup` helpers from tests/test_issue_150 (import underscore names only).
      Add the leaderboard, admin_tags and weekly_summary routers to a local copy of the
      `web` fixture as needed.
    - Pin env-driven values with `monkeypatch.setenv` and read them at call time
      (`reserved_words()`, the cooldown), so no module reload is needed.

  "No leak" test (Story 4)
    - Card rows carry `player_id` of the league player on the card (weekly summary,
      top performances, rosters). Those ids are public and may equal some user's linked
      id, so the leak check must assert that no object carrying a user identity
      (`id`/`user_id` + `username`) has a `player_id` key, rather than searching the
      whole body for the number.

  Existing tests likely affected
    - tests/test_issue_120_profile_requires_login.py
      `test_authenticated_user_can_view_any_profile_unchanged_shape` asserts the exact
      profile body of another user (including `player_id`, without `player_verified`
      / `is_admin`): update it to the new shape.
    - tests/test_issue_141_stored_card_points.py:275 asserts
      `set(r) == {"id", "username", "points", "tags", "cards"}` for
      `compute_season_standings` rows: extend with `is_admin` if it is added there.
    - tests/test_issue_150_steam_login.py signs up `newadmin` (l.1465), `admin1`
      (l.1502) and `steamadmin` (l.1571): reserved under the default list; rename those
      fixtures (or set `RESERVED_USERNAME_WORDS` in those tests).
      `test_steam_signup_invalid_or_taken_username_rejected` (l.859) may gain a
      case-variant case.
    - tests/test_issue_135_security_review_fixes.py rename tests
      (`test_update_username_writes_username_changed_audit`,
      `test_update_username_taken_name_no_session_change_or_audit`) and tag-key tests
      (`test_create_tag_valid_key_accepted`, `test_create_tag_invalid_key_returns_422`):
      should still pass; check the audit test against the cooldown column.
    - tests/test_issue_115_username_xss_fix.py profile rename tests,
      tests/test_issue_83_demo_mode.py
      `test_seed_accounts_creates_named_accounts_skipping_taken_usernames`,
      tests/test_models.py `test_unique_username_enforced`,
      tests/test_user_tag_system.py (tag creation),
      tests/test_player_linking_and_tag_visibility.py (replicates the profile response
      locally; the own-profile gap hint still reads `player_id`, which self views keep).
    - tests/test_migrate.py schema coverage: needs migration 034 for
      `users.username_changed_at`.
    - tests/test_issue_85_split_admin_router.py
      `test_full_suite_pass_skip_counts_match_pre_split_baseline` pins "2117 passed":
      add this file's final count (plus any net change in edited tests) and extend the
      docstring history.
"""

import json
import logging
import pathlib
import re
import time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

# Registers every existing table on Base before the conftest db fixture runs
# create_all (see markdown/lessons-learned.md, 2026-10-01).
import models  # noqa: F401

# The `web` and `mode` fixtures (auth, Steam, profile routers on a thread-safe DB).
from tests.test_issue_150_steam_login import (  # noqa: F401
    _count, _key, _round_trip, _user_by_name, mode, web,
)
from tests.test_issue_160_twitch_account_connection_oidc import _PASSWORD, _acting

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"

# Names that the plan says must be refused under the default reserved list.
_REFUSED_NAMES = ["SuperAdmin1", "4dmin", "Kana_Liiga", "rn0d", "support", "Official",
                  "staff-1", "m0d", "l11ga", "ADMIN"]

# Endpoints whose rows show another user's name (Story 3 badge, Story 4 no-leak).
_USER_ROW_ENDPOINTS = ["leaderboard_roster", "leaderboard_season", "leaderboard_weekly",
                       "leaderboard_archived_season", "profile_other_user"]

_DAY = 86400


@pytest.fixture(autouse=True)
def _default_name_env(monkeypatch):
    """Every test starts from the defaults (the developer shell may export either)."""
    monkeypatch.delenv("RESERVED_USERNAME_WORDS", raising=False)
    monkeypatch.delenv("USERNAME_CHANGE_COOLDOWN_DAYS", raising=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mk(db, username, **fields):
    from models import User
    fields.setdefault("email", f"{(username or 'soft').lower()}-{time.time_ns()}@example.com")
    fields.setdefault("tokens", 5)
    fields.setdefault("created_at", int(time.time()))
    user = User(username=username, **fields)
    db.add(user)
    db.commit()
    return user


def _rename(db, user, new_name):
    from routers.profile import UpdateUsernameBody, update_username
    return update_username(UpdateUsernameBody(username=new_name), db=db, current_user=_acting(user))


def _raises(fn, *args, **kwargs) -> HTTPException:
    with pytest.raises(HTTPException) as exc:
        fn(*args, **kwargs)
    return exc.value


def _profile(db, user, viewer):
    from routers.profile import get_profile
    return get_profile(user.id, db=db, current_user=_acting(viewer))


def _seed_env_admin(db, monkeypatch, username):
    import seed as seed_module
    monkeypatch.delenv("LOGIN_METHOD", raising=False)
    monkeypatch.setenv("SEED_ADMIN_USERNAME", username)
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "seeded-admin@example.com")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "secret123")
    monkeypatch.setattr(seed_module, "SessionLocal", lambda: db)
    seed_module.seed_admin_from_env()


def _seed_demo(db, monkeypatch, count=2):
    from routers.admin_demo import SeedDemoAccountsBody, seed_demo_accounts
    monkeypatch.setenv("DEMO_MODE", "true")
    boss = _mk(db, "boss", is_admin=True)
    return seed_demo_accounts(SeedDemoAccountsBody(count=count, cards_per_account=0), db=db,
                              admin=_acting(boss))


def _scene(db):
    """A real admin and the look-alike non-admin 'Admin_Helper' (an existing name), both with
    linked player ids, a viewer, a locked week with a weekly report, and an archived season."""
    from models import Player, SeasonArchive, Week, WeeklySummary
    now = int(time.time())
    admin = _mk(db, "Boss", is_admin=True, player_id=987650001)
    helper = _mk(db, "Admin_Helper", player_id=987650002)
    viewer = _mk(db, "viewer", player_id=987650003)
    db.add(Player(id=987650002, name="Famous Player", avatar_url="https://example.com/famous.png"))
    db.add(Week(id=1, label="Week 1", start_time=now - 7 * _DAY, end_time=now - _DAY, is_locked=True))
    db.add(WeeklySummary(week_id=1, generated_at=now))
    for rank, u in enumerate((admin, helper, viewer), start=1):
        db.add(SeasonArchive(season_label="S1", user_id=u.id, username=u.username,
                             points=10.0 * (4 - rank), rank=rank, archived_at=now))
    db.commit()
    season_id = db.query(SeasonArchive.id).order_by(SeasonArchive.id).first()[0]
    return {"admin": admin, "helper": helper, "viewer": viewer, "season_id": season_id}


def _endpoint_body(db, endpoint, scene, target):
    """The response of `endpoint`, as seen by scene['viewer']. `target` is the user whose
    profile is fetched for profile_other_user."""
    from routers import leaderboard as lb
    from routers import weekly_summary as ws
    viewer = _acting(scene["viewer"])
    if endpoint == "leaderboard_roster":
        return lb.roster_leaderboard(db=db)
    if endpoint == "leaderboard_season":
        return lb.season_leaderboard(db=db)
    if endpoint == "leaderboard_weekly":
        return lb.weekly_leaderboard(week_id=1, db=db)
    if endpoint == "leaderboard_archived_season":
        return lb.archived_season_detail(scene["season_id"], db=db)
    if endpoint == "weekly_summary_list":
        return ws.list_weekly_summaries(db=db, current_user=viewer)
    if endpoint == "weekly_summary_week":
        return ws.get_weekly_summary(1, db=db, current_user=viewer)
    if endpoint == "profile_other_user":
        return _profile(db, target, scene["viewer"])
    raise AssertionError(endpoint)


def _identity_rows(body):
    """Every object in a JSON-like body that carries a user identity (id/user_id + username)."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if "username" in node and ("id" in node or "user_id" in node):
                found.append(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                walk(v)
    walk(json.loads(json.dumps(body, default=str)))
    return found


def _row_for(body, user):
    rows = [r for r in _identity_rows(body) if r.get("id", r.get("user_id")) == user.id]
    assert len(rows) == 1, rows
    return rows[0]


def _read(name):
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


def _css_block(css, selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, f"{selector} not found"
    return m.group(1)


def _migrated_engine():
    from database import Base
    from migrate import run_migrations
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    run_migrations(engine)
    return engine


def _index_names(conn):
    return {r[0] for r in conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='users'")).fetchall()}


# ===========================================================================
# Story 1 — Usernames Are Unique Regardless of Case
# ===========================================================================

class TestUsernamesUniqueRegardlessOfCase:

    @pytest.mark.parametrize("candidate", ["ville", "VILLE", "vIlLe", "Ville"])
    def test_username_taken_matches_case_insensitively(self, db, candidate):
        """auth.username_taken(db, name) compares lower(username): any case variant of an existing 'Ville' is taken."""
        from auth import username_taken
        _mk(db, "Ville")
        assert username_taken(db, candidate) is True
        assert username_taken(db, "someone-else") is False

    def test_username_taken_excludes_own_account(self, db):
        """username_taken(db, 'VILLE', exclude_user_id=<Ville's id>) is False: the excluded account doesn't count."""
        from auth import username_taken
        ville = _mk(db, "Ville")
        assert username_taken(db, "VILLE", exclude_user_id=ville.id) is False
        other = _mk(db, "other")
        assert username_taken(db, "VILLE", exclude_user_id=other.id) is True

    def test_username_taken_ignores_lookalikes(self, db):
        """Uniqueness ignores case only: 'VilIe' is not taken when 'Ville' exists (no look-alike mapping)."""
        from auth import username_taken
        _mk(db, "Ville")
        assert username_taken(db, "VilIe") is False
        assert username_taken(db, "Vi11e") is False

    def test_register_case_variant_refused_409_creates_nothing(self, web, mode):
        """Failure path: POST /register 'ville' while 'Ville' exists answers 409 'Username already taken' and creates no user."""
        from models import User
        mode("password")
        web.add_user("Ville")
        resp = web.client().post("/register", json={"username": "ville", "email": "v2@example.com",
                                                     "password": "secret123"})
        assert resp.status_code == 409, resp.text
        assert resp.json()["detail"] == "Username already taken"
        assert _count(web, User) == 1

    def test_profile_rename_to_other_users_case_variant_refused_409(self, db):
        """PUT /profile/username to 'VILLE' while another account is 'Ville' answers 409 'Username already taken'."""
        from models import User
        _mk(db, "Ville")
        me = _mk(db, "someone")
        exc = _raises(_rename, db, me, "VILLE")
        assert (exc.status_code, exc.detail) == (409, "Username already taken")
        assert db.get(User, me.id).username == "someone"

    def test_profile_rename_own_case_change_allowed(self, db):
        """Failure path: renaming yourself from 'Ville' to 'VILLE' is allowed (your own account is excluded)."""
        from models import User
        me = _mk(db, "Ville")
        assert _rename(db, me, "VILLE")["username"] == "VILLE"
        assert db.get(User, me.id).username == "VILLE"

    def test_steam_signup_case_variant_refused_409(self, web, mode, monkeypatch):
        """POST /auth/steam/signup with 'ville' while 'Ville' exists answers 409 'Username already taken'."""
        from models import User
        mode("both")
        web.add_user("Ville")
        client = web.client()
        resp, _ = _round_trip(client, monkeypatch)
        assert _key(resp, "welcome") == "choose_name"
        bad = client.post("/auth/steam/signup", json={"username": "ville"})
        assert bad.status_code == 409, bad.text
        assert bad.json()["detail"] == "Username already taken"
        assert _count(web, User) == 1

    def test_seed_admin_from_env_treats_case_variant_as_existing(self, db, monkeypatch):
        """seed_admin_from_env with SEED_ADMIN_USERNAME='ADMIN' skips creation when 'admin' already exists."""
        from models import User
        _mk(db, "admin")
        _seed_env_admin(db, monkeypatch, "ADMIN")
        assert db.query(User).count() == 1
        assert db.query(User).filter_by(username="ADMIN").first() is None

    def test_seed_demo_accounts_skips_case_variant_of_existing_name(self, db, monkeypatch):
        """Demo seeding skips 'demo1' when 'DEMO1' exists and creates the next free name instead."""
        _mk(db, "DEMO1")
        result = _seed_demo(db, monkeypatch, count=2)
        assert [a["username"] for a in result["accounts"]] == ["demo2", "demo3"]

    @pytest.mark.parametrize("module, func", [
        ("routers.auth", "register"), ("routers.profile", "update_username"),
        ("steam_openid", "signup"), ("seed", "seed_admin_from_env"),
        ("routers.admin_demo", "seed_demo_accounts"),
    ])
    def test_every_name_check_uses_username_taken(self, module, func):
        """Register, rename, Steam sign-up, env admin seeding and demo seeding all call auth.username_taken (no exact User.username == name uniqueness query left). Login keeps its exact lookup."""
        import importlib
        import inspect
        src = inspect.getsource(getattr(importlib.import_module(module), func))
        assert "username_taken(db," in src
        assert "filter_by(username=" not in src
        assert "User.username ==" not in src
        assert "in existing" not in src

    def test_twitch_soft_accounts_without_username_unaffected(self, db):
        """Several Twitch viewer soft accounts with username NULL can coexist with the lower(username) unique index."""
        engine = _migrated_engine()
        with engine.connect() as conn:
            assert "ix_users_username_lower" in _index_names(conn)
            for i in range(3):
                conn.execute(text("INSERT INTO users (username, account_type, tokens, session_version, is_demo) "
                                  "VALUES (NULL, 'twitch', 0, 0, 0)"))
            conn.commit()
            assert conn.execute(text("SELECT COUNT(*) FROM users WHERE username IS NULL")).scalar() == 3

    def test_migration_034_creates_lower_username_unique_index(self):
        """Migration 034 on a clean legacy database creates the unique index ix_users_username_lower on lower(username)."""
        engine = _migrated_engine()
        with engine.connect() as conn:
            sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE name='ix_users_username_lower'")).scalar()
            applied = conn.execute(text(
                "SELECT 1 FROM schema_migrations WHERE id='034_username_case_and_rename_time'")).first()
        assert sql and "UNIQUE" in sql.upper() and "lower(username)" in sql
        assert applied is not None

    def test_lower_username_index_blocks_database_level_duplicate(self):
        """After migration 034, inserting 'ville' next to 'Ville' directly raises IntegrityError."""
        engine = _migrated_engine()
        insert = text("INSERT INTO users (username, account_type, tokens, session_version, is_demo) "
                      "VALUES (:u, 'full', 0, 0, 0)")
        with engine.connect() as conn:
            conn.execute(insert, {"u": "Ville"})
            conn.commit()
            with pytest.raises(IntegrityError):
                conn.execute(insert, {"u": "ville"})

    def test_migration_034_skips_index_and_warns_on_existing_collision(self, caplog):
        """Failure path: with 'Ville' and 'ville' already present, migration 034 skips the index and logs a warning naming both user ids; the migration still completes."""
        from database import Base
        from migrate import run_migrations
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with engine.connect() as conn:
            for uid, name in ((11, "Ville"), (12, "ville")):
                conn.execute(text("INSERT INTO users (id, username, account_type, tokens, session_version, is_demo) "
                                  "VALUES (:i, :u, 'full', 0, 0, 0)"), {"i": uid, "u": name})
            conn.commit()
        with caplog.at_level(logging.WARNING, logger="migrate"):
            run_migrations(engine)
        warnings = [r.getMessage() for r in caplog.records
                    if r.name == "migrate" and r.levelno == logging.WARNING and "034" in r.getMessage()]
        assert len(warnings) == 1
        assert re.search(r"\b11\b", warnings[0]) and re.search(r"\b12\b", warnings[0])
        with engine.connect() as conn:
            assert "ix_users_username_lower" not in _index_names(conn)
            assert conn.execute(text(
                "SELECT 1 FROM schema_migrations WHERE id='034_username_case_and_rename_time'")).first()
            assert conn.execute(text("SELECT COUNT(*) FROM users")).scalar() == 2


# ===========================================================================
# Story 2 — Reserved Words Can't Be Used in New Names
# ===========================================================================

class TestReservedWordsInNewNames:

    @pytest.mark.parametrize("raw, expected", [
        ("SuperAdmin1", "superadmini"),
        ("4dmin", "admin"),
        ("Kana_Liiga", "kanaliiga"),
        ("rn0d", "mod"),
        ("5UPP0R7", "support"),
        ("3-vv", "ew"),
        ("ordinary", "ordinary"),
    ])
    def test_normalise_username_maps_case_lookalikes_and_separators(self, raw, expected):
        """normalise_username lower-cases, maps 0→o 1→i 3→e 4→a 5→s 7→t rn→m vv→w, and removes _ and -."""
        from auth import normalise_username
        assert normalise_username(raw) == expected

    def test_reserved_words_default_list(self, monkeypatch):
        """With RESERVED_USERNAME_WORDS unset, reserved_words() is admin, kana, liiga, support, official, staff, mod."""
        from auth import reserved_words
        assert reserved_words() == {"admin", "kana", "liiga", "support", "official", "staff", "mod"}
        monkeypatch.setenv("RESERVED_USERNAME_WORDS", "  ")
        assert reserved_words() == {"admin", "kana", "liiga", "support", "official", "staff", "mod"}

    def test_reserved_words_env_trimmed_lowercased_empty_ignored(self, monkeypatch):
        """RESERVED_USERNAME_WORDS=' Foo, ,BAR,' gives exactly {'foo', 'bar'}, read at call time."""
        from auth import reserved_words
        monkeypatch.setenv("RESERVED_USERNAME_WORDS", " Foo, ,BAR,")
        assert reserved_words() == {"foo", "bar"}
        monkeypatch.setenv("RESERVED_USERNAME_WORDS", "baz")
        assert reserved_words() == {"baz"}

    def test_custom_reserved_words_replace_defaults(self, monkeypatch):
        """With RESERVED_USERNAME_WORDS='foo', 'admin' is accepted and 'xFOOx' is refused."""
        from auth import check_reserved
        monkeypatch.setenv("RESERVED_USERNAME_WORDS", "foo")
        check_reserved("admin")
        exc = _raises(check_reserved, "xFOOx")
        assert (exc.status_code, exc.detail) == (422, "This name is reserved")

    @pytest.mark.parametrize("name", _REFUSED_NAMES)
    def test_check_username_refuses_reserved_name(self, name):
        """Failure path: the reserved check (auth.check_reserved, run by the handlers) refuses a name whose normalised form contains a reserved word ('This name is reserved'); check_username itself checks only the format."""
        from auth import check_reserved, check_username
        assert check_username(name) == name
        exc = _raises(check_reserved, name)
        assert (exc.status_code, exc.detail) == (422, "This name is reserved")

    @pytest.mark.parametrize("name", ["Ville", "player_1", "dota-fan", "Puppey"])
    def test_check_username_accepts_ordinary_name(self, name):
        """check_username and the reserved check still accept ordinary ASCII names that contain no reserved word."""
        from auth import check_reserved, check_username, is_reserved
        assert check_username(name) == name
        check_reserved(name)
        assert is_reserved(name) is False

    def test_check_username_allow_reserved_skips_reserved_check(self):
        """check_username('admin') is accepted (the reserved check is separate, so env seeding can skip it); the ASCII pattern still applies."""
        from auth import check_username, is_reserved
        assert check_username("admin") == "admin"
        assert is_reserved("admin") is True
        with pytest.raises(ValueError):
            check_username("admin!")

    @pytest.mark.parametrize("name", _REFUSED_NAMES)
    def test_register_reserved_name_refused_422(self, web, mode, name):
        """POST /register with a reserved name answers 422 'This name is reserved' and creates no user."""
        from models import User
        mode("password")
        resp = web.client().post("/register", json={"username": name, "email": "new@example.com",
                                                     "password": "secret123"})
        assert resp.status_code == 422, resp.text
        assert resp.json()["detail"] == "This name is reserved"
        assert _count(web, User) == 0

    @pytest.mark.parametrize("name", ["SuperAdmin1", "4dmin", "Kana_Liiga", "rn0d"])
    def test_profile_rename_to_reserved_name_refused_422(self, db, name):
        """PUT /profile/username to a reserved name answers 422 'This name is reserved' and keeps the current name."""
        from models import User
        me = _mk(db, "Ville")
        exc = _raises(_rename, db, me, name)
        assert (exc.status_code, exc.detail) == (422, "This name is reserved")
        assert db.get(User, me.id).username == "Ville"
        assert db.get(User, me.id).username_changed_at is None

    @pytest.mark.parametrize("name", ["SuperAdmin1", "4dmin", "Kana_Liiga", "rn0d"])
    def test_steam_signup_reserved_name_refused_422(self, web, mode, monkeypatch, name):
        """POST /auth/steam/signup with a reserved name answers 422 'This name is reserved' and creates no user."""
        from models import User
        mode("both")
        client = web.client()
        resp, _ = _round_trip(client, monkeypatch)
        assert _key(resp, "welcome") == "choose_name"
        bad = client.post("/auth/steam/signup", json={"username": name})
        assert bad.status_code == 422, bad.text
        assert bad.json()["detail"] == "This name is reserved"
        assert _count(web, User) == 0
        assert client.post("/auth/steam/signup", json={"username": "fresh-name"}).status_code == 200

    def test_existing_reserved_name_still_logs_in(self, web, mode):
        """Failure path: an existing account named 'admin_old' still logs in with POST /login."""
        mode("password")
        web.add_user("admin_old")
        resp = web.client().post("/login", json={"username": "admin_old", "password": _PASSWORD})
        assert resp.status_code == 200, resp.text
        assert resp.json()["username"] == "admin_old"

    @pytest.mark.parametrize("new_name", ["admin_old", "ADMIN_OLD"])
    def test_existing_reserved_name_can_save_unchanged_name(self, db, new_name):
        """'admin_old' saving its unchanged name (or a case-only change) on Profile succeeds: the reserved check is skipped."""
        from models import User
        me = _mk(db, "admin_old")
        assert _rename(db, me, new_name)["username"] == new_name
        assert db.get(User, me.id).username == new_name

    def test_env_admin_seed_can_use_reserved_name(self, db, monkeypatch):
        """seed_admin_from_env creates an admin named 'admin' (env seeding skips the reserved check)."""
        from models import User
        _seed_env_admin(db, monkeypatch, "admin")
        user = db.query(User).filter_by(username="admin").first()
        assert user is not None and user.is_admin is True

    def test_demo_seed_names_pass_reserved_check(self, db, monkeypatch):
        """Every name POST /admin/demo/seed-accounts creates (demo1, demo2, ...) passes check_username's reserved check."""
        from auth import check_username, is_reserved
        result = _seed_demo(db, monkeypatch, count=5)
        names = [a["username"] for a in result["accounts"]]
        assert names == ["demo1", "demo2", "demo3", "demo4", "demo5"]
        assert all(check_username(n) == n and not is_reserved(n) for n in names)


# ===========================================================================
# Story 3 — Real Admins Carry a Badge
# ===========================================================================

class TestRealAdminsCarryABadge:

    @pytest.mark.parametrize("endpoint", _USER_ROW_ENDPOINTS)
    def test_user_rows_carry_is_admin_true_for_admin(self, db, endpoint):
        """Roster, season, weekly, archived-season standings and GET /profile/{user_id} rows carry is_admin (boolean), true for a real admin."""
        scene = _scene(db)
        body = _endpoint_body(db, endpoint, scene, scene["admin"])
        assert _row_for(body, scene["admin"])["is_admin"] is True
        assert all(isinstance(r["is_admin"], bool) for r in _identity_rows(body))

    @pytest.mark.parametrize("endpoint", _USER_ROW_ENDPOINTS)
    def test_lookalike_non_admin_has_is_admin_false(self, db, endpoint):
        """Failure path: a non-admin with the existing name 'Admin_Helper' has is_admin false on every row."""
        scene = _scene(db)
        body = _endpoint_body(db, endpoint, scene, scene["helper"])
        assert _row_for(body, scene["helper"])["is_admin"] is False

    @pytest.mark.parametrize("key, label", [
        ("admin", "Helper"),
        ("helper", "admin"),
        ("helper", "Admin"),
        ("helper", "ADMIN"),
    ])
    def test_create_tag_with_admin_key_or_label_refused(self, db, key, label):
        """POST /admin/tags refuses a tag whose key or label is 'admin' (any case) and creates nothing."""
        from models import TagDefinition
        from routers.admin_tags import TagBody, create_tag
        boss = _mk(db, "boss", is_admin=True)
        exc = _raises(create_tag, TagBody(key=key, label=label), db=db, admin=_acting(boss))
        assert exc.status_code == 422
        assert db.query(TagDefinition).count() == 0

    def test_create_tag_other_key_and_label_still_accepted(self, db):
        """POST /admin/tags still accepts ordinary tags such as key 'caster', label 'Caster'."""
        from models import TagDefinition
        from routers.admin_tags import TagBody, create_tag
        boss = _mk(db, "boss", is_admin=True)
        result = create_tag(TagBody(key="caster", label="Caster"), db=db, admin=_acting(boss))
        assert db.get(TagDefinition, result["id"]).label == "Caster"

    def test_frontend_leaderboards_render_admin_badge(self):
        """frontend/app-leaderboard.js renders an ADMIN badge next to the username when a row's is_admin is true."""
        lb = _read("app-leaderboard.js")
        assert lb.count("adminBadgeHtml(r.is_admin)") >= 2  # live standings + archived season
        assert re.search(r"_escHtml\(r\.username\)\}\$\{adminBadgeHtml\(r\.is_admin\)\}", lb)
        glob = _read("app-globals.js")
        fn = re.search(r"function adminBadgeHtml\(isAdmin\) \{(.*?)\n\}", glob, re.S).group(1)
        assert "isAdmin === true" in fn and 'class="admin-badge"' in fn and ">ADMIN<" in fn

    def test_frontend_profile_renders_admin_badge(self):
        """frontend/app-profile.js renders the ADMIN badge on the profile when is_admin is true."""
        assert "adminBadgeHtml(data.is_admin)" in _read("app-profile.js")
        assert 'id="profileAdminBadge"' in _read("index.html")

    def test_admin_badge_style_follows_design_system_and_differs_from_tags(self):
        """style.css: the admin badge uses display type, uppercase, the accent colour and a 2px radius (no pill), with a class distinct from user tags."""
        css = _read("style.css")
        block = _css_block(css, ".admin-badge")
        assert "var(--font-display)" in block
        assert "text-transform: uppercase" in block
        assert "var(--accent)" in block
        assert re.search(r"border-radius:\s*2px", block)
        assert "pill" not in block and "999" not in block and "50%" not in block
        assert "border-left" not in block
        size = re.search(r"font-size:\s*(\d+)px", block)
        assert size and int(size.group(1)) >= 11
        # Tag chips are filled flame chips (inline style / .tag-chip); the badge is outlined
        # and has its own class, which tag rendering never uses.
        assert "background: var(--accent-ghost)" in block
        tag_line = next(l for l in _read("app-leaderboard.js").splitlines() if "t.label" in l)
        assert "admin-badge" not in tag_line and "_escHtml(t.label)" in tag_line
        assert "admin-badge" not in _read("app-profile.js").split("tag-chip")[1].split("\n")[0]


# ===========================================================================
# Story 4 — Profiles Don't Lend Out Other Players' Identities
# ===========================================================================

class TestProfilesDontLendOutIdentities:

    def test_profile_other_viewer_never_gets_player_id(self, db):
        """GET /profile/{user_id} for another user's profile has no player_id key."""
        scene = _scene(db)
        for target in (scene["admin"], scene["helper"]):
            assert "player_id" not in _profile(db, target, scene["viewer"])

    def test_profile_other_viewer_verified_id_shows_avatar(self, db):
        """Another user's profile with steam_id set: player_verified true, player_name and player_avatar_url returned, no player_id."""
        from models import Player
        db.add(Player(id=55, name="Verified Guy", avatar_url="https://example.com/v.png"))
        target = _mk(db, "verified", player_id=55, steam_id="76561197960265783")
        viewer = _mk(db, "viewer")
        body = _profile(db, target, viewer)
        assert body["player_verified"] is True
        assert body["player_name"] == "Verified Guy"
        assert body["player_avatar_url"] == "https://example.com/v.png"
        assert "player_id" not in body

    def test_profile_other_viewer_self_reported_id_hides_avatar(self, db):
        """Failure path: another user's self-reported id of a well-known player returns that player's name, player_verified false, no player_avatar_url, no player_id."""
        scene = _scene(db)
        body = _profile(db, scene["helper"], scene["viewer"])
        assert body["player_name"] == "Famous Player"
        assert body["player_verified"] is False
        assert body.get("player_avatar_url") is None
        assert "player_id" not in body
        assert "987650002" not in json.dumps(body)

    def test_profile_self_view_includes_player_id(self, db):
        """The player viewing their own profile still gets the numeric player_id (plus player_verified)."""
        scene = _scene(db)
        body = _profile(db, scene["helper"], scene["helper"])
        assert body["player_id"] == 987650002
        assert body["player_verified"] is False
        assert body["player_avatar_url"] == "https://example.com/famous.png"

    def test_profile_admin_view_includes_player_id(self, db):
        """An admin viewing another user's profile still gets the numeric player_id."""
        from models import User
        scene = _scene(db)
        assert _profile(db, scene["helper"], scene["admin"])["player_id"] == 987650002
        # Decided by a fresh database lookup: a demoted admin's session no longer sees it.
        db.get(User, scene["admin"].id).is_admin = False
        db.commit()
        stale = {"user_id": scene["admin"].id, "username": "Boss", "is_admin": True}
        from routers.profile import get_profile
        assert "player_id" not in get_profile(scene["helper"].id, db=db, current_user=stale)

    @pytest.mark.parametrize("endpoint", ["leaderboard_roster", "leaderboard_season",
                                          "leaderboard_weekly", "leaderboard_archived_season",
                                          "weekly_summary_list", "weekly_summary_week",
                                          "profile_other_user"])
    def test_no_endpoint_returns_other_users_player_id(self, db, endpoint):
        """No response carrying other users' data (leaderboards, weekly report, season archive, profile/tags) has a player_id on a user-identity row."""
        scene = _scene(db)
        body = _endpoint_body(db, endpoint, scene, scene["helper"])
        rows = _identity_rows(body)
        if endpoint.startswith(("leaderboard", "profile")):
            assert rows
        assert all("player_id" not in r for r in rows), rows
        # The scene has no cards, so no league-player id can legitimately appear either.
        dumped = json.dumps(body, default=str)
        assert "987650001" not in dumped and "987650002" not in dumped

    def test_roster_of_other_user_forbidden_for_non_admin(self, db):
        """GET /roster/{user_id} for another user answers 403 to a non-admin (the roster view stays admin-only)."""
        from routers.cards import get_roster
        scene = _scene(db)
        exc = _raises(get_roster, scene["helper"].id, db=db, current_user=_acting(scene["viewer"]))
        assert exc.status_code == 403

    def test_frontend_profile_shows_verified_or_self_reported_label(self):
        """frontend/app-profile.js shows the in-game name with 'Verified with Steam' or 'Self-reported', and the avatar only when player_verified."""
        js = _read("app-profile.js")
        assert '"Verified with Steam"' in js and '"Self-reported"' in js
        assert "showPlayerPreview(name, verified ? avatarUrl : null)" in js
        assert "data.player_verified === true" in js
        assert 'id="profilePlayerSource"' in _read("index.html")

    def test_privacy_page_states_player_id_visibility(self):
        """frontend/privacy.html says a linked player id identifies a Steam account and is shown only to the player and to admins."""
        html = re.sub(r"\s+", " ", _read("privacy.html"))
        assert "A linked player id identifies a Steam account" in html
        assert "shows the number only to you and to admins" in html


# ===========================================================================
# Story 5 — Renames Are Limited
# ===========================================================================

class TestRenamesAreLimited:

    def test_user_model_has_username_changed_at(self):
        """models.User has username_changed_at (Integer, nullable)."""
        from sqlalchemy import Integer
        from models import User
        col = User.__table__.c.username_changed_at
        assert isinstance(col.type, Integer) and col.nullable is True

    def test_migration_034_adds_username_changed_at(self):
        """Migration 034 adds users.username_changed_at to a legacy database (PRAGMA-guarded, idempotent)."""
        from migrate import _m034_username_case_and_rename_time
        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as conn:
            conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, email TEXT)"))
            conn.execute(text("INSERT INTO users (id, username) VALUES (1, 'Ville')"))
            conn.commit()
            _m034_username_case_and_rename_time(conn)
            _m034_username_case_and_rename_time(conn)
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)")).fetchall()}
            assert "username_changed_at" in cols
            assert conn.execute(text("SELECT username_changed_at FROM users")).scalar() is None

    def test_first_rename_allowed_and_sets_username_changed_at(self, db):
        """A first rename (username_changed_at NULL) succeeds and sets username_changed_at to now."""
        from models import User
        me = _mk(db, "Ville")
        before = int(time.time())
        result = _rename(db, me, "Ville2")
        user = db.get(User, me.id)
        assert user.username == "Ville2"
        assert before <= user.username_changed_at <= int(time.time())
        assert result["username_change_available_at"] == user.username_changed_at + 7 * _DAY

    def test_second_rename_within_cooldown_refused_429_keeps_name(self, db):
        """Failure path: a second rename two days after the first answers 429 with the date it becomes possible, and keeps the current name."""
        from models import User
        last = int(time.time()) - 2 * _DAY
        me = _mk(db, "Ville", username_changed_at=last)
        exc = _raises(_rename, db, me, "Another")
        assert exc.status_code == 429
        expected = time.strftime("%Y-%m-%d", time.gmtime(last + 7 * _DAY))
        assert expected in exc.detail
        assert db.get(User, me.id).username == "Ville"
        assert db.get(User, me.id).username_changed_at == last

    def test_rename_after_cooldown_allowed(self, db):
        """A rename 7 days (default USERNAME_CHANGE_COOLDOWN_DAYS) after the last one succeeds."""
        me = _mk(db, "Ville", username_changed_at=int(time.time()) - 7 * _DAY)
        assert _rename(db, me, "Another")["username"] == "Another"

    @pytest.mark.parametrize("new_name", ["Ville", "VILLE", "ville"])
    def test_unchanged_or_case_only_change_does_not_count(self, db, new_name):
        """Saving the unchanged name or a case-only change within the cooldown succeeds and doesn't move username_changed_at."""
        from models import User
        last = int(time.time()) - _DAY
        me = _mk(db, "Ville", username_changed_at=last)
        assert _rename(db, me, new_name)["username"] == new_name
        assert db.get(User, me.id).username_changed_at == last

    def test_cooldown_zero_disables_limit(self, db, monkeypatch):
        """USERNAME_CHANGE_COOLDOWN_DAYS=0 lets a second rename right after the first succeed."""
        monkeypatch.setenv("USERNAME_CHANGE_COOLDOWN_DAYS", "0")
        me = _mk(db, "Ville")
        _rename(db, me, "First")
        result = _rename(db, me, "Second")
        assert result["username"] == "Second"
        assert result["username_change_available_at"] is None

    def test_custom_cooldown_days_respected(self, db, monkeypatch):
        """USERNAME_CHANGE_COOLDOWN_DAYS=1: a rename 2 days after the last succeeds, one 12 hours after answers 429."""
        monkeypatch.setenv("USERNAME_CHANGE_COOLDOWN_DAYS", "1")
        me = _mk(db, "Ville", username_changed_at=int(time.time()) - 2 * _DAY)
        assert _rename(db, me, "Renamed")["username"] == "Renamed"
        other = _mk(db, "Other", username_changed_at=int(time.time()) - _DAY // 2)
        assert _raises(_rename, db, other, "Other2").status_code == 429

    def test_profile_shows_next_rename_date(self, db):
        """Own Profile shows when the next rename is possible (frontend/app-profile.js reads it from the API)."""
        from routers.profile import me as me_endpoint
        last = int(time.time()) - _DAY
        user = _mk(db, "Ville", username_changed_at=last)
        assert me_endpoint(db=db, current_user=_acting(user))["username_change_available_at"] == last + 7 * _DAY
        fresh = _mk(db, "Fresh")
        assert me_endpoint(db=db, current_user=_acting(fresh))["username_change_available_at"] is None
        assert "data.username_change_available_at" in _read("app-auth.js")
        js = _read("app-profile.js")
        assert "You can rename again on ${when}" in js
        assert "activeUsernameChangeAvailableAt = data.username_change_available_at" in js
        assert 'id="profileRenameHint"' in _read("index.html")

    def test_env_example_documents_new_vars(self):
        """.env.example documents RESERVED_USERNAME_WORDS and USERNAME_CHANGE_COOLDOWN_DAYS."""
        env = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        assert "# RESERVED_USERNAME_WORDS=admin,kana,liiga,support,official,staff,mod" in env
        assert "# USERNAME_CHANGE_COOLDOWN_DAYS=7" in env


class TestReservedWordListEdgeCases:
    """Docs-check follow-up: the reserved list can't be emptied by accident, and its
    entries are normalised like names."""

    def test_commas_only_value_falls_back_to_defaults(self, monkeypatch):
        """RESERVED_USERNAME_WORDS=",,," has no usable entry, so the defaults apply and the check stays on."""
        import auth
        monkeypatch.setenv("RESERVED_USERNAME_WORDS", ", , ,")
        assert auth.reserved_words() == {"admin", "kana", "liiga", "support", "official", "staff", "mod"}
        assert auth.is_reserved("SuperAdmin1")

    def test_entries_are_normalised_like_names(self, monkeypatch):
        """An entry written with a look-alike or separator (m0d, kana_liiga) still matches names."""
        import auth
        monkeypatch.setenv("RESERVED_USERNAME_WORDS", "m0d, kana_liiga")
        assert auth.reserved_words() == {"mod", "kanaliiga"}
        assert auth.is_reserved("TheMod") and auth.is_reserved("KanaLiigaFan")
        assert not auth.is_reserved("admin")  # a custom list replaces the defaults
