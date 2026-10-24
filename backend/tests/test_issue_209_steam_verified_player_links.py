"""
Tests for plan-issue-209-steam-verified-player-links.md (resolves GitHub issue #209).

A player link exists only when `steam_id` and `player_id` are both set on a full,
non-demo account. Manual entry (`PUT /profile/player-id`) is removed, every reader
goes through `backend/player_links.py`, unlinking Steam clears `player_id`, and
migration 041 clears the old typed-in links once.

  Story 1: Only Steam Links an Account to a Player
  Story 2: Every Feature Trusts Only Verified Links
  Story 3: Typed-in Links Are Cleared Once

Approach notes (for the developer filling these in):

- Backend: `db` fixture; reuse the `web` / `mode` fixtures and `_acting`,
  `_STEAM32`, `_STEAM64`, `_function_source` from tests/test_issue_150_steam_login.py
  (as test_issue_188 does), and `_user` / `_linked_user` / `_player` style helpers
  from tests/test_issue_188_profile_identity_and_own_player_card.py. Sessions via
  `{"sid": sessions.create_session(db, user)}`; unlink needs a recent player re-auth
  (`require_recent_player_reauth`) when called through the route, or call
  `steam_openid.unlink(db, current_user)` directly.
- Route gone: drive a TestClient in each LOGIN_METHOD mode (password, both,
  steam_signup); today the route answers 410 in Steam modes and works in password
  mode, so these fail until the route is removed. Unmatched non-GET paths may fall
  through to the `/` static mount (lessons-learned: 405) in the full `main.app`;
  use an app with only the profile router (as the `web` fixture does), where an
  unknown path answers 404.
- Card tags: since issue #217 they are tag pips fed by GET /accolades `tags`
  (`_card_tag_keys`), no longer `tag_keys` passed to `image.generate_card_image`.
- Migration 041: the latest migration today is `040_cards_is_holo`. Build a legacy
  engine as in tests/test_migrate.py (`legacy_engine`) / test_issue_129_*, record
  earlier migrations as applied where needed, seed `users` rows and an
  `audit_log` table, then call `migrate.run_migrations(engine)`.
- Guard test: scan backend/*.py and backend/routers/*.py (not tests/, not
  scripts/ unless they read the link) for `users.player_id` in SQL text and
  `User.player_id` in ORM code; a hit outside the allow-list (player_links.py,
  steam_openid.py, migrate.py, routers/admin_users.py claims history) fails unless
  `steam_id` is in the same statement. Decide and document whether instance
  attribute reads such as `user.player_id` in own_card.has_grant_row count.
- Frontend Node harness: `_node_eval("app-profile.js", ["playerIdentityState"], ...)`
  as `_identity_state` in test_issue_188. Source-reading stubs use `_read` on
  frontend/app-profile.js and frontend/index.html.

Run with: cd backend && python -m pytest tests/test_issue_209_steam_verified_player_links.py -v
"""

import ast
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from sqlalchemy import create_engine, text

import models  # noqa: F401  (registers every table for the db fixture)

# `web` app and `mode` (LOGIN_METHOD + APP_BASE_URL) fixtures from the #150 tests.
from tests.test_issue_150_steam_login import (  # noqa: F401  (fixtures used by name)
    _STEAM32, _STEAM64, _acting, _round_trip, _signup, mode, web,
)
from tests.test_issue_188_profile_identity_and_own_player_card import (
    _OTHER_STEAM32, _OTHER_STEAM64, _identity_state, _linked_user, _player, _read, _user,
)

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

_STEAM_ME = {"steam_linked": False, "has_password": True, "is_demo": False}
_THIRD_STEAM64 = "76561198000000003"


def _audits(db, action):
    from models import AuditLog
    return db.query(AuditLog).filter(AuditLog.action == action).all()


def _profile(db, target, viewer):
    from routers.profile import get_profile
    return get_profile(target.id, db=db, current_user=_acting(viewer))


def _tag(db, user, key):
    from models import TagDefinition, UserTag
    td = db.query(TagDefinition).filter_by(key=key).first()
    if td is None:
        td = TagDefinition(key=key, label=key.title())
        db.add(td)
        db.flush()
    db.add(UserTag(user_id=user.id, tag_id=td.id))
    db.flush()


def _card_tag_keys(db, player_id):
    """The tag keys shown on player_id's cards: GET /accolades `tags` (issue #217
    moved card tags from image stickers to tag pips fed by this field)."""
    from routers.history import get_accolades
    return [t["key"] for t in get_accolades(db=db)["tags"].get(str(player_id), [])]


# ---------------------------------------------------------------------------
# Guard scanner. A read of the link is:
#   - ORM: the attribute `player_id` on the name `User` (User.player_id);
#   - instance: the attribute `player_id` on a name ending in "user" (user.player_id,
#     linked_user.player_id). Decision: these count too, so own_card.has_grant_row and
#     friends go through player_links and the rule stays "only player_links reads it";
#   - SQL: a string that reads the users table (FROM/JOIN/UPDATE/INTO users, or
#     users.player_id next to an upper-case SQL keyword) and mentions player_id.
# A hit passes when "steam_id" appears in the same Python statement.
# ---------------------------------------------------------------------------

_GUARD_ALLOW = {"player_links.py", "steam_openid.py", "migrate.py", "routers/admin_users.py"}
_SQL_USERS = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO)\s+users\b(?:\s+(?:AS\s+)?"
    r"(?!(?:ON|WHERE|SET|JOIN|LEFT|INNER|CROSS|GROUP|ORDER|LIMIT|VALUES)\b)(\w+))?", re.I)
_SQL_OTHER_TABLE = re.compile(r"\b(?:FROM|JOIN)\s+(?!users\b)\w+", re.I)
_SQL_COL = re.compile(r"\busers\.player_id\b")
_SQL_KEYWORD = re.compile(r"\b(SELECT|WHERE|UPDATE|JOIN)\b")


def _is_link_attr(node):
    if not (isinstance(node, ast.Attribute) and node.attr == "player_id"
            and isinstance(node.value, ast.Name)):
        return False
    name = node.value.id
    return name == "User" or name.lower().endswith("user")


def _is_users_sql(node):
    """A SQL string reading users.player_id: qualified by `users.` or the users alias,
    or unqualified in a statement whose only table is users."""
    if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
        return False
    s = node.value
    if "player_id" not in s:
        return False
    matches = list(_SQL_USERS.finditer(s))
    if not matches:
        return bool(_SQL_COL.search(s) and _SQL_KEYWORD.search(s))
    aliases = {"users"} | {m.group(1) for m in matches if m.group(1)}
    if any(re.search(r"\b%s\.player_id\b" % re.escape(a), s) for a in aliases):
        return True
    return bool(re.search(r"(?<![\w.])player_id\b", s) and not _SQL_OTHER_TABLE.search(s))


def _unverified_reads(src):
    """[(line, first line of the statement)] for unverified link reads in `src`."""
    tree = ast.parse(src)
    stmts = [n for n in ast.walk(tree) if isinstance(n, ast.stmt)
             and not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    hits = []
    for node in ast.walk(tree):
        if not (_is_link_attr(node) or _is_users_sql(node)):
            continue
        enclosing = [s for s in stmts if s.lineno <= node.lineno <= s.end_lineno]
        segment = ""
        if enclosing:
            stmt = min(enclosing, key=lambda s: s.end_lineno - s.lineno)
            segment = ast.get_source_segment(src, stmt) or ""
        if "steam_id" not in segment:
            hits.append((node.lineno, segment.strip().splitlines()[0] if segment.strip() else ""))
    return sorted(hits)


def _guard_files():
    files = sorted(BACKEND_DIR.glob("*.py")) + sorted((BACKEND_DIR / "routers").glob("*.py"))
    return [(f.relative_to(BACKEND_DIR).as_posix(), f) for f in files]


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------

_M041 = "041_clear_unverified_player_links"

_MIXED_USERS = [
    {"id": 1, "username": "typed1", "player_id": 111},
    {"id": 2, "username": "typed2", "player_id": 222},
    {"id": 3, "username": "steamer", "player_id": _STEAM32, "steam_id": _STEAM64},
    {"id": 4, "username": "nobody"},
]


def _migration_engine(users):
    """A full-schema database where every migration but 041 is recorded as applied."""
    import migrate
    from database import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        migrate._ensure_migrations_table(conn)
        for mid, _ in migrate.MIGRATIONS:
            if mid != _M041:
                migrate._record(conn, mid)
        for u in users:
            conn.execute(text(
                "INSERT INTO users (id, username, player_id, steam_id, account_type, is_demo, session_version) "
                "VALUES (:id, :username, :player_id, :steam_id, 'full', 0, 0)"),
                {"player_id": None, "steam_id": None, **u})
        conn.commit()
    return engine


def _rows(engine, sql, **params):
    with engine.connect() as conn:
        return conn.execute(text(sql), params).fetchall()


def _player_ids(engine):
    return {r[0]: r[1] for r in _rows(engine, "SELECT id, player_id FROM users")}


def _cleared_audits(engine):
    return _rows(engine, "SELECT actor_username, detail FROM audit_logs "
                         "WHERE action = 'player_links_cleared'")


# ===========================================================================
# Story 1: Only Steam Links an Account to a Player
# ===========================================================================

class TestOnlySteamLinksAnAccountToAPlayer:

    @pytest.mark.parametrize("login_method", ["password", "both", "steam_signup"])
    def test_put_profile_player_id_returns_404_in_every_login_mode(self, web, mode, login_method):
        """Route removed: PUT /profile/player-id answers 404 in password, both and steam_signup modes."""
        mode(login_method)
        web.add_user("alice")
        client = web.login("alice")
        resp = client.put("/profile/player-id", json={"player_id": 4242})
        assert resp.status_code == 404

    def test_put_profile_player_id_404_changes_nothing(self, web, mode):
        """Failure path: a PUT /profile/player-id request (password mode) leaves users.player_id unchanged and writes no audit entry."""
        from models import AuditLog, User
        mode("password")
        uid = web.add_user("alice", player_id=777)
        client = web.login("alice")
        audits_before = len(web.rows(AuditLog))
        assert client.put("/profile/player-id", json={"player_id": 4242}).status_code == 404
        assert web.get(User, uid).player_id == 777
        assert len(web.rows(AuditLog)) == audits_before

    def test_update_player_id_and_body_model_removed_from_profile_router(self):
        """routers/profile.py no longer defines update_player_id or UpdatePlayerIdBody."""
        from routers import profile
        for name in ("update_player_id", "update_player_id_route", "UpdatePlayerIdBody"):
            assert not hasattr(profile, name), name
        src = (BACKEND_DIR / "routers" / "profile.py").read_text(encoding="utf-8")
        assert '"/profile/player-id"' not in src

    def test_steam_link_still_sets_player_id_from_steam_id(self, web, mode, monkeypatch):
        """Steam sets the link: Link Steam still sets player_id from the Steam id, unchanged."""
        from models import User
        mode("both")
        uid = web.add_user("alice")
        _round_trip(web.login("alice"), monkeypatch, purpose="link")
        user = web.get(User, uid)
        assert user.steam_id == _STEAM64 and user.player_id == _STEAM32

    def test_steam_signup_still_sets_player_id_from_steam_id(self, web, mode, monkeypatch):
        """Steam sets the link: Steam sign-up still sets player_id from the Steam id, unchanged."""
        from models import User
        mode("steam_signup")
        _signup(web, web.client(), monkeypatch, username="newbie")
        [user] = web.rows(User, username="newbie")
        assert user.steam_id == _STEAM64 and user.player_id == _STEAM32

    def test_unlink_clears_player_id_in_same_transaction(self, db, monkeypatch):
        """Unlinking Steam clears steam_id and player_id together in one commit."""
        import steam_openid
        user = _linked_user(db, password_hash="x")
        db.commit()
        commits = []
        real_commit = db.commit

        def counting_commit():
            commits.append((user.steam_id, user.player_id))
            real_commit()

        monkeypatch.setattr(db, "commit", counting_commit)
        result = steam_openid.unlink(db, _acting(user))
        assert result == {"steam_linked": False, "changed": True}
        assert commits == [(None, None)]
        db.expire_all()
        assert user.steam_id is None and user.player_id is None

    def test_unlink_audit_detail_adds_player_id_cleared(self, db):
        """The steam_unlinked audit detail adds player_id_cleared=1 when a player_id was set."""
        import steam_openid
        user = _linked_user(db, password_hash="x")
        db.commit()
        steam_openid.unlink(db, _acting(user))
        [audit] = _audits(db, "steam_unlinked")
        assert audit.detail == f"user_id={user.id} player_id_cleared=1"
        assert _STEAM64 not in audit.detail and str(_STEAM32) not in audit.detail

    def test_unlink_without_player_id_audit_has_no_player_id_cleared(self, db):
        """Failure path: unlinking an account whose player_id was already NULL writes steam_unlinked without player_id_cleared."""
        import steam_openid
        user = _user(db, password_hash="x", steam_id=_STEAM64)
        db.commit()
        steam_openid.unlink(db, _acting(user))
        [audit] = _audits(db, "steam_unlinked")
        assert audit.detail == f"user_id={user.id}"

    def test_unlink_steam_only_account_409_keeps_player_id(self, db):
        """Failure path: a Steam-only account (no password) gets 409 on unlink and keeps steam_id and player_id."""
        from fastapi import HTTPException
        import steam_openid
        user = _linked_user(db)
        db.commit()
        with pytest.raises(HTTPException) as exc:
            steam_openid.unlink(db, _acting(user))
        assert exc.value.status_code == 409
        db.refresh(user)
        assert user.steam_id == _STEAM64 and user.player_id == _STEAM32
        assert _audits(db, "steam_unlinked") == []

    @pytest.mark.parametrize("login_method", ["both", "steam_signup"])
    def test_frontend_player_identity_state_steam_modes_keep_three_states(self, login_method):
        """Node harness: in Steam modes playerIdentityState returns only linked, linked_no_match or not_linked."""
        linked_me = {**_STEAM_ME, "steam_linked": True}
        cases = [
            (linked_me, {"player_id": _STEAM32, "player_name": "Meatstorm"}, "linked"),
            (linked_me, {"player_id": _STEAM32}, "linked_no_match"),
            (_STEAM_ME, {}, "not_linked"),
            (_STEAM_ME, {"player_id": 4242, "player_name": "Legacy"}, "not_linked"),
            (None, None, "not_linked"),
        ]
        for me, profile, expected in cases:
            state = _identity_state(login_method, me, profile)
            if state is None:
                pytest.skip("Node not installed")
            assert state == expected, (me, profile)

    def test_frontend_player_identity_state_stale_player_id_is_not_linked(self):
        """Node harness: Steam mode, me.steam_linked false and a profile with a player_id gives "not_linked", never "self_reported"."""
        state = _identity_state("both", _STEAM_ME, {"player_id": 4242, "player_name": "Legacy"})
        if state is None:
            pytest.skip("Node not installed")
        assert state == "not_linked"

    def test_frontend_player_identity_state_password_mode_has_no_password_state(self):
        """Node harness: password mode returns a dedicated steam-required state, not "password" or "self_reported"."""
        for profile in ({}, {"player_id": 4242, "player_name": "Legacy"}):
            state = _identity_state("password", _STEAM_ME, profile)
            if state is None:
                pytest.skip("Node not installed")
            assert state == "steam_required"

    def test_frontend_no_self_reported_or_password_field_state_in_source(self):
        """Source-reading: app-profile.js has no "self_reported" state, no identityLegacyHint, no playerIdForm handler or show() call."""
        js = _read("app-profile.js")
        for needle in ("self_reported", "identityLegacyHint", "playerIdForm", "savePlayerId",
                       "profilePlayerId", '"password"', "Self-reported", "/profile/player-id"):
            assert needle not in js, needle
        assert "playerIdField" not in _read("app-auth.js")

    def test_frontend_index_html_removes_player_id_form_and_legacy_hint(self):
        """Source-reading: index.html has no #playerIdForm, #profilePlayerId input or #identityLegacyHint."""
        html = _read("index.html")
        for needle in ('id="playerIdForm"', 'id="profilePlayerId"', 'id="identityLegacyHint"',
                       'id="btnSavePlayerId"', "savePlayerId("):
            assert needle not in html, needle

    def test_frontend_password_mode_shows_steam_required_note(self):
        """Source-reading: index.html holds the "Player linking needs Steam sign-in" note and app-profile.js shows it only in password mode, with no field or button."""
        html = _read("index.html")
        m = re.search(r'<p id="identitySteamRequired"[^>]*>([^<]*)</p>', html)
        assert m, "identitySteamRequired note missing"
        assert "Player linking needs Steam sign-in" in m.group(1)
        assert 'style="display:none;"' in m.group(0)
        js = _read("app-profile.js")
        assert 'show("identitySteamRequired", state === "steam_required");' in js
        # No field or button in password mode: Link Steam follows steamUiState, which is
        # off without Steam, and the note holds no input or button.
        assert "<input" not in m.group(0) and "<button" not in m.group(0)
        assert 'show("btnLinkSteam", ui.linkSteam);' in js


# ===========================================================================
# Story 2: Every Feature Trusts Only Verified Links
# ===========================================================================

class TestEveryFeatureTrustsOnlyVerifiedLinks:

    # --- helper: backend/player_links.py ---

    def test_verified_player_id_returns_player_for_steam_linked_full_account(self, db):
        """verified_player_id(user) returns player_id when steam_id and player_id are set on a full, non-demo account."""
        import player_links
        user = _linked_user(db)
        assert player_links.verified_player_id(user) == _STEAM32

    @pytest.mark.parametrize("case", ["no_steam_id", "no_player_id", "demo", "soft", "none"])
    def test_verified_player_id_returns_none_without_verified_link(self, db, case):
        """Failure path: verified_player_id is None without steam_id, without player_id, for demo or soft accounts, and for None."""
        import player_links
        user = {
            "no_steam_id": lambda: _user(db, player_id=_STEAM32),
            "no_player_id": lambda: _user(db, steam_id=_STEAM64),
            "demo": lambda: _linked_user(db, is_demo=True),
            "soft": lambda: _linked_user(db, None, account_type="twitch"),
            "none": lambda: None,
        }[case]()
        assert player_links.verified_player_id(user) is None

    def test_verified_users_for_player_returns_only_verified_users(self, db):
        """verified_users_for_player(db, pid) returns the Steam-verified full accounts linked to pid and skips stale, demo and soft ones."""
        import player_links
        _user(db, "stale", player_id=_STEAM32)
        _user(db, "demo", steam_id=_OTHER_STEAM64, player_id=_STEAM32, is_demo=True)
        _user(db, None, steam_id=_THIRD_STEAM64, player_id=_STEAM32, account_type="twitch")
        verified = _linked_user(db, "alice")
        db.commit()
        assert [u.id for u in player_links.verified_users_for_player(db, _STEAM32)] == [verified.id]
        assert player_links.verified_users_for_player(db, None) == []

    def test_verified_users_for_player_empty_for_unverified_claim(self, db):
        """Failure path: a player claimed only by an account without steam_id has no verified users."""
        import player_links
        _user(db, "claimant", player_id=4242)
        db.commit()
        assert player_links.verified_users_for_player(db, 4242) == []

    def test_verified_links_maps_user_id_to_player_id(self, db):
        """verified_links(db) returns {user_id: player_id} for verified full, non-demo accounts only."""
        import player_links
        alice = _linked_user(db, "alice")
        bob = _linked_user(db, "bob", steam64=_OTHER_STEAM64)
        _user(db, "stale", player_id=999)
        _user(db, "demo", steam_id=_THIRD_STEAM64, player_id=998, is_demo=True)
        db.commit()
        assert player_links.verified_links(db) == {alice.id: _STEAM32, bob.id: _OTHER_STEAM32}

    # --- delegation ---

    def test_own_card_is_candidate_delegates_to_helper(self, db, monkeypatch):
        """own_card.is_candidate agrees with player_links.verified_player_id (patching the helper changes the answer)."""
        import own_card
        import player_links
        linked = _linked_user(db, "alice")
        stale = _user(db, "stale", player_id=4242)
        assert own_card.is_candidate(linked) is True and own_card.is_candidate(stale) is False
        monkeypatch.setattr(player_links, "verified_player_id",
                            lambda u: 4242 if u is stale else None)
        assert own_card.is_candidate(linked) is False and own_card.is_candidate(stale) is True

    def test_accolades_linked_users_delegates_to_helper(self, db, monkeypatch):
        """accolades._linked_users returns player_links.verified_links(db) (patching the helper changes the answer)."""
        import accolades
        import player_links
        alice = _linked_user(db, "alice")
        db.commit()
        assert accolades._linked_users(db) == {alice.id: _STEAM32}
        monkeypatch.setattr(player_links, "verified_links", lambda _db: {99: 7})
        assert accolades._linked_users(db) == {99: 7}

    # --- profile response ---

    def test_profile_owner_view_hides_stale_unverified_player_id(self, db):
        """GET /profile/{own id} for an account with player_id but no steam_id returns no player_id, player_name, player_avatar_url or player_team_name."""
        _player(db, pid=4242, name="Somebody")
        stale = _user(db, "stale", player_id=4242)
        db.commit()
        data = _profile(db, stale, stale)
        assert data["player_id"] is None
        assert data["player_name"] is None and data["player_avatar_url"] is None
        assert data.get("player_team_name") is None and data["player_verified"] is False

    def test_profile_admin_view_hides_stale_unverified_player_id(self, db):
        """An admin viewing an account with a stale player_id (no steam_id) gets no player_id and no player fields."""
        _player(db, pid=4242, name="Somebody")
        stale = _user(db, "stale", player_id=4242)
        admin = _user(db, "boss", is_admin=True)
        db.commit()
        data = _profile(db, stale, admin)
        assert data["player_id"] is None
        assert data["player_name"] is None and data["player_avatar_url"] is None
        assert data.get("player_team_name") is None

    def test_profile_other_viewer_hides_stale_unverified_player(self, db):
        """Another user viewing an account with a stale player_id gets no player_name, avatar or team name."""
        _player(db, pid=4242, name="Somebody")
        stale = _user(db, "stale", player_id=4242)
        viewer = _user(db, "viewer")
        db.commit()
        data = _profile(db, stale, viewer)
        assert "player_id" not in data
        assert data["player_name"] is None and data["player_avatar_url"] is None
        assert data.get("player_team_name") is None

    def test_profile_verified_link_returns_player_fields(self, db):
        """A Steam-verified account's profile returns player_name, player_avatar_url, player_team_name, and player_id to the owner and admins only."""
        from models import Match, PlayerMatchStats, Team
        player = _player(db)
        player.avatar_url = "https://avatars.example/m.png"
        db.add(Team(id=10, name="Chickens"))
        db.add(Match(match_id=1, start_time=1000))
        db.add(PlayerMatchStats(player_id=player.id, match_id=1, team_id=10))
        alice = _linked_user(db, "alice")
        admin = _user(db, "boss", is_admin=True)
        viewer = _user(db, "viewer")
        db.commit()
        for who in (alice, admin):
            data = _profile(db, alice, who)
            assert data["player_id"] == _STEAM32
            assert data["player_name"] == "Meatstorm"
            assert data["player_avatar_url"] == "https://avatars.example/m.png"
            assert data["player_team_name"] == "Chickens" and data["player_verified"] is True
        public = _profile(db, alice, viewer)
        assert "player_id" not in public
        assert public["player_name"] == "Meatstorm" and public["player_team_name"] == "Chickens"

    # --- card tags (stickers until issue #217, now tag pips from GET /accolades) ---

    def test_card_tags_from_verified_user(self, db):
        """A card's tags come from the user with a verified link to the card's player."""
        _player(db)
        alice = _linked_user(db, "alice")
        _tag(db, alice, "caster")
        db.commit()
        assert _card_tag_keys(db, _STEAM32) == ["caster"]

    def test_card_stale_player_id_adds_no_tags(self, db):
        """Failure path: a tagged account holding the card's player_id without steam_id adds no card tags."""
        _player(db, pid=4242, name="Somebody")
        claimant = _user(db, "claimant", player_id=4242)
        _tag(db, claimant, "caster")
        db.commit()
        assert _card_tag_keys(db, 4242) == []

    def test_card_prefers_verified_user_over_earlier_stale_claim(self, db):
        """With a stale claimant (lower user id) and a verified user on the same player, only the verified user's tags appear."""
        _player(db)
        claimant = _user(db, "claimant", player_id=_STEAM32)
        _tag(db, claimant, "impostor")
        alice = _linked_user(db, "alice")
        _tag(db, alice, "caster")
        db.commit()
        assert claimant.id < alice.id
        assert _card_tag_keys(db, _STEAM32) == ["caster"]

    # --- guard ---

    def test_guard_no_unverified_player_id_reads_outside_allow_list(self):
        """Guard: no backend code outside player_links.py, steam_openid.py, migrate.py and admin_users.py claims history reads users.player_id / User.player_id without steam_id.

        A tripwire, not a proof: it catches the usual spellings (User.player_id,
        <...>user.player_id, SQL reading users.player_id) but not every alias, getattr or
        row["player_id"]. New code should call player_links instead of reading the column."""
        offenders = []
        scanned = set()
        for rel, path in _guard_files():
            scanned.add(rel)
            if rel in _GUARD_ALLOW:
                continue
            for line, snippet in _unverified_reads(path.read_text(encoding="utf-8")):
                offenders.append(f"{rel}:{line}: {snippet}")
        assert {"routers/cards.py", "routers/profile.py", "own_card.py", "accolades.py"} <= scanned
        assert not offenders, "Read the player link through player_links:\n" + "\n".join(offenders)

    def test_guard_detects_planted_unverified_read(self):
        """Failure path: the guard's scanner flags a sample source line reading users.player_id without steam_id."""
        planted = (
            "from sqlalchemy import text\n"
            "def f(db, pid, user):\n"
            "    row = db.execute(text('SELECT id FROM users WHERE player_id = :pid'), {'pid': pid})\n"
            "    q = db.query(User).filter(User.player_id == pid)\n"
            "    db.execute(text('SELECT u.id FROM users u JOIN cards c ON c.player_id = u.player_id'))\n"
            "    return user.player_id\n"
        )
        assert [line for line, _ in _unverified_reads(planted)] == [3, 4, 5, 6]
        verified = (
            "def g(db, pid, user):\n"
            "    q = db.query(User).filter(User.player_id == pid, User.steam_id.isnot(None))\n"
            "    ok = bool(user.steam_id and user.player_id)\n"
            "    card_pid = card.player_id\n"
            "    'The player_id of the card.'\n"
            "    db.execute(text('SELECT u.id FROM users u JOIN cards c ON c.owner_id = u.id '\n"
            "                    'JOIN player_match_stats s ON s.player_id = c.player_id'))\n"
        )
        assert _unverified_reads(verified) == []


# ===========================================================================
# Story 3: Typed-in Links Are Cleared Once
# ===========================================================================

class TestTypedInLinksAreClearedOnce:

    def test_migration_041_clears_player_id_without_steam_id(self):
        """Migration 041_clear_unverified_player_links sets player_id = NULL for users with player_id set and steam_id NULL."""
        import migrate
        engine = _migration_engine(_MIXED_USERS)
        migrate.run_migrations(engine)
        ids = _player_ids(engine)
        assert ids[1] is None and ids[2] is None and ids[4] is None

    def test_migration_041_keeps_steam_verified_links(self):
        """Accounts with steam_id keep their player_id after migration 041."""
        import migrate
        engine = _migration_engine(_MIXED_USERS)
        migrate.run_migrations(engine)
        assert _player_ids(engine)[3] == _STEAM32
        assert _rows(engine, "SELECT steam_id FROM users WHERE id = 3")[0][0] == _STEAM64

    def test_migration_041_writes_one_audit_entry_with_count(self):
        """Migration 041 writes exactly one player_links_cleared audit entry with count=N."""
        import migrate
        engine = _migration_engine(_MIXED_USERS)
        migrate.run_migrations(engine)
        rows = _cleared_audits(engine)
        assert len(rows) == 1
        assert rows[0][0] == "system" and "count=2" in rows[0][1].split()

    def test_migration_041_no_audit_entry_when_nothing_cleared(self):
        """Failure path: with no unverified links (N=0) migration 041 writes no player_links_cleared entry."""
        import migrate
        engine = _migration_engine([u for u in _MIXED_USERS if u["id"] in (3, 4)])
        migrate.run_migrations(engine)
        assert _cleared_audits(engine) == []
        assert _player_ids(engine) == {3: _STEAM32, 4: None}

    def test_migration_041_idempotent_second_run_changes_nothing(self):
        """A second run_migrations changes no rows and writes no second player_links_cleared entry."""
        import migrate
        engine = _migration_engine(_MIXED_USERS)
        migrate.run_migrations(engine)
        after_first = _player_ids(engine)
        migrate.run_migrations(engine)
        assert _player_ids(engine) == after_first
        assert len(_cleared_audits(engine)) == 1
        # The function itself is idempotent too, even when called again directly.
        with engine.connect() as conn:
            migrate._m041_clear_unverified_player_links(conn)
        assert _player_ids(engine) == after_first
        assert len(_cleared_audits(engine)) == 1

    def test_migration_041_recorded_in_schema_migrations(self):
        """041_clear_unverified_player_links is listed in migrate.py and recorded as applied."""
        import migrate
        assert _M041 in [name for name, _ in migrate.MIGRATIONS]
        engine = _migration_engine(_MIXED_USERS)
        migrate.run_migrations(engine)
        assert _rows(engine, "SELECT id FROM schema_migrations WHERE id = :id", id=_M041)

    def test_migration_doc_says_run_backup_first(self):
        """Deploy note: the migration doc (player-linking doc) tells operators to run scripts/backup-db.sh before deploying 041."""
        doc = (REPO_ROOT / "markdown" / "features" / "reference"
               / "player-linking-and-tag-visibility.md").read_text(encoding="utf-8")
        assert _M041 in doc
        assert "bash scripts/backup-db.sh" in doc


def test_unlink_confirm_text_says_player_link_is_removed():
    """The Unlink Steam confirmation tells the user their player link goes too."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "frontend" / "app-profile.js").read_text()
    assert "player id stays" not in src
    assert "This also removes your player link." in src
