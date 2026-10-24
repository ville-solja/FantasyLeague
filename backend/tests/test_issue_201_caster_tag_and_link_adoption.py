"""Tests for issue #201: caster tag for approved streamers, and link adoption in
User Management.

Plan: markdown/plans/plan-issue-201-caster-tag-and-link-adoption.md

A website account (`account_type = "full"`) whose `users.twitch_account_id` equals an
approved channel id (`twitch_channels.approved_channels(db)`: TWITCH_MVP_CHANNEL_IDS
plus portal-approved rows) gets the seeded `caster` tag with `source = "caster_sync"`.
`caster_tags.sync(db, reason=None) -> (granted, revoked)` grants and removes those rows
(never `source = "admin"` rows) and audits each change; the caller commits.
`GET /users` adds `steam_linked` and per-tag `source`; `GET /admin/twitch/channels`
adds `linked_username` per row. One test per acceptance criterion, plus the primary
failure path per story. Frontend behaviour runs app-admin-users.js under Node with a
fake DOM (`_USERS_HARNESS`).

Developer notes
---------------

  Patterns to reuse (import underscore names only, so pytest doesn't collect the
  other module's tests twice)
    - Approved streamers: `env` fixture (copy it; fixtures aren't picked up by
      import), `_add_row`, `_decide` (calls the admin_twitch route functions
      directly with `admin=dict(_ADMIN)`, so no re-auth is involved) and
      `_admin_client(monkeypatch, reauth=True)` in
      tests/test_issue_175_approved_streamers_admin.py.
    - Admin re-auth: approve / reject / remove carry `require_recent_reauth`.
      `_build_app([...], admin_override=True)` (test_issue_135) replaces only
      `require_admin`, so HTTP happy paths must also override
      `require_recent_reauth`. The tag routes in routers/admin_tags.py
      (`grant_tag`, `revoke_tag`) and `GET /users` need only `require_admin`.
    - Twitch connect / disconnect / merge: `_acting`, `_pending_pair`, `_merge`,
      `_disconnect`, `_audits` in tests/test_issue_160_twitch_account_connection_oidc.py
      and `_website_user`, `_join`, `_user_by_opaque` in
      tests/test_issue_157_twitch_extension_policy_compliance.py. Call
      `twitch_oauth.connect_account(db, user, sub)` and `twitch_oauth.disconnect(db,
      _acting(user))` directly; the HTTP disconnect route needs
      `require_recent_player_reauth`. Set TWITCH_CONNECT_BONUS_TOKENS=0 (see
      `_no_twitch_starter_bonus` in test_issue_160) so #187's bonus stays out.
    - Tags: `_make_tag`, `_grant_tag`, `_fetch_tags_for_users` in
      tests/test_user_tag_system.py. The `caster` tag is not in the `db` fixture;
      create it (key "caster", label "Caster").
    - Audit rows: `deps._audit(db, action, actor_id=None, actor_username="system", ...)`.

  Plan vs code (checked 2026-10-14; follow the code)
    - Frontend: User Management and Approved streamers live in
      frontend/app-admin-users.js, not frontend/app-admin.js (the plan's file table).
    - Soft-account merge: `soft_accounts.merge_soft_into` never sets
      `twitch_account_id` on the website account. `twitch_oauth.connect_account`
      already moved the id to the website account in its "merge_ready" branch
      (the column is unique), and commits there early. So the sync must run in
      both `connect_account` commit paths ("merge_ready" and "connected"); a sync
      in soft_accounts after the merge changes nothing.
    - `soft_accounts.reverse_merge` (admin route POST /admin/twitch/merges/{id}/reverse)
      clears `full.twitch_account_id`; the plan has no sync there, so an auto tag
      would survive until the maintenance loop. reverse_merge syncs with reason
      `merge_reversed`.
    - "Totals exclude demo accounts", but `GET /users` returns no `is_demo`, so the
      frontend can't exclude them. `GET /users` returns `is_demo` (bool).
    - Reject applies only to pending channels (`twitch_channels._ACTIONS`), which
      never had an auto tag; the reject path matters only for a stale
      caster_sync row (e.g. a channel approved earlier then requested again).
    - `linked_username` fits in `twitch_channels.list_channels` / `_row_dict`
      (env rows and DB rows); one query mapping twitch_account_id -> username for
      full accounts.
    - Startup: `main.lifespan` after `seed_tags()` (which re-creates a deleted
      `caster` definition at each restart); wrap like `_ensure_card_points_current`
      (own SessionLocal, try/except + log). Maintenance: inside the `try` of
      `main._week_maintenance_loop`.
    - `revoke_tag` currently audits `tag.key` before deleting; check the
      caster_sync 409 before the audit.
"""
import inspect
import json
import logging
import pathlib
import shutil
import subprocess
import time

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import models  # noqa: F401  (registers every table for the db fixture)
from tests.test_issue_160_twitch_account_connection_oidc import (
    _TWITCH_ID, _acting, _merge, _merged, _pending_pair)
from tests.test_user_tag_system import _grant_tag, _make_tag

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND_DIR = REPO_ROOT / "frontend"
_CH = "4242"      # a channel id is the broadcaster's Twitch user id
_OTHER = "999"    # in TWITCH_MVP_CHANNEL_IDS, so the portal decides for _CH
_ADMIN = {"user_id": 1, "username": "admin"}
_AUTO_DETAIL = ("This tag is given automatically to approved streamers; "
                "remove the channel from Approved streamers instead")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """No real Twitch calls, no production, no #187 starter bonus (copied from #175 / #160)."""
    monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", _OTHER)
    monkeypatch.setenv("TWITCH_CONNECT_BONUS_TOKENS", "0")
    for k in ("TWITCH_OAUTH_CLIENT_ID", "TWITCH_OAUTH_CLIENT_SECRET", "TWITCH_OAUTH_REDIRECT_URI"):
        monkeypatch.delenv(k, raising=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _web(db, username="alice", twitch_id=None, **fields):
    from models import User
    user = User(username=username, email=f"{username}@example.com", password_hash="x", tokens=5,
                created_at=int(time.time()), twitch_account_id=twitch_id, **fields)
    db.add(user)
    db.commit()
    return user


def _soft(db, twitch_id, opaque="Usoft1"):
    from models import User
    user = User(username=None, account_type="twitch", tokens=0, created_at=int(time.time()),
                twitch_user_id=opaque, twitch_account_id=twitch_id)
    db.add(user)
    db.commit()
    return user


def _caster(db):
    tag = _make_tag(db)
    db.commit()
    return tag


def _add_row(db, channel=_CH, status="pending", seen=1000):
    from models import TwitchChannelApproval
    db.add(TwitchChannelApproval(channel_id=channel, status=status, first_seen_at=seen,
                                 last_seen_at=seen))
    db.commit()


def _decide(db, channel, action):
    from routers import admin_twitch
    fn = {"approve": admin_twitch.approve_twitch_channel,
          "reject": admin_twitch.reject_twitch_channel,
          "remove": admin_twitch.remove_twitch_channel}[action]
    return fn(channel, admin=dict(_ADMIN), db=db)


def _tag_rows(db, user_id):
    from models import UserTag
    db.expire_all()
    return db.query(UserTag).filter(UserTag.user_id == user_id).all()


def _audits(db, action):
    from models import AuditLog
    return db.query(AuditLog).filter(AuditLog.action == action).all()


def _sync(db, reason=None):
    import caster_tags
    result = caster_tags.sync(db, reason)
    db.commit()
    return result


def _stale_auto_row(db, user, tag):
    from models import UserTag
    db.add(UserTag(user_id=user.id, tag_id=tag.id, granted_at=1, source="caster_sync"))
    db.commit()


def _list_users(db, account_type="full"):
    from routers import admin_users
    return admin_users.list_users(account_type=account_type, db=db, _=dict(_ADMIN))


def _startup_sync(db, monkeypatch):
    import database
    import main
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=db.get_bind()))
    main._sync_caster_tags_at_startup()


def _read(name):
    return (FRONTEND_DIR / name).read_text(encoding="utf-8")


def _js_function(source, name):
    """Body of `function name(...) { ... }` in a JS source, by brace matching."""
    import re
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\(", source)
    assert m, f"function {name} not found"
    start = source.index("{", m.end())
    depth = 0
    for i in range(start, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
    raise AssertionError(f"unbalanced braces in {name}")


# app-admin-users.js under Node with a fake DOM: loadUsers() fetches ROWS.
_USERS_HARNESS = r"""
var els = {};
function el(id) { return els[id] || (els[id] = { id: id, innerHTML: "", textContent: "", hidden: false, value: "" }); }
var document = { getElementById: el, querySelector: function () { return null; } };
var API = "";
var activeUserId = 1;
function setStatus() {}
var ROWS = %(rows)s;
function fetch() { return Promise.resolve({ ok: true, json: function () { return Promise.resolve(ROWS); } }); }
%(esc)s
%(src)s
loadPlayerIdClaims = function () {};
loadTwitchStatus = function () {};
loadTwitchChannels = function () {};
(async function () { var out = {}; %(steps)s console.log(JSON.stringify(out)); })()
    .catch(function (e) { console.error(e && e.stack || e); process.exit(1); });
"""


def _run_users_harness(tmp_path, rows, steps):
    if shutil.which("node") is None:
        pytest.skip("node not available")
    globals_js = _read("app-globals.js")

    def fn(name):
        return f"function {name}" + globals_js.split(f"function {name}", 1)[1].split("\n}\n", 1)[0] + "\n}\n"

    # Issue #202: the badge helpers (and their tag maps) render the users table's badges.
    maps = globals_js[globals_js.index("const _TAG_BADGE_VARIANTS"):globals_js.index("function _ownValue")]
    esc = maps + "".join(fn(n) for n in ("_escHtml", "_ownValue", "adminBadgeHtml", "tagBadgeHtml", "statusBadgeHtml"))
    script = _USERS_HARNESS % {"rows": json.dumps(rows), "esc": esc,
                               "src": _read("app-admin-users.js"), "steps": steps}
    path = tmp_path / "harness.js"
    path.write_text(script, encoding="utf-8")
    out = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def _user_row(uid, username, steam=False, twitch=False, demo=False, account_type="full", tags=()):
    return {"id": uid, "username": username, "account_type": account_type, "tokens": 5,
            "card_count": 0, "created_at": 0, "last_seen_at": 0, "twitch_linked": False,
            "twitch_identity_shared": twitch, "steam_linked": steam, "is_demo": demo,
            "is_tester": False, "is_admin": False, "tags": list(tags)}


_LOAD_FULL = 'el("userAccountType").value = "full"; await loadUsers(); ' \
             'out.summary = el("userAdoptionSummary").textContent; ' \
             'out.hidden = el("userAdoptionSummary").hidden; out.body = el("usersBody").innerHTML;'


# ---------------------------------------------------------------------------
# Story 1 — Approved Streamers Get the Caster Tag Automatically
# ---------------------------------------------------------------------------

def test_caster_sync_grants_tag_to_full_account_matching_approved_channel(db):
    """A website account whose twitch_account_id equals an approved channel id gets the caster tag with source="caster_sync" and granted_by NULL; sync returns (1, 0)."""
    tag = _caster(db)
    user = _web(db, twitch_id=_CH)
    _add_row(db, status="approved")
    assert _sync(db) == (1, 0)
    rows = _tag_rows(db, user.id)
    assert [(r.tag_id, r.source, r.granted_by) for r in rows] == [(tag.id, "caster_sync", None)]


def test_admin_approve_channel_grants_caster_tag_in_same_request(db):
    """Approving a waiting channel (admin_twitch approve route) gives the linked website account the caster tag before the request returns."""
    _caster(db)
    user = _web(db, twitch_id=_CH)
    _add_row(db, status="pending")
    assert _decide(db, _CH, "approve")["status"] == "approved"
    assert [r.source for r in _tag_rows(db, user.id)] == ["caster_sync"]


def test_twitch_connect_account_grants_caster_tag_for_approved_channel(db):
    """connect_account on a website account whose Twitch id is an approved channel ("connected") grants the caster tag in the same commit."""
    import twitch_oauth
    _caster(db)
    _add_row(db, status="approved")
    user = _web(db)
    assert twitch_oauth.connect_account(db, user, _CH) == "connected"
    db.rollback()  # nothing left uncommitted: the tag came with the connect commit
    assert [r.source for r in _tag_rows(db, user.id)] == ["caster_sync"]


def test_twitch_connect_account_merge_ready_grants_caster_tag(db):
    """When connect_account moves the Twitch id from a soft account ("merge_ready"), the website account gets the caster tag; the merge itself keeps it."""
    _caster(db)
    _add_row(db, channel=_TWITCH_ID, status="approved")
    web_user, soft, _cards = _pending_pair(db)
    db.rollback()
    assert [r.source for r in _tag_rows(db, web_user.id)] == ["caster_sync"]
    assert _tag_rows(db, soft.id) == []
    _merge(db, web_user)
    assert [r.source for r in _tag_rows(db, web_user.id)] == ["caster_sync"]


def test_caster_auto_tag_shows_on_leaderboard_card_sticker_and_profile(db, monkeypatch):
    """A caster_sync tag appears wherever tags already show: leaderboard tag chips, card stickers and the Profile identity panel (#188)."""
    import image
    from models import Card, Player
    from routers import cards as cards_router
    from routers.leaderboard import _fetch_tags_for_users
    from routers.profile import get_profile
    _caster(db)
    db.add(Player(id=77, name="Caster Player"))
    db.commit()
    user = _web(db, twitch_id=_CH, player_id=77)
    _add_row(db, status="approved")
    _sync(db)

    assert {"key": "caster", "label": "Caster"} in _fetch_tags_for_users(db, [user.id])[user.id]
    profile = get_profile(user.id, db=db, current_user=_acting(user))
    assert {"key": "caster", "label": "Caster"} in profile["tags"]

    card = Card(owner_id=user.id, player_id=77, card_type="common", is_active=False, generation=1)
    db.add(card)
    db.commit()
    seen = {}

    def fake_generate(**kwargs):
        seen["tag_keys"] = kwargs["tag_keys"]
        from PIL import Image
        return Image.new("RGB", (2, 2))

    if not image.PIL_AVAILABLE:
        pytest.skip("Pillow not installed")
    monkeypatch.setattr(image, "generate_card_image", fake_generate)
    cards_router.get_card_image(card.id, db=db)
    assert seen["tag_keys"] == ["caster"]


def test_caster_sync_existing_admin_grant_no_duplicate_row_no_audit(db):
    """A user already holding the caster tag from an admin gets no second row, keeps source="admin", and no caster_tag_auto_grant entry is written."""
    tag = _caster(db)
    user = _web(db, twitch_id=_CH)
    _grant_tag(db, user, tag, granted_by_id=None)
    db.commit()
    _add_row(db, status="approved")
    assert _sync(db) == (0, 0)
    assert [r.source for r in _tag_rows(db, user.id)] == ["admin"]
    assert _audits(db, "caster_tag_auto_grant") == []


def test_caster_sync_repeat_run_is_idempotent(db):
    """Running sync twice grants once: the second run returns (0, 0) and writes no audit entry."""
    _caster(db)
    user = _web(db, twitch_id=_CH)
    _add_row(db, status="approved")
    assert _sync(db) == (1, 0)
    assert _sync(db) == (0, 0)
    assert len(_tag_rows(db, user.id)) == 1
    assert len(_audits(db, "caster_tag_auto_grant")) == 1
    assert _audits(db, "caster_tag_auto_revoke") == []


def test_caster_sync_writes_auto_grant_audit_with_user_and_channel(db):
    """Each new automatic grant writes caster_tag_auto_grant with actor "system" and detail "user_id=<id> channel=<channel_id>"."""
    _caster(db)
    user = _web(db, twitch_id=_CH)
    _add_row(db, status="approved")
    _sync(db)
    [entry] = _audits(db, "caster_tag_auto_grant")
    assert (entry.actor_id, entry.actor_username) == (None, "system")
    assert entry.detail == f"user_id={user.id} channel={_CH}"


def test_caster_sync_never_tags_soft_account(db):
    """A soft account (account_type="twitch") whose twitch_account_id matches an approved channel is never tagged."""
    _caster(db)
    soft = _soft(db, _CH)
    _add_row(db, status="approved")
    assert _sync(db) == (0, 0)
    assert _tag_rows(db, soft.id) == []


def test_caster_sync_missing_caster_definition_is_noop_with_one_warning(db, caplog):
    """With no `caster` tag definition, sync changes nothing, returns (0, 0) and logs exactly one warning."""
    from models import UserTag
    user = _web(db, twitch_id=_CH)
    _add_row(db, status="approved")
    with caplog.at_level(logging.WARNING, logger="caster_tags"):
        assert _sync(db) == (0, 0)
    warnings = [r for r in caplog.records if r.name == "caster_tags" and r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert db.query(UserTag).count() == 0
    assert _audits(db, "caster_tag_auto_grant") == []
    assert user.id


def test_twitch_connect_account_sync_failure_still_connects(db, monkeypatch, caplog):
    """If caster_tags.sync raises during connect_account, the Twitch connection is still stored and the error is logged (a sync failure never blocks a login)."""
    import caster_tags
    import twitch_oauth
    from models import User

    def boom(*args, **kwargs):
        raise RuntimeError("sync broke")

    _caster(db)
    _add_row(db, status="approved")
    monkeypatch.setattr(caster_tags, "sync", boom)
    user = _web(db)
    with caplog.at_level(logging.WARNING, logger="caster_tags"):
        assert twitch_oauth.connect_account(db, user, _CH) == "connected"
    db.expire_all()
    assert db.get(User, user.id).twitch_account_id == _CH
    assert _audits(db, "twitch_connected")
    assert any("Caster tag sync failed" in r.getMessage() for r in caplog.records)
    assert all(_CH not in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------
# Story 2 — The Automatic Tag Follows the Approval
# ---------------------------------------------------------------------------

def test_admin_remove_channel_revokes_auto_caster_tag(db):
    """Removing an approved channel deletes the linked account's caster_sync row in the same request."""
    _caster(db)
    user = _web(db, twitch_id=_CH)
    _add_row(db, status="approved")
    _sync(db)
    _decide(db, _CH, "remove")
    assert _tag_rows(db, user.id) == []
    [entry] = _audits(db, "caster_tag_auto_revoke")
    assert entry.detail == f"user_id={user.id} reason=channel_not_approved"


def test_admin_reject_channel_revokes_stale_auto_caster_tag(db):
    """Rejecting a pending channel removes any caster_sync row whose Twitch id matches that channel."""
    tag = _caster(db)
    user = _web(db, twitch_id=_CH)
    _add_row(db, status="pending")
    _stale_auto_row(db, user, tag)
    _decide(db, _CH, "reject")
    assert _tag_rows(db, user.id) == []


def test_twitch_disconnect_revokes_auto_caster_tag_with_reason(db):
    """twitch_oauth.disconnect removes the caster_sync row and writes caster_tag_auto_revoke with detail "user_id=<id> reason=twitch_disconnected"."""
    import twitch_oauth
    _caster(db)
    _add_row(db, status="approved")
    user = _web(db)
    assert twitch_oauth.connect_account(db, user, _CH) == "connected"
    assert len(_tag_rows(db, user.id)) == 1
    assert twitch_oauth.disconnect(db, _acting(user))["changed"] is True
    assert _tag_rows(db, user.id) == []
    [entry] = _audits(db, "caster_tag_auto_revoke")
    assert (entry.actor_id, entry.actor_username) == (None, "system")
    assert entry.detail == f"user_id={user.id} reason=twitch_disconnected"


def test_caster_sync_revoke_audit_defaults_to_channel_not_approved(db):
    """A revoke with no reason given writes caster_tag_auto_revoke (actor "system") with detail "user_id=<id> reason=channel_not_approved"."""
    tag = _caster(db)
    user = _web(db, twitch_id=_CH)
    _stale_auto_row(db, user, tag)
    assert _sync(db) == (0, 1)
    [entry] = _audits(db, "caster_tag_auto_revoke")
    assert (entry.actor_id, entry.actor_username) == (None, "system")
    assert entry.detail == f"user_id={user.id} reason=channel_not_approved"


@pytest.mark.parametrize("path", ["remove", "reject", "disconnect", "startup"])
def test_caster_sync_never_removes_admin_granted_caster_tag(db, path, monkeypatch):
    """A caster tag with source="admin" survives every revoke path (remove, reject, disconnect, startup sync)."""
    import twitch_oauth
    tag = _caster(db)
    user = _web(db, twitch_id=_CH)
    _grant_tag(db, user, tag, granted_by_id=None)
    db.commit()
    if path == "remove":
        _add_row(db, status="approved")
        _decide(db, _CH, "remove")
    elif path == "reject":
        _add_row(db, status="pending")
        _decide(db, _CH, "reject")
    elif path == "disconnect":
        _add_row(db, status="approved")
        twitch_oauth.disconnect(db, _acting(user))
    else:
        _startup_sync(db, monkeypatch)
    assert [r.source for r in _tag_rows(db, user.id)] == ["admin"]
    assert _audits(db, "caster_tag_auto_revoke") == []


def test_caster_sync_env_channel_counts_as_approved(db, monkeypatch):
    """A channel listed in TWITCH_MVP_CHANNEL_IDS (no portal row) counts as approved and its linked account gets the caster tag."""
    _caster(db)
    user = _web(db, twitch_id=_CH)
    monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", f"{_OTHER},{_CH}")
    assert _sync(db) == (1, 0)
    assert [r.source for r in _tag_rows(db, user.id)] == ["caster_sync"]


def test_caster_sync_startup_without_env_channel_revokes_its_auto_tag(db, monkeypatch):
    """After a restart without a channel in TWITCH_MVP_CHANNEL_IDS, the startup sync removes the caster_sync tag that channel gave."""
    _caster(db)
    user = _web(db, twitch_id=_CH)
    monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", f"{_OTHER},{_CH}")
    _startup_sync(db, monkeypatch)
    assert [r.source for r in _tag_rows(db, user.id)] == ["caster_sync"]
    monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", _OTHER)
    _startup_sync(db, monkeypatch)
    assert _tag_rows(db, user.id) == []
    [entry] = _audits(db, "caster_tag_auto_revoke")
    assert entry.detail == f"user_id={user.id} reason=channel_not_approved"


def test_main_lifespan_and_maintenance_loop_call_caster_sync():
    """Static check: main.lifespan calls the caster sync after seed_tags(), and _week_maintenance_loop calls it inside its try block, each wrapped so a failure is logged."""
    import main
    lifespan = inspect.getsource(main.lifespan)
    assert lifespan.index("seed_tags()") < lifespan.index("_sync_caster_tags_at_startup()")
    assert "_run_caster_tag_sync(db, " in inspect.getsource(main._sync_caster_tags_at_startup)
    runner = inspect.getsource(main._run_caster_tag_sync)
    assert runner.index("try:") < runner.index("caster_tags.sync(db)") < runner.index("except Exception")
    assert "logger.exception" in runner.split("except Exception", 1)[1]
    loop = inspect.getsource(main._week_maintenance_loop)
    call = loop.index("_run_caster_tag_sync(db, ")
    assert loop.index("try:") < call < loop.rindex("except Exception")


def test_reverse_merge_revokes_auto_caster_tag(db):
    """Reversing a Twitch merge (which clears the website account's twitch_account_id) removes its caster_sync tag in the same request."""
    from routers import admin_twitch
    _caster(db)
    _add_row(db, channel=_TWITCH_ID, status="approved")
    web_user, log, _card_ids, _week = _merged(db, with_week=False)
    assert [r.source for r in _tag_rows(db, web_user.id)] == ["caster_sync"]
    admin_twitch.reverse_twitch_merge(log.id, admin=dict(_ADMIN), db=db)
    assert _tag_rows(db, web_user.id) == []
    [entry] = _audits(db, "caster_tag_auto_revoke")
    assert entry.detail == f"user_id={web_user.id} reason=merge_reversed"


def test_revoke_tag_caster_sync_row_returns_409(db):
    """DELETE /admin/users/{user_id}/tags/{tag_id} on a caster_sync row returns 409 "This tag is given automatically to approved streamers; remove the channel from Approved streamers instead", keeps the row and writes no admin_tag_revoke."""
    from routers import admin_tags
    tag = _caster(db)
    user = _web(db, twitch_id=_CH)
    _add_row(db, status="approved")
    _sync(db)
    with pytest.raises(HTTPException) as exc:
        admin_tags.revoke_tag(user.id, tag.id, db=db, admin=dict(_ADMIN))
    assert exc.value.status_code == 409
    assert exc.value.detail == _AUTO_DETAIL
    db.rollback()
    assert [r.source for r in _tag_rows(db, user.id)] == ["caster_sync"]
    assert _audits(db, "admin_tag_revoke") == []


def test_revoke_tag_admin_row_still_works(db):
    """DELETE /admin/users/{user_id}/tags/{tag_id} on a source="admin" row still deletes it and writes admin_tag_revoke."""
    from routers import admin_tags
    tag = _caster(db)
    user = _web(db)
    _grant_tag(db, user, tag)
    db.commit()
    assert admin_tags.revoke_tag(user.id, tag.id, db=db, admin=dict(_ADMIN)) == {"ok": True}
    assert _tag_rows(db, user.id) == []
    [entry] = _audits(db, "admin_tag_revoke")
    assert entry.detail == f"user_id={user.id} tag=caster"


def test_grant_tag_sets_source_admin(db):
    """POST /admin/users/{user_id}/tags/{tag_id} stores the new row with source="admin"."""
    from routers import admin_tags
    tag = _caster(db)
    user = _web(db)
    admin_tags.grant_tag(user.id, tag.id, db=db, admin=dict(_ADMIN))
    [row] = _tag_rows(db, user.id)
    assert (row.source, row.granted_by) == ("admin", _ADMIN["user_id"])


def test_migration_adds_user_tags_source_defaulting_admin_for_existing_rows():
    """The new migration adds user_tags.source (NOT NULL DEFAULT 'admin'); rows that existed before read source="admin"; running migrations twice is a no-op."""
    import migrate
    from database import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE user_tags"))
        conn.execute(text("""CREATE TABLE user_tags (id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL, tag_id INTEGER NOT NULL, granted_by INTEGER,
            granted_at INTEGER, CONSTRAINT uq_user_tag UNIQUE (user_id, tag_id))"""))
        conn.execute(text("INSERT INTO user_tags (user_id, tag_id, granted_by, granted_at) "
                          "VALUES (1, 1, 1, 100)"))
        conn.commit()
        migrate._ensure_migrations_table(conn)
        for migration_id, _ in migrate.MIGRATIONS:
            if migration_id < "039":
                migrate._record(conn, migration_id)
    assert "039_user_tags_source" in [m for m, _ in migrate.MIGRATIONS]
    migrate.run_migrations(engine)
    with engine.connect() as conn:
        cols = {r[1]: r for r in conn.execute(text("PRAGMA table_info(user_tags)")).fetchall()}
        assert "source" in cols
        assert cols["source"][3] == 1  # notnull
        assert cols["source"][4] == "'admin'"
        assert conn.execute(text("SELECT source FROM user_tags")).scalar() == "admin"
    migrate._m039_user_tags_source(engine.connect())  # already there: no-op
    migrate.run_migrations(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM user_tags")).scalar() == 1


# ---------------------------------------------------------------------------
# Story 3 — Admins See Which Channel Belongs to Which Account
# ---------------------------------------------------------------------------

def test_admin_list_channels_rows_carry_linked_username(db, monkeypatch):
    """Each row in GET /admin/twitch/channels (env, approved, pending, rejected) has linked_username = the website account whose twitch_account_id is that channel id."""
    import twitch_channels
    from routers import admin_twitch
    monkeypatch.setattr(twitch_channels, "_lookup_names", lambda ids: {})
    _add_row(db, _CH, "approved")
    _add_row(db, "555", "pending")
    _add_row(db, "556", "rejected")
    for name, cid in (("envuser", _OTHER), ("alice", _CH), ("bob", "555"), ("carol", "556")):
        _web(db, name, twitch_id=cid)
    data = admin_twitch.list_twitch_channels(admin=dict(_ADMIN), db=db)
    assert [(r["channel_id"], r["linked_username"]) for r in data["env"]] == [(_OTHER, "envuser")]
    assert [(r["channel_id"], r["linked_username"]) for r in data["approved"]] == [(_CH, "alice")]
    assert [(r["channel_id"], r["linked_username"]) for r in data["pending"]] == [("555", "bob")]
    assert [(r["channel_id"], r["linked_username"]) for r in data["rejected"]] == [("556", "carol")]


def test_admin_list_channels_linked_username_null_without_website_account(db, monkeypatch):
    """linked_username is null when no website account matches, including when only a soft account holds the Twitch id."""
    import twitch_channels
    from routers import admin_twitch
    monkeypatch.setattr(twitch_channels, "_lookup_names", lambda ids: {})
    _add_row(db, _CH, "approved")
    _add_row(db, "555", "pending")
    _soft(db, _CH)
    data = admin_twitch.list_twitch_channels(admin=dict(_ADMIN), db=db)
    rows = data["env"] + data["approved"] + data["pending"]
    assert {r["channel_id"]: r["linked_username"] for r in rows} == {_OTHER: None, _CH: None, "555": None}


def test_admin_frontend_approved_streamers_shows_linked_account_escaped():
    """Static check: the Approved streamers Channel cell renders "Account: {username}" through _escHtml, or "No linked account"."""
    row = _js_function(_read("app-admin-users.js"), "_twitchChannelRow")
    assert "Account: ${_escHtml(c.linked_username)}" in row
    assert "No linked account" in row
    assert "${name}${note}${account}</td>" in row


def test_get_users_tags_carry_source(db):
    """GET /users returns each tag with its source ("admin" or "caster_sync")."""
    tag = _caster(db)
    other = _make_tag(db, "season_winner", "Season Winner")
    db.commit()
    streamer = _web(db, "streamer", twitch_id=_CH)
    alice = _web(db, "alice")
    _grant_tag(db, alice, other)
    db.commit()
    _add_row(db, status="approved")
    _sync(db)
    by_name = {u["username"]: u["tags"] for u in _list_users(db)}
    assert by_name["streamer"] == [{"id": tag.id, "key": "caster", "label": "Caster", "source": "caster_sync"}]
    assert by_name["alice"] == [{"id": other.id, "key": "season_winner", "label": "Season Winner",
                                 "source": "admin"}]
    assert streamer.id


def test_admin_frontend_auto_caster_tag_shows_auto_without_revoke_button(tmp_path):
    """Static check: a caster_sync tag renders as "Caster (auto)" with no revoke button and a title explaining it follows Approved streamers."""
    js = _read("app-admin-users.js")
    manager = _js_function(js, "openTagManager")
    auto_branch = manager[manager.index('held.source === "caster_sync"'):manager.index("const btn")]
    assert "revokeUserTag" not in auto_branch
    assert "_AUTO_TAG_TITLE" in auto_branch and "_tagChipLabel(held)" in auto_branch
    assert "Approved streamers" in js.split("const _AUTO_TAG_TITLE", 1)[1].split("\n", 1)[0]
    rows = [_user_row(2, "streamer", tags=[{"id": 1, "key": "caster", "label": "Caster", "source": "caster_sync"}]),
            _user_row(3, "alice", tags=[{"id": 1, "key": "caster", "label": "Caster", "source": "admin"}])]
    out = _run_users_harness(tmp_path, rows, _LOAD_FULL)
    streamer_row, alice_row = out["body"].split('data-user-id="3"')
    assert "Caster (auto)</span>" in streamer_row and "Approved streamers" in streamer_row
    assert ">Caster</span>" in alice_row and "(auto)" not in alice_row


# ---------------------------------------------------------------------------
# Story 4 — Admins See Steam and Twitch Link Adoption
# ---------------------------------------------------------------------------

def test_get_users_returns_steam_linked_bool(db):
    """GET /users returns steam_linked=True for a user with steam_id set and False otherwise."""
    _web(db, "alice", steam_id="76561197960265729")
    _web(db, "bob")
    by_name = {u["username"]: u["steam_linked"] for u in _list_users(db)}
    assert by_name == {"alice": True, "bob": False}


def test_get_users_never_returns_steam_or_twitch_ids(db):
    """GET /users never includes steam_id, twitch_account_id or twitch_user_id (keys or values) for any account type."""
    _web(db, "alice", twitch_id="88776655", steam_id="76561197960265729", twitch_user_id="Uweb123")
    _soft(db, "11223344", opaque="Usoft987")
    rows = _list_users(db, "all")
    assert len(rows) == 2
    dumped = json.dumps(rows)
    for key in ("steam_id", "twitch_account_id", "twitch_user_id"):
        assert all(key not in r for r in rows)
    for value in ("88776655", "76561197960265729", "Uweb123", "11223344", "Usoft987"):
        assert value not in dumped


def test_get_users_returns_is_demo_for_totals(db):
    """GET /users returns is_demo (bool) so the adoption totals can exclude demo accounts."""
    _web(db, "alice")
    _web(db, "demo1", is_demo=True)
    by_name = {u["username"]: u["is_demo"] for u in _list_users(db)}
    assert by_name == {"alice": False, "demo1": True}


def test_get_users_refuses_non_admin_with_403():
    """GET /users still answers 403 to a logged-in non-admin."""
    from fastapi.testclient import TestClient
    from tests.test_issue_135_security_review_fixes import _add_user, _build_app
    app, Session = _build_app(["routers.admin_users"])
    _add_user(Session, user_id=2, username="bob", email="bob@example.com")
    client = TestClient(app)
    assert client.post("/_test/login/2").status_code == 200
    resp = client.get("/users")
    assert resp.status_code == 403


def test_admin_frontend_users_table_shows_steam_and_twitch_badges(tmp_path):
    """Static check: website-account rows show a Steam badge when steam_linked and a Twitch badge when twitch_identity_shared; no badge otherwise."""
    rows = [_user_row(2, "both", steam=True, twitch=True), _user_row(3, "steamonly", steam=True),
            _user_row(4, "none")]
    out = _run_users_harness(tmp_path, rows, _LOAD_FULL)
    both, rest = out["body"].split('data-user-id="3"')
    steam_only, none = rest.split('data-user-id="4"')
    assert ">Steam</span>" in both and ">Twitch</span>" in both
    assert ">Steam</span>" in steam_only and ">Twitch</span>" not in steam_only
    assert ">Steam</span>" not in none and ">Twitch</span>" not in none


def test_admin_frontend_adoption_summary_counts_full_non_demo_accounts(tmp_path):
    """The summary line reads "{N} website accounts · Steam linked {S} ({S/N}%) · Twitch connected {T} ({T/N}%)", counting website accounts without demo accounts, percentages rounded to whole numbers."""
    rows = [_user_row(2, "a", steam=True, twitch=True), _user_row(3, "b", steam=True),
            _user_row(4, "c"), _user_row(5, "demo1", steam=True, twitch=True, demo=True)]
    out = _run_users_harness(tmp_path, rows, _LOAD_FULL)
    assert out["hidden"] is False
    assert out["summary"] == "3 website accounts · Steam linked 2 (67%) · Twitch connected 1 (33%)"


def test_admin_frontend_adoption_summary_zero_accounts_message(tmp_path):
    """With no website accounts the summary line reads "No website accounts yet"."""
    out = _run_users_harness(tmp_path, [_user_row(5, "demo1", demo=True)], _LOAD_FULL)
    assert out["summary"] == "No website accounts yet"
    out = _run_users_harness(tmp_path, [], _LOAD_FULL)
    assert out["summary"] == "No website accounts yet"


def test_admin_frontend_search_filters_rows_not_totals(tmp_path):
    """Typing in the user search filters the table rows but leaves the summary totals describing all website accounts."""
    rows = [_user_row(2, "alice", steam=True), _user_row(3, "bob")]
    steps = _LOAD_FULL + ' el("userSearch").value = "ali"; filterUsers(); ' \
        'out.summary2 = el("userAdoptionSummary").textContent; out.body2 = el("usersBody").innerHTML;'
    out = _run_users_harness(tmp_path, rows, steps)
    assert out["summary"] == "2 website accounts · Steam linked 1 (50%) · Twitch connected 0 (0%)"
    assert out["summary2"] == out["summary"]
    assert 'data-user-id="2"' in out["body2"] and 'data-user-id="3"' not in out["body2"]


def test_admin_frontend_twitch_viewers_view_keeps_id_shared_badge(tmp_path):
    """The Twitch viewers view is unchanged: it keeps its "ID SHARED" badge and shows no adoption summary."""
    rows = [_user_row(9, "Twitch viewer #9", twitch=True, account_type="twitch")]
    steps = 'el("userAccountType").value = "twitch"; await loadUsers(); ' \
            'out.summary = el("userAdoptionSummary").textContent; ' \
            'out.hidden = el("userAdoptionSummary").hidden; out.body = el("usersBody").innerHTML;'
    out = _run_users_harness(tmp_path, rows, steps)
    assert "ID SHARED</span>" in out["body"]
    assert ">Twitch</span>" not in out["body"]
    assert out["hidden"] is True and out["summary"] == ""
