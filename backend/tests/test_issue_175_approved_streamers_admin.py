"""Tests for issue #175: approved streamers admin.

Plan: markdown/plans/plan-issue-175-approved-streamers-admin.md

Channels that may set match MVPs = TWITCH_MVP_CHANNEL_IDS (env) union the
`twitch_channel_approvals` rows with status "approved". Broadcasters on channels
that aren't approved leave a pending request; admins approve / reject / remove
them under /admin/twitch/channels.

Patterns to reuse (do not reinvent):
- Twitch JWT payloads and env: the `twitch_env` fixture, `_signed`, `_viewer_claims`
  and `_engine` / `_session` in tests/test_issue_163_twitch_steam_account_hardening.py,
  and `twitch_env` / `twitch_prod_env`, `_seed_series_match`, `_set_mvp` in
  tests/test_issue_157_twitch_extension_policy_compliance.py. Both call
  `twitch.set_mvp(twitch.MVPBody(...), payload, db)` and `twitch.current_matches(payload, db)`
  directly with a claims dict, so no TestClient is needed for the Twitch side.
- Admin re-auth on a route: `_route` + `_needs_reauth` in test_issue_163
  (checks `require_recent_reauth` is in `route.dependant.dependencies`).
- Admin endpoints over HTTP: `_build_app(["routers.admin_twitch"], admin_override=True)`
  in tests/test_issue_135_security_review_fixes.py. `admin_override` replaces
  `require_admin` only; `require_recent_reauth` still runs, so happy-path HTTP tests
  must also override it (`app.dependency_overrides[require_recent_reauth] = ...`),
  and the "no recent reauth" test must not.
- Import helpers from other test modules by underscore name only
  (`from tests.test_issue_163_twitch_steam_account_hardening import _needs_reauth, _route`),
  so pytest doesn't collect their tests twice (see markdown/lessons-learned.md).

Notes for the developer:
- The #165 fail-closed rule lives in `twitch.mvp_channel_allowed` and is pinned by
  test_issue_163::TestFailClosedDefaults, which calls `twitch.mvp_channel_allowed("123")`
  with ONE argument. The plan's Step 2 signature is `mvp_channel_allowed(db, channel_id)`.
  Keep the single-argument call working (e.g. `mvp_channel_allowed(channel_id, db=None)`,
  env list only when no db), or update those tests in the same change; either way they
  must keep passing. See test_mvp_channel_allowed_single_argument_call_still_works below.
- `set_mvp` must record the request before its 403 but still write no MVP, bonus or
  drop; commit the request row even though the request ends in an HTTPException.
- Audit entries go through `deps._audit(db, action, actor_id=..., actor_username=..., detail=...)`
  (AuditLog has no channel column; put the channel id in `detail`).
- Helix lookups must be patched in tests (no network): patch the lookup function in
  the new `twitch_channels` module, and clear TWITCH_OAUTH_CLIENT_ID / _SECRET with
  monkeypatch for the "no credentials" case.
"""
import logging
import pathlib
import re
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from tests.test_issue_135_security_review_fixes import _add_user, _build_app
from tests.test_issue_157_twitch_extension_policy_compliance import _seed_series_match
from tests.test_issue_163_twitch_steam_account_hardening import _needs_reauth, _route

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_CH = "4242"
_OTHER = "999"
_ADMIN = {"user_id": 1, "username": "admin"}


def _read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


@pytest.fixture
def env(monkeypatch):
    """No real Twitch calls; no production; env list holds another channel so the
    portal decides for _CH."""
    monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", _OTHER)
    for k in ("TWITCH_OAUTH_CLIENT_ID", "TWITCH_OAUTH_CLIENT_SECRET", "TWITCH_OAUTH_REDIRECT_URI"):
        monkeypatch.delenv(k, raising=False)


def _oauth_env(monkeypatch):
    monkeypatch.setenv("TWITCH_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("TWITCH_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setenv("TWITCH_OAUTH_REDIRECT_URI", "https://example.test/cb")


def _payload(channel=_CH, role="broadcaster"):
    return {"channel_id": channel, "role": role, "opaque_user_id": "Ub"}


def _current(db, channel=_CH, role="broadcaster"):
    import twitch
    return twitch.current_matches(payload=_payload(channel, role), db=db)


def _set_mvp(db, channel=_CH, match_id=1001, player_id=102):
    import twitch
    return twitch.set_mvp(twitch.MVPBody(match_id=match_id, player_id=player_id),
                          payload=_payload(channel), db=db)


def _row(db, channel=_CH):
    from models import TwitchChannelApproval
    db.expire_all()
    return db.get(TwitchChannelApproval, channel)


def _add_row(db, channel=_CH, status="pending", seen=1000, **kw):
    from models import TwitchChannelApproval
    db.add(TwitchChannelApproval(channel_id=channel, status=status, first_seen_at=seen,
                                 last_seen_at=seen, **kw))
    db.commit()


def _nothing_written(db):
    from models import PlayerMatchStats, TwitchMVP, TwitchTokenDrop
    assert db.query(TwitchMVP).count() == 0
    assert db.query(TwitchTokenDrop).count() == 0
    assert all(not s.is_mvp for s in db.query(PlayerMatchStats).all())


def _decide(db, channel, action):
    from routers import admin_twitch
    fn = {"approve": admin_twitch.approve_twitch_channel,
          "reject": admin_twitch.reject_twitch_channel,
          "remove": admin_twitch.remove_twitch_channel}[action]
    return fn(channel, admin=dict(_ADMIN), db=db)


def _admin_client(monkeypatch, reauth=True):
    from deps import require_recent_reauth
    app, Session = _build_app(["routers.admin_twitch"], admin_override=True)
    if reauth:
        app.dependency_overrides[require_recent_reauth] = lambda: dict(_ADMIN)
    return TestClient(app), Session


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def test_twitch_channel_approval_table_created_by_create_all(db):
    """`twitch_channel_approvals` exists via create_all with channel_id PK, status, display_name, login, first/last seen, decided_at/by (new table: no migrate.py entry)."""
    from sqlalchemy import inspect
    insp = inspect(db.get_bind())
    assert "twitch_channel_approvals" in insp.get_table_names()
    cols = {c["name"] for c in insp.get_columns("twitch_channel_approvals")}
    assert cols == {"channel_id", "status", "display_name", "login", "first_seen_at",
                    "last_seen_at", "decided_at", "decided_by"}
    assert insp.get_pk_constraint("twitch_channel_approvals")["constrained_columns"] == ["channel_id"]
    assert "twitch_channel_approvals" not in _read(REPO_ROOT / "backend" / "migrate.py")


# ---------------------------------------------------------------------------
# Story 1 — Broadcaster Asks to Be Approved
# ---------------------------------------------------------------------------

def test_current_matches_broadcaster_on_unapproved_channel_records_pending_request(db, monkeypatch, env):
    """A broadcaster opening the MVP tool on an unapproved channel creates one pending row with first_seen_at and last_seen_at."""
    before = int(time.time())
    _current(db)
    row = _row(db)
    assert row is not None and row.status == "pending"
    assert row.first_seen_at >= before and row.last_seen_at == row.first_seen_at


def test_current_matches_repeat_broadcaster_visit_bumps_last_seen_without_duplicate(db, monkeypatch, env):
    """Repeated visits update last_seen_at only (first_seen_at unchanged) and create no duplicate row."""
    from models import TwitchChannelApproval
    _add_row(db, seen=1000)
    _current(db)
    _current(db)
    row = _row(db)
    assert db.query(TwitchChannelApproval).count() == 1
    assert row.first_seen_at == 1000 and row.last_seen_at > 1000
    assert row.status == "pending"


def test_current_matches_returns_mvp_allowed_and_approval_for_approved_channel(db, monkeypatch, env):
    """An approved channel gets mvp_allowed true, approval "approved" and the normal series list."""
    _seed_series_match(db)
    _add_row(db, status="approved")
    data = _current(db)
    assert data["mvp_allowed"] is True and data["approval"] == "approved"
    assert len(data["series"]) == 1


def test_current_matches_unapproved_channel_returns_pending_and_empty_series(db, monkeypatch, env):
    """An unapproved channel gets mvp_allowed false, approval "pending" and an empty series list."""
    _seed_series_match(db)
    data = _current(db)
    assert data["mvp_allowed"] is False and data["approval"] == "pending"
    assert data["series"] == []


def test_current_matches_rejected_channel_returns_rejected(db, monkeypatch, env):
    """A rejected channel gets mvp_allowed false and approval "rejected"."""
    _add_row(db, status="rejected")
    data = _current(db)
    assert data["mvp_allowed"] is False and data["approval"] == "rejected"
    assert data["series"] == []
    assert _row(db).status == "rejected"


@pytest.mark.parametrize("role", ["viewer", "moderator"])
def test_current_matches_viewer_and_moderator_tokens_create_no_request(db, monkeypatch, env, role):
    """Viewer and moderator tokens never create a twitch_channel_approvals row."""
    from models import TwitchChannelApproval
    data = _current(db, role=role)
    assert data["mvp_allowed"] is False
    assert db.query(TwitchChannelApproval).count() == 0


def test_set_mvp_unapproved_channel_records_request_and_returns_403_before_any_write(db, monkeypatch, env):
    """POST /twitch/mvp from an unapproved channel records/bumps the request and returns 403 with no MVP, bonus or token drop written."""
    _seed_series_match(db)
    with pytest.raises(HTTPException) as exc:
        _set_mvp(db)
    assert exc.value.status_code == 403
    db.rollback()  # the request row was committed before the 403
    assert _row(db).status == "pending"
    _nothing_written(db)


def test_record_request_rejected_channel_stays_rejected_and_bumps_last_seen(db):
    """A rejected channel's later visits update last_seen_at but don't move it back to pending."""
    import twitch_channels
    _add_row(db, status="rejected", seen=1000)
    twitch_channels.record_request(db, _CH, now=2000)
    db.commit()
    row = _row(db)
    assert row.status == "rejected" and row.last_seen_at == 2000 and row.first_seen_at == 1000


@pytest.mark.parametrize("channel_id", ["", "abc", "12a4", "1" * 21, "chan-163"])
def test_record_request_invalid_channel_id_creates_no_row(db, channel_id):
    """record_request only accepts digit-only ids of at most 20 characters."""
    import twitch_channels
    from models import TwitchChannelApproval
    assert twitch_channels.record_request(db, channel_id) is None
    db.commit()
    assert db.query(TwitchChannelApproval).count() == 0
    assert twitch_channels.record_request(db, "1" * 20) is not None


def test_record_request_pending_cap_drops_oldest_by_last_seen(db):
    """With 200 pending rows, a new request drops the oldest pending row by last_seen_at; approved/rejected rows are untouched."""
    import twitch_channels
    from models import TwitchChannelApproval
    for i in range(200):
        db.add(TwitchChannelApproval(channel_id=str(1000 + i), status="pending",
                                     first_seen_at=1, last_seen_at=5000 - i))
    db.add(TwitchChannelApproval(channel_id="1", status="approved", first_seen_at=1, last_seen_at=1))
    db.add(TwitchChannelApproval(channel_id="2", status="rejected", first_seen_at=1, last_seen_at=1))
    db.commit()
    twitch_channels.record_request(db, "77", now=9000)
    db.commit()
    q = db.query(TwitchChannelApproval)
    assert q.filter_by(status="pending").count() == 200
    assert db.get(TwitchChannelApproval, "1199") is None   # oldest pending (last_seen 4801)
    assert db.get(TwitchChannelApproval, "77") is not None
    assert db.get(TwitchChannelApproval, "1").status == "approved"
    assert db.get(TwitchChannelApproval, "2").status == "rejected"


def test_live_config_shows_waiting_and_rejected_messages():
    """live_config.js reads mvp_allowed / approval and shows the waiting or rejected message instead of the series list (static check)."""
    js = _read(REPO_ROOT / "twitch-extension" / "live_config.js")
    assert "mvp_allowed === false" in js
    assert "data.approval" in js
    assert "This channel is waiting for the league's approval to set match MVPs." in js
    assert "This channel isn't approved to set match MVPs." in js
    load = js[js.index("function loadSeries"):]
    assert load.index("mvp_allowed === false") < load.index("_seriesData.forEach")


# ---------------------------------------------------------------------------
# Story 2 — Approve Streamers in the Portal
# ---------------------------------------------------------------------------

def test_admin_list_channels_groups_env_approved_pending_rejected(monkeypatch, env):
    """GET /admin/twitch/channels returns {env, approved, pending, rejected} with env channels listed as approved from server settings."""
    client, Session = _admin_client(monkeypatch)
    db = Session()
    _add_row(db, "11", "approved")
    _add_row(db, "12", "pending")
    _add_row(db, "13", "rejected")
    db.close()
    data = client.get("/admin/twitch/channels").json()
    assert set(data) == {"env", "approved", "pending", "rejected"}
    assert [c["channel_id"] for c in data["env"]] == [_OTHER]
    assert data["env"][0]["from_env"] is True and data["env"][0]["status"] == "approved"
    assert [c["channel_id"] for c in data["approved"]] == ["11"]
    assert [c["channel_id"] for c in data["pending"]] == ["12"]
    assert [c["channel_id"] for c in data["rejected"]] == ["13"]


def test_admin_list_channels_rows_carry_name_login_id_and_dates(monkeypatch, env):
    """Each row carries display_name and login when known, the numeric channel_id, first_seen_at and last_seen_at."""
    client, Session = _admin_client(monkeypatch)
    db = Session()
    _add_row(db, "12", "pending", seen=1234, display_name="Kanaliiga", login="kanaliiga")
    db.close()
    row = client.get("/admin/twitch/channels").json()["pending"][0]
    assert row["channel_id"] == "12"
    assert row["display_name"] == "Kanaliiga" and row["login"] == "kanaliiga"
    assert row["first_seen_at"] == 1234 and row["last_seen_at"] == 1234


def test_admin_list_channels_fills_missing_names_with_one_batched_helix_call(monkeypatch, env):
    """Missing names are looked up in one Helix call (at most 100 ids) and stored on the rows."""
    import twitch_channels
    from models import TwitchChannelApproval
    _oauth_env(monkeypatch)
    calls = []

    def fake(ids):
        calls.append(list(ids))
        return {cid: {"display_name": f"Name{cid}", "login": f"login{cid}"} for cid in ids}
    monkeypatch.setattr(twitch_channels, "fetch_twitch_users", fake)
    client, Session = _admin_client(monkeypatch)
    db = Session()
    for i in range(120):
        _add_row(db, str(100 + i), "pending")
    _add_row(db, "50", "approved", display_name="Known", login="known")
    db.close()
    data = client.get("/admin/twitch/channels").json()
    assert len(calls) == 1 and len(calls[0]) <= 100
    assert "50" not in calls[0]
    looked_up = set(calls[0])
    db = Session()
    for cid in looked_up - {_OTHER}:
        assert db.get(TwitchChannelApproval, cid).display_name == f"Name{cid}"
    db.close()
    env_row = data["env"][0]
    assert env_row["display_name"] == f"Name{_OTHER}"


def test_admin_list_channels_helix_failure_leaves_names_empty_and_still_loads(monkeypatch, env):
    """A Helix error leaves names empty and the list still returns 200."""
    import twitch_channels
    _oauth_env(monkeypatch)

    def boom(ids):
        raise RuntimeError("helix down")
    monkeypatch.setattr(twitch_channels, "fetch_twitch_users", boom)
    client, Session = _admin_client(monkeypatch)
    db = Session()
    _add_row(db, "12", "pending")
    db.close()
    resp = client.get("/admin/twitch/channels")
    assert resp.status_code == 200
    row = resp.json()["pending"][0]
    assert row["display_name"] is None and row["login"] is None and row["channel_id"] == "12"


def test_admin_list_channels_without_oauth_credentials_skips_helix(monkeypatch, env):
    """Without TWITCH_OAUTH_CLIENT_ID / _SECRET no Helix call is made and rows show the numeric id only."""
    import twitch_channels
    calls = []
    monkeypatch.setattr(twitch_channels, "fetch_twitch_users", lambda ids: calls.append(ids) or {})
    monkeypatch.setattr(twitch_channels._requests, "get",
                        lambda *a, **k: pytest.fail("no Helix call expected"))
    monkeypatch.setattr(twitch_channels._requests, "post",
                        lambda *a, **k: pytest.fail("no token call expected"))
    client, Session = _admin_client(monkeypatch)
    db = Session()
    _add_row(db, "12", "pending")
    db.close()
    resp = client.get("/admin/twitch/channels")
    assert resp.status_code == 200
    assert calls == []
    row = resp.json()["pending"][0]
    assert row["channel_id"] == "12" and row["display_name"] is None


def test_admin_approve_pending_channel_lets_set_mvp_through(db, monkeypatch, env):
    """Approve on a waiting channel makes it approved at once: its next POST /twitch/mvp is accepted."""
    _seed_series_match(db)
    with pytest.raises(HTTPException):
        _set_mvp(db)
    db.rollback()
    _decide(db, _CH, "approve")
    result = _set_mvp(db)
    assert result["player_id"] == 102
    assert _current(db)["mvp_allowed"] is True


def test_admin_approve_rejected_channel_makes_it_approved(db, monkeypatch, env):
    """Approve on a rejected channel moves it to approved and sets decided_at / decided_by."""
    _add_row(db, status="rejected")
    before = int(time.time())
    _decide(db, _CH, "approve")
    row = _row(db)
    assert row.status == "approved"
    assert row.decided_at >= before and row.decided_by == _ADMIN["user_id"]


def test_admin_reject_pending_channel_moves_to_rejected_and_blocks_mvp(db, monkeypatch, env):
    """Reject on a waiting channel moves it to rejected; POST /twitch/mvp stays 403."""
    _seed_series_match(db)
    _add_row(db, status="pending")
    _decide(db, _CH, "reject")
    assert _row(db).status == "rejected"
    with pytest.raises(HTTPException) as exc:
        _set_mvp(db)
    assert exc.value.status_code == 403
    db.rollback()
    assert _row(db).status == "rejected"
    _nothing_written(db)


def test_admin_remove_approved_channel_moves_to_rejected_and_blocks_mvp(db, monkeypatch, env):
    """Remove on an approved channel moves it to rejected; its next POST /twitch/mvp is 403 again."""
    _seed_series_match(db)
    _add_row(db, status="approved")
    _decide(db, _CH, "remove")
    assert _row(db).status == "rejected"
    with pytest.raises(HTTPException) as exc:
        _set_mvp(db)
    assert exc.value.status_code == 403
    db.rollback()
    _nothing_written(db)


@pytest.mark.parametrize("action,audit_action", [
    ("approve", "twitch_channel_approved"),
    ("reject", "twitch_channel_rejected"),
    ("remove", "twitch_channel_removed"),
])
def test_admin_channel_action_writes_audit_entry_with_channel_id(db, monkeypatch, env, action, audit_action):
    """Approve / Reject / Remove each write an AuditLog entry with the action name and the channel id."""
    from models import AuditLog
    _add_row(db, status="approved" if action == "remove" else "pending")
    _decide(db, _CH, action)
    entries = db.query(AuditLog).filter_by(action=audit_action).all()
    assert len(entries) == 1
    assert f"channel={_CH}" in entries[0].detail
    assert entries[0].actor_id == _ADMIN["user_id"] and entries[0].actor_username == "admin"


@pytest.mark.parametrize("action", ["approve", "reject", "remove"])
def test_admin_channel_action_route_requires_recent_reauth(action):
    """POST /admin/twitch/channels/{channel_id}/{action} has require_recent_reauth as a route dependency."""
    from routers import admin_twitch
    route = _route(admin_twitch.router, f"/admin/twitch/channels/{{channel_id}}/{action}", "POST")
    assert _needs_reauth(route)


def test_admin_channel_action_without_recent_reauth_returns_403_reauth_required(monkeypatch, env):
    """Without a recent password check, an action returns 403 {"detail": "reauth_required"} and changes nothing."""
    from models import AuditLog, TwitchChannelApproval
    client, Session = _admin_client(monkeypatch, reauth=False)
    db = Session()
    _add_row(db, "12", "pending")
    db.close()
    resp = client.post("/admin/twitch/channels/12/approve")
    assert resp.status_code == 403
    assert resp.json() == {"detail": "reauth_required"}
    db = Session()
    assert db.get(TwitchChannelApproval, "12").status == "pending"
    assert db.query(AuditLog).count() == 0
    db.close()


@pytest.mark.parametrize("action", ["approve", "reject", "remove"])
def test_admin_channel_action_unknown_channel_returns_404(monkeypatch, env, action):
    """An action on a channel id with no row (and not in the env list) returns 404."""
    client, _ = _admin_client(monkeypatch)
    assert client.post(f"/admin/twitch/channels/31337/{action}").status_code == 404


def test_admin_remove_env_channel_returns_409(monkeypatch, env):
    """Remove on a channel from TWITCH_MVP_CHANNEL_IDS returns 409 and it stays allowed."""
    import twitch
    client, Session = _admin_client(monkeypatch)
    db = Session()
    _add_row(db, _OTHER, "approved")
    db.close()
    assert client.post(f"/admin/twitch/channels/{_OTHER}/remove").status_code == 409
    db = Session()
    assert twitch.mvp_channel_allowed(_OTHER, db) is True
    db.close()


@pytest.mark.parametrize("method,path", [
    ("GET", "/admin/twitch/channels"),
    ("POST", "/admin/twitch/channels/123/approve"),
    ("POST", "/admin/twitch/channels/123/reject"),
    ("POST", "/admin/twitch/channels/123/remove"),
])
def test_admin_channel_endpoints_refuse_non_admins_with_403(monkeypatch, env, method, path):
    """Non-admins get 403 on every /admin/twitch/channels endpoint."""
    app, Session = _build_app(["routers.admin_twitch"])
    db = Session()
    _add_row(db, "123", "pending")
    db.close()
    _add_user(Session, user_id=2, username="bob", email="bob@example.com")
    client = TestClient(app)
    assert client.post("/_test/login/2").status_code == 200
    resp = client.request(method, path)
    assert resp.status_code == 403
    db = Session()
    from models import TwitchChannelApproval
    assert db.get(TwitchChannelApproval, "123").status == "pending"
    db.close()


def test_admin_frontend_approved_streamers_section_uses_admin_fetch_and_escapes_names():
    """The admin panel has an Approved streamers section (waiting / approved / rejected collapsed), uses adminFetch for actions and _escHtml for names; env channels show no Remove button (static check)."""
    html = _read(REPO_ROOT / "frontend" / "index.html")
    js = _read(REPO_ROOT / "frontend" / "app-admin-users.js")
    assert "Approved streamers" in html and 'id="twitchChannels"' in html
    render = js[js.index("function _renderTwitchChannels"):js.index("async function twitchChannelAction")]
    assert "Waiting for approval" in render and "Approved" in render
    assert re.search(r"<details><summary>Rejected", render)
    assert "c.from_env ? []" in render
    action = js[js.index("async function twitchChannelAction"):]
    action = action[:action.index("\n}\n")]
    assert "adminFetch(`${API}/admin/twitch/channels/" in action
    row = js[js.index("function _twitchChannelRow"):js.index("function _twitchChannelTable")]
    assert "_escHtml(c.display_name)" in row and "_escHtml(c.login)" in row
    assert "from server settings" in row


# ---------------------------------------------------------------------------
# Story 3 — Env Var and Portal Together
# ---------------------------------------------------------------------------

def test_mvp_channel_allowed_env_or_portal_approved(db, monkeypatch, env):
    """A channel may set MVPs when it is in TWITCH_MVP_CHANNEL_IDS or approved in the portal; pending/rejected/unknown may not."""
    import twitch
    _add_row(db, "11", "approved")
    _add_row(db, "12", "pending")
    _add_row(db, "13", "rejected")
    assert twitch.mvp_channel_allowed(_OTHER, db) is True
    assert twitch.mvp_channel_allowed("11", db) is True
    for cid in ("12", "13", "14"):
        assert twitch.mvp_channel_allowed(cid, db) is False


def test_mvp_channel_allowed_empty_lists_refuse_every_channel_in_production(db, monkeypatch):
    """With both lists empty and ENV=production, no channel may set MVPs (#165); pending rows don't count."""
    import twitch
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
    _add_row(db, "12", "pending")
    _add_row(db, "13", "rejected")
    for cid in ("12", "13", "14"):
        assert twitch.mvp_channel_allowed(cid, db) is False


def test_mvp_channel_allowed_empty_lists_allow_any_channel_outside_production(db, monkeypatch):
    """With both lists empty and no ENV=production, any channel may set MVPs (#165)."""
    import twitch
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
    _add_row(db, "12", "pending")
    assert twitch.mvp_channel_allowed("12", db) is True
    assert twitch.mvp_channel_allowed("14", db) is True


def test_mvp_channel_allowed_portal_approval_alone_requires_approval_for_others(db, monkeypatch):
    """Once any channel is approved in the portal (env empty), every other channel needs approval, also outside production."""
    import twitch
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
    _add_row(db, "11", "approved")
    assert twitch.mvp_channel_allowed("11", db) is True
    assert twitch.mvp_channel_allowed("14", db) is False


def test_mvp_channel_allowed_single_argument_call_still_works(monkeypatch):
    """twitch.mvp_channel_allowed("123") (no db) keeps the env-only #165 behaviour so test_issue_163::TestFailClosedDefaults passes."""
    import twitch
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
    assert twitch.mvp_channel_allowed("123") is False
    monkeypatch.delenv("ENV", raising=False)
    assert twitch.mvp_channel_allowed("123") is True
    monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", "111, 222")
    assert twitch.mvp_channel_allowed("222") is True
    assert twitch.mvp_channel_allowed("333") is False


def test_portal_remove_never_affects_channel_also_in_env(db, monkeypatch, env):
    """A channel in the env var with a portal row set to rejected is still allowed to set MVPs."""
    import twitch
    _add_row(db, _OTHER, "rejected")
    assert twitch.mvp_channel_allowed(_OTHER, db) is True
    data = _current(db, channel=_OTHER)
    assert data["mvp_allowed"] is True and data["approval"] == "approved"


def test_startup_warning_names_env_var_and_portal(monkeypatch, caplog):
    """warn_if_mvp_channels_unset in production with both lists empty logs a warning naming TWITCH_MVP_CHANNEL_IDS and the admin portal."""
    import twitch
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
    with caplog.at_level(logging.WARNING, logger="twitch"):
        twitch.warn_if_mvp_channels_unset()
    messages = [r.getMessage() for r in caplog.records if r.name == "twitch"]
    assert any("TWITCH_MVP_CHANNEL_IDS" in m and "admin portal" in m for m in messages)
