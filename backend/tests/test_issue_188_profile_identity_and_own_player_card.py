"""
Tests for plan-issue-188-profile-identity-and-own-player-card.md (resolves GitHub issue #188).

Profile's Steam and Dota 2 Player panels merge into one "Player identity" panel;
manual OpenDota linking (`PUT /profile/player-id`) answered 410 unless
`LOGIN_METHOD=password`; issue #209 removed it (tests updated to match). A Steam-verified league player gets one common card of
themselves, recorded once in the new `own_player_card_grants` table, with a popup
on the next page load (`GET /me` -> `own_card_grant`, dismissed with
`POST /profile/own-card-grant/seen`). One class per user story; one test per
acceptance criterion plus the primary failure path.

Developer notes
---------------

  Code vs plan
    - `GET /me` lives in `routers/profile.py` (not `routers/auth.py` as the plan's
      Critical Files table says). Hook the lazy grant there.
    - `_activate_new_card(db, card, user_id)` is in `routers/cards.py`;
      `_assign_modifiers` in `card_utils.py`; `_pick_player` /
      `_pick_player_from_team` in `card_draw.py`.
    - Steam hooks: `steam_openid.link_account` and `steam_openid.signup`, after
      `_supersede_player_id_claims`.

  Verified vs self-reported ids
    - Follow tests/test_issue_169_impersonation_hardening.py: a user with
      `player_id` set but no `steam_id` is self-reported and never qualifies.

  Steam / LOGIN_METHOD
    - Reuse the `web` fixture, `_mock_steam` and `_id_res_params` patterns from
      tests/test_issue_150_steam_login.py (copy underscore helpers, never import
      test functions). Never hit steamcommunity.com. HTTP-level stubs take `db`
      for now; switch them to a local `web` fixture when filling them in.

  Insert-once grant
    - Like `twitch_starter_grants` (tests/test_issue_187_*): `INSERT ... ON CONFLICT
      DO NOTHING` on unique `user_id` and unique `player_id`; create the card only
      when `rowcount == 1`.

  Concurrency
    - Reuse `file_db_sessionmaker` / `_run_concurrently` from
      tests/test_issue_185_atomic_roster_and_token_operations.py (WAL file SQLite +
      `threading.Barrier`). Run it against code without the ON CONFLICT guard first
      and confirm it fails (lessons-learned 2026-10-13).
"""

import json
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time

import pytest

# Registers every existing table on Base before the conftest db fixture runs
# create_all. The new OwnPlayerCardGrant model is imported inside tests.
import models  # noqa: F401

# Fixtures and underscore helpers from the Steam sign-in tests (issue #150): the
# `web` app (auth, Steam, profile routers on a thread-safe in-memory DB), `mode`
# (LOGIN_METHOD + APP_BASE_URL) and the mocked OpenID round trip. Never hits Steam.
from tests.test_issue_150_steam_login import (  # noqa: F401  (fixtures used by name)
    _STEAM32, _STEAM64, _acting, _function_source, _round_trip, _signup, _key, mode, web,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"

_OTHER_STEAM64 = "76561198000000002"
_OTHER_STEAM32 = int(_OTHER_STEAM64) - 76561197960265728


def _read(name):
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


def _node_eval(src_file, fn_names, expr):
    """Evaluate `expr` under Node with the named pure functions from a frontend file;
    None when Node is missing."""
    node = shutil.which("node")
    if node is None:
        return None
    src = _read(src_file)
    code = "\n".join(_function_source(src, n) for n in fn_names)
    code += "\nconsole.log(JSON.stringify(" + expr + "));"
    out = subprocess.run([node, "-e", code], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def _identity_state(login_method, me, profile):
    return _node_eval("app-profile.js", ["playerIdentityState"],
                      f"playerIdentityState({json.dumps(login_method)}, {json.dumps(me)}, "
                      f"{json.dumps(profile)})")


def _steam_ui(login_method, me):
    return _node_eval("app-auth.js", ["steamUiState"],
                      f"steamUiState({json.dumps(login_method)}, {json.dumps(me)})")


def _seed_weights(db):
    from models import Weight
    for key, value in (("modifier_count_common", 1), ("modifier_bonus_pct", 10.0)):
        if db.get(Weight, key) is None:
            db.add(Weight(key=key, label=key, value=value))
    db.flush()


def _player(db, pid=_STEAM32, name="Meatstorm", is_active=True):
    from models import Player
    p = Player(id=pid, name=name, is_active=is_active)
    db.add(p)
    db.flush()
    return p


def _user(db, username="alice", **fields):
    from models import User
    fields.setdefault("tokens", 5)
    fields.setdefault("created_at", int(time.time()))
    u = User(username=username, **fields)
    db.add(u)
    db.flush()
    return u


def _linked_user(db, username="alice", steam64=_STEAM64, **fields):
    return _user(db, username, steam_id=steam64,
                 player_id=int(steam64) - 76561197960265728, **fields)


def _card(db, owner_id, player_id, is_active=False, card_type="common"):
    from models import Card
    c = Card(owner_id=owner_id, player_id=player_id, card_type=card_type,
             is_active=is_active, generation=1)
    db.add(c)
    db.flush()
    return c


def _cards(db, owner_id, player_id=None):
    from models import Card
    q = db.query(Card).filter(Card.owner_id == owner_id)
    if player_id is not None:
        q = q.filter(Card.player_id == player_id)
    return q.all()


def _grants(db):
    from models import OwnPlayerCardGrant
    return db.query(OwnPlayerCardGrant).all()


def _grant(db, user):
    from own_card import grant_own_player_card
    _seed_weights(db)
    result = grant_own_player_card(db, user)
    db.commit()
    return result


def _me(db, user):
    from routers.profile import me
    return me(db=db, current_user=_acting(user))


def _web_seed(web, fn):
    db = web.Session()
    try:
        out = fn(db)
        db.commit()
        return out
    finally:
        db.close()


def _web_count_cards(web, owner_id=None):
    from models import Card
    rows = web.rows(Card) if owner_id is None else web.rows(Card, owner_id=owner_id)
    return len(rows)


# ---------------------------------------------------------------------------
# Story 1 — One Clear Identity Panel on Profile
# ---------------------------------------------------------------------------

class TestOneClearIdentityPanelOnProfile:
    """
    Acceptance criteria:
    - "Profile shows four panels: Account (username, password or Steam-only sign-in,
      sessions), Player identity (replaces the Steam and Dota 2 Player panels, and
      holds Your Tags), Twitch (unchanged) and Past seasons (unchanged, when present)"
    - "Player identity, not linked: one sentence on what linking does (...), plus Link Steam"
    - "Player identity, linked: Steam linked and the matched league player's avatar,
      name and team, or 'No league player matches this Steam account' when none
      exists; the account's tags as chips, or 'No tags'; Unlink Steam for accounts
      with a password, as today."
    - "No OpenDota account id field when LOGIN_METHOD is both or steam_signup;
      PUT /profile/player-id answers 410 'Link Steam to verify your player id'"
    - "With LOGIN_METHOD=password, the panel keeps the id field, labelled 'Self-reported'"
    - "An existing self-reported id is shown read-only with 'Self-reported, link
      Steam to verify'; tags still show"
    - "The Steam id itself is never shown, as today"
    """

    @staticmethod
    def _profile_tab():
        html = _read("index.html")
        start = html.index('<div id="tab-profile"')
        return html[start:html.index("<!-- TAB: MY TEAM -->", start)]

    def test_profile_html_has_four_panels_and_no_separate_steam_or_dota_panel(self):
        """Profile markup has Account, Player identity, Twitch and Past seasons panels; the old Steam and Dota 2 Player panels are gone."""
        tab = self._profile_tab()
        titles = re.findall(r'<div class="panel[^"]*"[^>]*>\s*(?:<div[^>]*>\s*)?<h2>([^<]+)</h2>', tab)
        assert titles == ["Player identity", "Account", "Twitch", "Past Seasons"], titles
        assert 'id="steamProfilePanel"' not in tab
        assert "Dota 2 Player" not in tab
        assert "<h2>Steam</h2>" not in tab and "<h2>Your Tags</h2>" not in tab
        # Player identity spans the full width at the top.
        assert tab.index('id="profileIdentityPanel"') < tab.index("<h2>Account</h2>")
        assert ".profile-grid .profile-identity { grid-column: 1 / -1; }" in _read("style.css")

    def test_player_identity_panel_holds_your_tags(self):
        """Your Tags is rendered inside the Player identity panel, as chips or 'No tags'."""
        tab = self._profile_tab()
        panel = tab[tab.index('id="profileIdentityPanel"'):tab.index("<h2>Account</h2>")]
        assert "Your Tags" in panel and 'id="profileTagsContainer"' in panel
        js = _read("app-profile.js")
        assert 'tags.map(t => tagBadgeHtml(t)).join("")' in js  # issue #202: role badges
        assert ">No tags</span>" in js

    def test_player_identity_not_linked_state_explains_linking_and_offers_link_steam(self):
        """Not linked: one sentence on what linking does plus a Link Steam button."""
        tab = self._profile_tab()
        copy = re.search(r'id="identityLinkCopy">([^<]+)<', tab).group(1)
        assert "verify which league player you are" in copy
        assert "tags then show on your cards and next to your name on the leaderboard" in copy
        assert "your own player card, once" in copy
        assert copy.count(". ") == 0  # one sentence
        assert 'id="btnLinkSteam" onclick="linkSteam()"' in tab
        me = {"steam_linked": False, "has_password": True, "is_demo": False}
        for method in ("both", "steam_signup"):
            state = _identity_state(method, me, {"player_id": None})
            if state is None:
                return
            assert state == "not_linked"
            assert _steam_ui(method, me)["linkSteam"] is True

    def test_player_identity_linked_state_shows_matched_player_or_no_match_text(self):
        """Linked: 'Steam linked' with the matched player's avatar, name and team, or 'No league player matches this Steam account'."""
        tab = self._profile_tab()
        assert "Steam linked" in tab and 'id="identitySteamLinked"' in tab
        for el in ("profilePlayerAvatar", "profilePlayerName", "profilePlayerTeam"):
            assert f'id="{el}"' in tab
        assert "No league player matches this Steam account" in tab
        js = _read("app-profile.js")
        assert "profile.player_team_name" in js
        me = {"steam_linked": True, "has_password": True, "is_demo": False}
        state = _identity_state("both", me, {"player_id": _STEAM32, "player_name": "Meatstorm"})
        if state is None:
            return
        assert state == "linked"
        assert _identity_state("both", me, {"player_id": _STEAM32, "player_name": None}) == "linked_no_match"

    def test_profile_returns_player_team_name(self, db):
        """GET /profile/{id} carries the matched player's latest team for the panel."""
        from models import Match, PlayerMatchStats, Team
        from routers.profile import get_profile
        user = _linked_user(db)
        _player(db)
        db.add(Team(id=7, name="Kana Flames"))
        db.add(Team(id=9, name="Old Team"))
        # The newer match by start time has the lower match id: start time decides.
        db.add(Match(match_id=1, radiant_team_id=7, dire_team_id=8, start_time=2000))
        db.add(Match(match_id=2, radiant_team_id=9, dire_team_id=8, start_time=1000))
        db.flush()
        db.add(PlayerMatchStats(player_id=_STEAM32, match_id=1, team_id=7, fantasy_points=0))
        db.add(PlayerMatchStats(player_id=_STEAM32, match_id=2, team_id=9, fantasy_points=0))
        db.commit()
        result = get_profile(user.id, db=db, current_user=_acting(user))
        assert result["player_name"] == "Meatstorm"
        assert result["player_team_name"] == "Kana Flames"

    def test_unlink_steam_shown_only_for_accounts_with_password(self):
        """Unlink Steam is offered only to Steam-linked accounts that have a password, as today."""
        tab = self._profile_tab()
        assert 'id="btnUnlinkSteam" onclick="unlinkSteam()"' in tab
        assert 'show("btnUnlinkSteam", ui.unlinkSteam);' in _read("app-profile.js")
        with_pw = _steam_ui("both", {"steam_linked": True, "has_password": True, "is_demo": False})
        if with_pw is None:
            return
        assert with_pw["unlinkSteam"] is True
        assert _steam_ui("both", {"steam_linked": True, "has_password": False,
                                  "is_demo": False})["unlinkSteam"] is False

    # Issue #209 removed PUT /profile/player-id and the typed-in id: the route test
    # below replaces the old 410 / password-mode tests, and the two frontend tests pin
    # the panel without the id field or the "self-reported" state.
    @pytest.mark.parametrize("mode_value", ["password", "both", "steam_signup"])
    def test_update_player_id_route_removed(self, web, mode, mode_value):
        """PUT /profile/player-id no longer exists (issue #209): 404 in every mode, nothing changes."""
        from models import User
        mode(mode_value)
        uid = web.add_user("alice", player_id=777)
        client = web.login("alice")
        assert client.put("/profile/player-id", json={"player_id": 4242}).status_code == 404
        assert web.get(User, uid).player_id == 777

    def test_frontend_no_opendota_field_in_any_mode(self):
        """The Player identity panel has no OpenDota id field in any login mode (issue #209); password mode shows the Steam note."""
        tab = self._profile_tab()
        assert 'id="playerIdForm"' not in tab and 'id="profilePlayerId"' not in tab
        assert "Player linking needs Steam sign-in" in tab
        assert "playerIdField" not in _read("app-auth.js")
        me = {"steam_linked": False, "has_password": True, "is_demo": False}
        state = _identity_state("password", me, {"player_id": 4242})
        if state is None:
            return
        assert state == "steam_required"

    def test_frontend_stale_typed_in_id_shows_not_linked(self):
        """A leftover typed-in id (no Steam) shows the not-linked state with Link Steam (issue #209); tags still show."""
        tab = self._profile_tab()
        assert 'id="identityLegacyHint"' not in tab
        assert "Self-reported" not in tab
        js = _read("app-profile.js")
        assert "self_reported" not in js
        # Tags render whatever the state.
        assert js.index("_renderPlayerIdentity(data);") < js.index("profileTagsContainer")
        me = {"steam_linked": False, "has_password": True, "is_demo": False}
        state = _identity_state("both", me, {"player_id": 4242, "player_name": "Legacy"})
        if state is None:
            return
        assert state == "not_linked"
        assert _steam_ui("both", me)["linkSteam"] is True

    def test_me_and_profile_never_expose_steam_id(self, db):
        """GET /me and GET /profile/{id} never return the Steam id, and the panel never renders it."""
        from routers.profile import get_profile
        user = _linked_user(db)
        _player(db)
        db.commit()
        me = _me(db, user)
        profile = get_profile(user.id, db=db, current_user=_acting(user))
        for body in (me, profile):
            assert "steam_id" not in body
            assert _STEAM64 not in json.dumps(body, default=str)
        assert "steam_id" not in _read("app-profile.js")


# ---------------------------------------------------------------------------
# Story 2 — Own Player Card When Steam Matches a League Player
# ---------------------------------------------------------------------------

class TestOwnPlayerCardWhenSteamMatches:
    """
    Acceptance criteria:
    - "When an account's verified player id (from Steam) is an active player in the
      pool (Player.is_active), the account gets one common card of that player with
      the usual modifiers. It goes to the roster if there is room and no active card
      of that player, otherwise to the bench"
    - "The grant runs after Link Steam, after Steam sign-up, and on GET /me for
      accounts that qualify but have no grant yet"
    - "A new table own_player_card_grants holds user_id (unique), player_id (unique),
      card_id (nullable), outcome (granted or already_owned) and granted_at. It is
      written with INSERT … ON CONFLICT DO NOTHING, and a card is created only when
      the insert added the row. Unlinking and relinking, or linking the same Steam
      account to another account, grants nothing more"
    - "If the account already owns any card of that player, no card is created and
      the grant is recorded as already_owned"
    - "An audit entry own_player_card_granted names the user, the player and the card id"
    - "Self-reported ids never qualify; neither do demo accounts or soft (Twitch-only) accounts"
    """

    def test_grant_own_player_card_creates_common_card_with_modifiers_for_pool_player(self, db):
        """A Steam-verified account whose player is active in the pool gets one common card of that player with modifiers and points."""
        from models import CardModifier
        user = _linked_user(db)
        _player(db)
        grant = _grant(db, user)
        assert grant is not None
        cards = _cards(db, user.id)
        assert len(cards) == 1
        card = cards[0]
        assert card.player_id == _STEAM32 and card.card_type == "common"
        mods = db.query(CardModifier).filter(CardModifier.card_id == card.id).all()
        assert len(mods) == 1 and mods[0].bonus_pct == 10.0

    def test_grant_own_player_card_records_granted_row(self, db):
        """The grant writes an own_player_card_grants row with user_id, player_id, card_id, outcome='granted' and granted_at."""
        user = _linked_user(db)
        _player(db)
        before = int(time.time())
        _grant(db, user)
        rows = _grants(db)
        assert len(rows) == 1
        row = rows[0]
        assert row.user_id == user.id and row.player_id == _STEAM32
        assert row.card_id == _cards(db, user.id)[0].id
        assert row.outcome == "granted"
        assert before <= row.granted_at <= int(time.time())
        assert row.seen_at is None

    def test_grant_own_player_card_writes_audit_entry(self, db):
        """An own_player_card_granted audit entry names the user, the player and the card id."""
        from models import AuditLog
        user = _linked_user(db)
        _player(db)
        _grant(db, user)
        card_id = _cards(db, user.id)[0].id
        audits = db.query(AuditLog).filter(AuditLog.action == "own_player_card_granted").all()
        assert len(audits) == 1
        assert audits[0].actor_id == user.id
        detail = audits[0].detail
        assert f"user_id={user.id}" in detail and f"player_id={_STEAM32}" in detail
        assert f"card_id={card_id}" in detail
        assert _STEAM64 not in detail

    def test_grant_own_player_card_skips_self_reported_id(self, db):
        """A player_id without a steam_id (self-reported) never qualifies: no row, no card."""
        user = _user(db, player_id=_STEAM32)
        _player(db)
        assert _grant(db, user) is None
        assert _grants(db) == [] and _cards(db, user.id) == []

    def test_grant_own_player_card_skips_inactive_player(self, db):
        """A verified id for a player with is_active False grants nothing."""
        user = _linked_user(db)
        _player(db, is_active=False)
        assert _grant(db, user) is None
        assert _grants(db) == [] and _cards(db, user.id) == []

    def test_grant_own_player_card_skips_unknown_player(self, db):
        """A verified id with no matching Player row grants nothing."""
        user = _linked_user(db)
        assert _grant(db, user) is None
        assert _grants(db) == [] and _cards(db, user.id) == []

    def test_grant_own_player_card_skips_demo_account(self, db):
        """Demo accounts never get the grant."""
        user = _linked_user(db, is_demo=True)
        _player(db)
        assert _grant(db, user) is None
        assert _grants(db) == [] and _cards(db, user.id) == []

    def test_grant_own_player_card_skips_soft_account(self, db):
        """Soft (Twitch-only) accounts never get the grant."""
        user = _linked_user(db, account_type="twitch")
        _player(db)
        assert _grant(db, user) is None
        assert _grants(db) == [] and _cards(db, user.id) == []

    def test_grant_own_player_card_already_owned_records_without_card(self, db):
        """When the account already owns any card of that player, no card is created and the row has outcome='already_owned', card_id null."""
        user = _linked_user(db)
        _player(db)
        _card(db, user.id, _STEAM32, card_type="epic")
        _grant(db, user)
        rows = _grants(db)
        assert len(rows) == 1
        assert rows[0].outcome == "already_owned" and rows[0].card_id is None
        assert len(_cards(db, user.id)) == 1

    def test_grant_own_player_card_places_on_roster_when_room(self, db):
        """With roster room and no active card of that player, the granted card is active (via _activate_new_card)."""
        user = _linked_user(db)
        _player(db)
        _player(db, pid=9001, name="Other")
        _card(db, user.id, 9001, is_active=True)
        _grant(db, user)
        card = _cards(db, user.id, _STEAM32)[0]
        assert card.is_active is True

    def test_grant_own_player_card_goes_to_bench_when_roster_full(self, db):
        """With a full roster, the granted card goes to the bench."""
        from routers.cards import ROSTER_LIMIT
        user = _linked_user(db)
        _player(db)
        for i in range(ROSTER_LIMIT):
            _player(db, pid=9100 + i, name=f"Filler{i}")
            _card(db, user.id, 9100 + i, is_active=True)
        _grant(db, user)
        card = _cards(db, user.id, _STEAM32)[0]
        assert card.is_active is False

    def test_steam_link_triggers_grant(self, web, mode, monkeypatch):
        """Link Steam (steam_openid link path) for a pool player creates the card in the same request."""
        from models import Card, OwnPlayerCardGrant
        mode("both")
        uid = web.add_user("alice")
        _web_seed(web, lambda db: (_seed_weights(db), _player(db)))
        resp, _ = _round_trip(web.login("alice"), monkeypatch, purpose="link")
        assert _key(resp, "profile") == "linked"
        cards = web.rows(Card, owner_id=uid)
        assert len(cards) == 1 and cards[0].player_id == _STEAM32
        grants = web.rows(OwnPlayerCardGrant)
        assert len(grants) == 1 and grants[0].card_id == cards[0].id

    def test_steam_signup_triggers_grant(self, web, mode, monkeypatch):
        """Steam sign-up (POST /auth/steam/signup) for a pool player creates the card."""
        from models import Card, OwnPlayerCardGrant, User
        mode("both")
        _web_seed(web, lambda db: (_seed_weights(db), _player(db)))
        client = web.client()
        _signup(web, client, monkeypatch, username="newbie")
        uid = web.rows(User, username="newbie")[0].id
        cards = web.rows(Card, owner_id=uid)
        assert len(cards) == 1 and cards[0].player_id == _STEAM32
        grants = web.rows(OwnPlayerCardGrant)
        assert len(grants) == 1 and grants[0].user_id == uid and grants[0].outcome == "granted"
        me = client.get("/me").json()
        assert me["own_card_grant"] == {"player_name": "Meatstorm", "card_id": cards[0].id,
                                        "outcome": "granted"}

    def test_unlink_and_relink_grants_nothing_more(self, web, mode, monkeypatch):
        """Unlinking and relinking Steam leaves exactly one grant row and one card."""
        from models import Card, OwnPlayerCardGrant
        mode("both")
        uid = web.add_user("alice")
        _web_seed(web, lambda db: (_seed_weights(db), _player(db)))
        client = web.login("alice")
        resp, _ = _round_trip(client, monkeypatch, purpose="link")
        assert _key(resp, "profile") == "linked"
        assert client.post("/profile/steam/unlink").status_code == 200
        resp, _ = _round_trip(client, monkeypatch, purpose="link")
        assert _key(resp, "profile") == "linked"
        assert client.get("/me").status_code == 200
        assert len(web.rows(Card, owner_id=uid)) == 1
        assert len(web.rows(OwnPlayerCardGrant)) == 1

    def test_same_steam_account_on_second_account_grants_nothing(self, web, mode, monkeypatch):
        """Linking the same Steam account to another account later grants nothing (player_id unique)."""
        from models import Card, OwnPlayerCardGrant
        mode("both")
        first = web.add_user("alice")
        second = web.add_user("bob")
        _web_seed(web, lambda db: (_seed_weights(db), _player(db)))
        alice = web.login("alice")
        _round_trip(alice, monkeypatch, purpose="link")
        assert alice.post("/profile/steam/unlink").status_code == 200
        bob = web.login("bob")
        resp, _ = _round_trip(bob, monkeypatch, purpose="link")
        assert _key(resp, "profile") == "linked"
        assert bob.get("/me").json()["own_card_grant"] is None
        assert len(web.rows(Card, owner_id=first)) == 1
        assert len(web.rows(Card, owner_id=second)) == 0
        grants = web.rows(OwnPlayerCardGrant)
        assert len(grants) == 1 and grants[0].user_id == first

    def test_card_creation_failure_keeps_link_and_me_retries(self, web, mode, monkeypatch):
        """A failure while creating the card rolls back only the grant (savepoint): the Steam link succeeds with no grant row, and a later GET /me grants the card."""
        import card_points
        from models import Card, OwnPlayerCardGrant, User
        mode("both")
        uid = web.add_user("alice")
        _web_seed(web, lambda db: (_seed_weights(db), _player(db)))
        real_refresh = card_points.refresh_card_points

        def boom(*args, **kwargs):
            raise RuntimeError("card points down")

        monkeypatch.setattr(card_points, "refresh_card_points", boom)
        client = web.login("alice")
        resp, _ = _round_trip(client, monkeypatch, purpose="link")
        assert _key(resp, "profile") == "linked"
        user = web.get(User, uid)
        assert user.steam_id == _STEAM64 and user.player_id == _STEAM32
        assert web.rows(OwnPlayerCardGrant) == []
        assert web.rows(Card, owner_id=uid) == []
        monkeypatch.setattr(card_points, "refresh_card_points", real_refresh)
        me = client.get("/me")
        assert me.status_code == 200
        cards = web.rows(Card, owner_id=uid)
        assert len(cards) == 1 and cards[0].player_id == _STEAM32
        assert me.json()["own_card_grant"] == {"player_name": "Meatstorm", "card_id": cards[0].id,
                                               "outcome": "granted"}

    def test_steam_signup_survives_card_creation_failure(self, web, mode, monkeypatch):
        """Steam sign-up still creates the account and session when the card creation fails; no grant row is left behind."""
        import card_points
        from models import Card, OwnPlayerCardGrant, User
        mode("both")
        _web_seed(web, lambda db: (_seed_weights(db), _player(db)))
        monkeypatch.setattr(card_points, "refresh_card_points",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
        client = web.client()
        _signup(web, client, monkeypatch, username="newbie")
        uid = web.rows(User, username="newbie")[0].id
        assert web.rows(OwnPlayerCardGrant) == [] and web.rows(Card, owner_id=uid) == []

    def test_grant_concurrent_calls_create_one_card(self, tmp_path):
        """Two concurrent grants for the same user and player insert one row and create one card (ON CONFLICT DO NOTHING, rowcount == 1)."""
        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker
        from database import Base
        from models import Card, OwnPlayerCardGrant, User
        from own_card import grant_own_player_card

        engine = create_engine(f"sqlite:///{tmp_path / 'race.db'}",
                               connect_args={"check_same_thread": False, "timeout": 30})

        @event.listens_for(engine, "connect")
        def _wal(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        try:
            with Session() as db:
                _seed_weights(db)
                user = _linked_user(db)
                _player(db)
                db.commit()
                uid = user.id

            barrier = threading.Barrier(2)
            results = [None, None]

            def worker(i):
                with Session() as db:
                    u = db.get(User, uid)
                    barrier.wait()
                    try:
                        grant = grant_own_player_card(db, u)
                        db.commit()
                        results[i] = (grant is not None, None)
                    except Exception as exc:  # noqa: BLE001 — asserted below
                        db.rollback()
                        results[i] = (None, exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(60)
            assert all(exc is None for _, exc in results), results
            assert sorted(r for r, _ in results) == [False, True]
            with Session() as db:
                assert db.query(OwnPlayerCardGrant).count() == 1
                assert db.query(Card).filter(Card.owner_id == uid).count() == 1
        finally:
            engine.dispose()

    def test_own_player_card_grants_table_unique_constraints(self, db):
        """own_player_card_grants has unique user_id and unique player_id; a second row for either is rejected."""
        from sqlalchemy.exc import IntegrityError
        from models import OwnPlayerCardGrant
        now = int(time.time())
        db.add(OwnPlayerCardGrant(user_id=1, player_id=10, outcome="granted", granted_at=now))
        db.commit()
        for user_id, player_id in ((1, 11), (2, 10)):
            db.add(OwnPlayerCardGrant(user_id=user_id, player_id=player_id, outcome="granted",
                                      granted_at=now))
            with pytest.raises(IntegrityError):
                db.commit()
            db.rollback()
        cols = {c.name: c for c in OwnPlayerCardGrant.__table__.columns}
        assert set(cols) >= {"user_id", "player_id", "card_id", "outcome", "granted_at", "seen_at"}
        assert cols["card_id"].nullable is True

    def test_season_reset_clears_grants(self):
        """A season reset deletes the cards, so it clears the grants too (next season's players get their card again)."""
        import inspect
        from routers import admin_season
        src = inspect.getsource(admin_season.reset_season)
        assert '"own_player_card_grants": db.query(OwnPlayerCardGrant).delete(' in src


# ---------------------------------------------------------------------------
# Story 3 — Popup Explains the Gift
# ---------------------------------------------------------------------------

class TestPopupExplainsTheGift:
    """
    Acceptance criteria:
    - "After a grant, the next page load shows a popup with the card in the existing
      card viewer and the text 'Your own player card. You linked Steam, and you play
      in this season's league, so this card of {player name} is yours.' with Nice"
    - "For already_owned: 'You already have a card of {player name}, so no new card
      was added.' with OK"
    - "The popup shows once: GET /me returns own_card_grant: {player_name,
      card_id | null, outcome} until the player dismisses it
      (POST /profile/own-card-grant/seen), then null"
    - "Text is set with textContent or _escHtml"
    """

    def test_me_lazy_grant_for_existing_linked_player(self, db):
        """GET /me grants once for a qualifying Steam-linked account with no grant row; a second call creates nothing more."""
        _seed_weights(db)
        user = _linked_user(db)
        _player(db)
        db.commit()
        _me(db, user)
        _me(db, user)
        assert len(_grants(db)) == 1
        assert len(_cards(db, user.id)) == 1

    def test_me_returns_own_card_grant_until_seen(self, db):
        """GET /me returns own_card_grant {player_name, card_id, outcome} while seen_at is null."""
        _seed_weights(db)
        user = _linked_user(db)
        _player(db)
        db.commit()
        first = _me(db, user)["own_card_grant"]
        card_id = _cards(db, user.id)[0].id
        assert first == {"player_name": "Meatstorm", "card_id": card_id, "outcome": "granted"}
        assert _me(db, user)["own_card_grant"] == first

    def test_me_returns_already_owned_grant_with_null_card_id(self, db):
        """For already_owned, own_card_grant has card_id null and outcome 'already_owned'."""
        user = _linked_user(db)
        _player(db)
        _card(db, user.id, _STEAM32)
        db.commit()
        assert _me(db, user)["own_card_grant"] == {"player_name": "Meatstorm", "card_id": None,
                                                   "outcome": "already_owned"}

    def test_own_card_grant_seen_clears_popup(self, db):
        """POST /profile/own-card-grant/seen sets seen_at; GET /me then returns own_card_grant null."""
        from routers.profile import own_card_grant_seen
        _seed_weights(db)
        user = _linked_user(db)
        _player(db)
        db.commit()
        assert _me(db, user)["own_card_grant"] is not None
        assert own_card_grant_seen(db=db, current_user=_acting(user)) == {"changed": True}
        assert _grants(db)[0].seen_at is not None
        assert _me(db, user)["own_card_grant"] is None
        assert own_card_grant_seen(db=db, current_user=_acting(user)) == {"changed": False}
        assert len(_cards(db, user.id)) == 1

    def test_own_card_grant_seen_requires_login(self, web, mode):
        """POST /profile/own-card-grant/seen without a session answers 401 and changes nothing."""
        from models import OwnPlayerCardGrant
        mode("both")
        uid = web.add_user("alice")
        _web_seed(web, lambda db: db.add(OwnPlayerCardGrant(
            user_id=uid, player_id=_STEAM32, outcome="already_owned", granted_at=int(time.time()))))
        resp = web.client().post("/profile/own-card-grant/seen")
        assert resp.status_code == 401
        assert web.rows(OwnPlayerCardGrant)[0].seen_at is None

    def test_own_card_grant_seen_is_rate_limited(self):
        """POST /profile/own-card-grant/seen carries the per-user rate limit (#184 route coverage)."""
        from slowapi import Limiter
        import rate_limit
        import routers.profile  # noqa: F401
        module = sys.modules["routers.profile"]
        name = "routers.profile.own_card_grant_seen_route"
        limits = []
        for value in vars(module).values():
            if isinstance(value, Limiter):
                limits.extend(value._route_limits.get(name, []))
        assert limits, "no route-level limit"
        assert any(str(lim.limit) == str(__import__("limits").parse(rate_limit.RATE_LIMIT_USER_ACTION))
                   for lim in limits)
        src = (REPO_ROOT / "backend" / "routers" / "profile.py").read_text(encoding="utf-8")
        assert re.search(r'@router\.post\("/profile/own-card-grant/seen"\)\n'
                         r'@limiter\.limit\(RATE_LIMIT_USER_ACTION, key_func=key_by_user_or_ip\)', src)

    def test_me_returns_null_own_card_grant_for_non_qualifying_account(self, db):
        """An account with no grant (self-reported, unlinked) gets own_card_grant null."""
        _player(db)
        self_reported = _user(db, "legacy", player_id=_STEAM32)
        unlinked = _user(db, "plain")
        db.commit()
        assert _me(db, self_reported)["own_card_grant"] is None
        assert _me(db, unlinked)["own_card_grant"] is None
        assert _grants(db) == []

    def test_frontend_popup_texts_and_buttons(self):
        """app-profile.js holds the 'Your own player card...' text with Nice and the 'You already have a card of...' text with OK, using #revealModal."""
        js = _read("app-profile.js")
        assert ("`Your own player card. You linked Steam, and you play in this season's league, "
                "so this card of ${name} is yours.`") in js
        assert "`You already have a card of ${name}, so no new card was added.`" in js
        assert 'document.getElementById("revealActionBtn").textContent = "Nice";' in js
        assert 'document.getElementById("revealModal")' in js and "showCard(card, ownCardGrantText(grant)" in js
        assert "/profile/own-card-grant/seen" in js
        html = _read("index.html")
        notice = html[html.index('id="ownCardNoticeModal"'):]
        notice = notice[:notice.index("<!-- PLAYER DETAIL MODAL -->")]
        assert 'onclick="dismissOwnCardGrant()">OK</button>' in notice
        # The notice opens after the card viewer in the DOM, so it stacks above it.
        assert html.index('id="revealModal"') < html.index('id="ownCardNoticeModal"')
        # Shown on page load and after Steam sign-up.
        assert "showOwnCardGrant();" in _read("app-init.js")
        assert "showOwnCardGrant();" in _read("app-auth.js")
        texts = _node_eval("app-profile.js", ["ownCardGrantText"],
                           '[ownCardGrantText({player_name: "Meatstorm", outcome: "granted", card_id: 3}),'
                           ' ownCardGrantText({player_name: "Meatstorm", outcome: "already_owned", card_id: null})]')
        if texts is None:
            return
        assert texts == [
            "Your own player card. You linked Steam, and you play in this season's league, "
            "so this card of Meatstorm is yours.",
            "You already have a card of Meatstorm, so no new card was added.",
        ]

    def test_frontend_popup_text_set_with_textcontent_or_eschtml(self):
        """The popup sets the player name via textContent or _escHtml, never raw innerHTML."""
        js = _read("app-profile.js")
        show = _function_source(js, "showOwnCardGrant")
        assert "innerHTML" not in show
        assert 'document.getElementById("ownCardNoticeText").textContent = ownCardGrantText(grant);' in show
        # The card viewer writes its footer (the reason) with textContent.
        cards = _read("app-cards.js")
        cards = cards[cards.index("function showCard("):cards.index("let _revealBoosterTeamId")]
        assert 'document.getElementById("revealDestination").textContent = footer || "";' in cards
        assert "innerHTML" not in cards


# ---------------------------------------------------------------------------
# Story 4 — Draws Stay Duplicate-Free
# ---------------------------------------------------------------------------

class TestDrawsStayDuplicateFree:
    """
    Acceptance criteria:
    - "After a grant, a standard draw and a team draw treat the granted player as
      owned, under the existing _pick_player and _pick_player_from_team rules"
    - "No grant is made when the account already owns that player, so the grant
      itself never creates a second card of a player"
    - "The one-active-card-per-player rule holds: if an active card of that player
      exists, the granted card goes to the bench"
    """

    def test_pick_player_skips_granted_player_while_unowned_remain(self, db):
        """After a grant, _pick_player never returns the granted player while unowned players remain."""
        from card_draw import _pick_player
        user = _linked_user(db)
        _player(db)
        for i in range(3):
            _player(db, pid=9200 + i, name=f"Pool{i}")
        _grant(db, user)
        picks = {_pick_player(db, user.id, "common").id for _ in range(60)}
        assert _STEAM32 not in picks
        assert picks <= {9200, 9201, 9202}

    def test_pick_player_from_team_skips_granted_player_while_unowned_remain(self, db):
        """After a grant, _pick_player_from_team never returns the granted player while unowned teammates remain."""
        from card_draw import _pick_player_from_team
        from models import Match, PlayerMatchStats, Team
        user = _linked_user(db)
        _player(db)
        db.add(Team(id=7, name="Kana Flames"))
        db.add(Match(match_id=1, radiant_team_id=7, dire_team_id=8, start_time=0))
        db.flush()
        mates = [9300, 9301]
        for pid in mates:
            _player(db, pid=pid, name=f"Mate{pid}")
        for pid in [_STEAM32, *mates]:
            db.add(PlayerMatchStats(player_id=pid, match_id=1, team_id=7, fantasy_points=0))
        db.flush()
        _grant(db, user)
        picks = {_pick_player_from_team(db, user.id, "common", 7).id for _ in range(60)}
        assert _STEAM32 not in picks and picks <= set(mates)

    def test_grant_never_creates_second_card_of_owned_player(self, db):
        """An account owning a card of the player (any rarity, active or benched) still has exactly one card of them after the grant."""
        for i, (rarity, active) in enumerate((("legendary", False), ("rare", True))):
            user = _linked_user(db, username=f"owner{i}",
                                steam64=str(76561198000000100 + i))
            _player(db, pid=user.player_id, name=f"Owner{i}")
            _card(db, user.id, user.player_id, is_active=active, card_type=rarity)
            _grant(db, user)
            assert len(_cards(db, user.id, user.player_id)) == 1
        assert {g.outcome for g in _grants(db)} == {"already_owned"}

    def test_grant_respects_one_active_card_per_player(self, db):
        """If an active card of that player exists (ux_cards_owner_player_active), the grant does not add a second active card."""
        from models import Card
        user = _linked_user(db)
        _player(db)
        _card(db, user.id, _STEAM32, is_active=True)
        _grant(db, user)
        active = db.query(Card).filter(Card.owner_id == user.id, Card.player_id == _STEAM32,
                                       Card.is_active.is_(True)).count()
        assert active == 1
        # The placement helper itself benches a new card of a player already active.
        from routers.cards import _activate_new_card
        extra = _card(db, user.id, _STEAM32)
        assert _activate_new_card(db, extra, user.id) is False
        db.refresh(extra)
        assert extra.is_active is False
