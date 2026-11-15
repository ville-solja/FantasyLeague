"""Tests for issue #215: streamer approval notifications.

Plan: markdown/plans/plan-issue-215-streamer-approval-notifications.md

New pending `twitch_channel_approvals` rows (issue #175) are announced to admins by
email and/or a Discord webhook from the week maintenance loop: batched (max 10 names,
then "and N more"), at least 30 minutes apart, once per channel (`notified_at`).
Admin › Twitch status gets an "Approval notifications" check, and
`POST /admin/twitch/notify-test` sends a test message.

Notes for the developer:
- Import not-yet-existing code INSIDE each test (`import admin_notify`,
  `from twitch_channels import notify_pending`) so this module collects before the
  implementation exists. `models` is imported at module level so the `db` fixture's
  `create_all` sees every table (markdown/lessons-learned.md).
- Time injection: `twitch_channels.notify_pending(db, now=<int>)`. Use fixed ints
  (e.g. `_T0 = 1_800_000_000`, then `_T0 + 29 * 60`, `_T0 + 31 * 60`); never sleep.
  Spacing is read from the latest `notified_at`, so a test can seed a row with
  `notified_at=_T0 - 10 * 60` to simulate "last message 10 minutes ago". Use the
  module constants (spacing 30 min, name limit 10) rather than literals where the
  test only needs "the limit".
- Faking Discord: monkeypatch `admin_notify.requests.post` (call it as
  `requests.post(...)` on the module, not `from requests import post`) with a
  recorder that stores `(url, json, timeout)` and returns an object with
  `status_code` (204 = ok, 404 = "error: http 404"); raise `requests.Timeout` for the
  "timeout" kind. Set the env var `ADMIN_NOTIFY_DISCORD_WEBHOOK_URL` to
  `https://discord.com/api/webhooks/1/secret-token` via monkeypatch; delenv it for
  "not configured".
- Faking email: call `email_utils.send_email(...)` through the module
  (`import email_utils`), so tests can monkeypatch `email_utils.send_email` with a
  recorder returning True/False. `email_configured()` reads `SMTP_HOST`: setenv it to
  "smtp.example" for "SMTP on", delenv for "SMTP off". Also delenv
  `ADMIN_NOTIFY_EMAILS` by default (the shell may export it) and setenv per test.
  Precedent: tests/test_issue_122_forgot_password_cooldown.py patches
  `routers.auth.send_email`.
- `admin_notify.last_result()` is process-global in-memory state: give the module a
  reset hook (e.g. `_reset_for_tests()` or a `_LAST` dict) and clear it in an
  autouse fixture so xdist/order doesn't leak results between tests.
- Helix: patch `twitch_channels._lookup_names` (no network) and clear
  TWITCH_OAUTH_CLIENT_ID / _SECRET like the `env` fixture in
  tests/test_issue_175_approved_streamers_admin.py. Reuse its `_add_row`
  (`from tests.test_issue_175_approved_streamers_admin import _add_row`, underscore
  names only so pytest doesn't collect its tests twice) and pass `notified_at=` via
  `**kw` once the column exists.
- Admin users with/without email: add `models.User(..., is_admin=True, email=...)`
  directly, or use `_add_user` from tests/test_issue_135_security_review_fixes.py and
  flip `is_admin`. Steam-only admins have `email=None`.
- HTTP route tests: `_build_app(["routers.admin_twitch"], admin_override=True)`
  (test_issue_135) and override `deps.require_recent_reauth` for happy paths
  (`_admin_client` in test_issue_175 does both). Re-auth wiring: `_route` +
  `_needs_reauth` from tests/test_issue_163_twitch_steam_account_hardening.py.
  Rate limit: `_build_app(..., rate_limited=True, admin_override=True)` and read the
  limit from the reloaded router module (`routers.admin_twitch.limiter`), never from
  `rate_limit` (lessons-learned: Limiter identity under -n auto). Check
  `wc -l backend/routers/admin_twitch.py` against the 350-line cap
  (test_issue_85) before adding the route; keep it a thin wrapper.
- Status: `twitch_status.build_status(db)["checks"]`; find the row by key (suggested
  key `approval_notifications`) like `_row` in
  tests/test_issue_180_twitch_integration_status.py.
- Loop: put the call in a helper with its own try/except (like `_run_finals_check` /
  `_run_caster_tag_sync` in main.py) because test_issue_117 slices the loop body
  from its first `try:` to its first `except Exception`. Any test that runs the loop
  (test_architecture_review_fixes, test_issue_161, test_issue_237) may need the new
  helper stubbed out.
- Migration: `044_twitch_channel_approvals_notified_at`; `_legacy_engine` in
  tests/test_issue_129_* shows how to build a pre-migration DB. The schema coverage
  gate is tests/test_migrate.py::TestSchemaCoverage.
- Secrets: assert with caplog (`caplog.set_level(logging.DEBUG)`) that the webhook
  URL / its token and recipient addresses are absent from `caplog.text`, response
  JSON, status JSON and `AuditLog.detail`.
"""
import logging
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy import inspect as sa_inspect

import models  # noqa: F401  (register every table for the db fixture)
from tests.test_issue_135_security_review_fixes import _build_app
from tests.test_issue_163_twitch_steam_account_hardening import _needs_reauth, _route
from tests.test_issue_175_approved_streamers_admin import _add_row

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_T0 = 1_800_000_000
_WEBHOOK = "https://discord.com/api/webhooks/1/secret-token"
_ADMIN = {"user_id": 1, "username": "admin"}
_ADDR_A = "first-admin@example.org"
_ADDR_B = "second-admin@example.org"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _notify_env(monkeypatch):
    """No channel configured, no Helix, no APP_BASE_URL; fresh in-memory last result."""
    import admin_notify
    import twitch_channels
    for k in ("ADMIN_NOTIFY_DISCORD_WEBHOOK_URL", "ADMIN_NOTIFY_EMAILS", "SMTP_HOST", "APP_BASE_URL",
              "TWITCH_OAUTH_CLIENT_ID", "TWITCH_OAUTH_CLIENT_SECRET", "TWITCH_OAUTH_REDIRECT_URI",
              "TWITCH_MVP_CHANNEL_IDS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(twitch_channels, "_lookup_names", lambda ids: {})
    admin_notify._reset_for_tests()
    twitch_channels._reset_notify_backoff()
    yield
    admin_notify._reset_for_tests()
    twitch_channels._reset_notify_backoff()


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


def _discord(monkeypatch, status=204, exc=None, url=_WEBHOOK):
    """Configure the webhook and record posts as (url, json, timeout)."""
    import admin_notify
    monkeypatch.setenv("ADMIN_NOTIFY_DISCORD_WEBHOOK_URL", url)
    calls = []

    def fake_post(u, json=None, timeout=None, **kw):
        calls.append((u, json, timeout))
        assert kw.get("allow_redirects") is False
        if exc is not None:
            raise exc
        return _Resp(status)

    monkeypatch.setattr(admin_notify.requests, "post", fake_post)
    return calls


def _email(monkeypatch, ok=True, smtp=True):
    """SMTP on (or off) and record send_email calls as (to, subject, body)."""
    import email_utils
    if smtp:
        monkeypatch.setenv("SMTP_HOST", "smtp.example")
    calls = []

    def fake_send(to, subject, body):
        calls.append((to, subject, body))
        return ok

    monkeypatch.setattr(email_utils, "send_email", fake_send)
    return calls


def _admin(db, uid, email, is_admin=True, username=None):
    db.add(models.User(id=uid, username=username or f"user{uid}", email=email,
                       is_admin=is_admin, tokens=0))
    db.commit()


def _notify(db, now=_T0):
    from twitch_channels import notify_pending
    return notify_pending(db, now=now)


def _row(db, channel):
    db.expire_all()
    return db.get(models.TwitchChannelApproval, channel)


def _audits(db, action):
    return db.query(models.AuditLog).filter(models.AuditLog.action == action).all()


def _status_row(db, key="approval_notifications"):
    import twitch_status
    rows = [c for c in twitch_status.build_status(db)["checks"] if c["key"] == key]
    assert len(rows) == 1
    return rows[0]


def _client(reauth=True, rate_limited=False):
    from deps import require_recent_reauth
    app, Session = _build_app(["routers.admin_twitch"], admin_override=True, rate_limited=rate_limited)
    if reauth:
        app.dependency_overrides[require_recent_reauth] = lambda: dict(_ADMIN)
    return TestClient(app), Session


# ---------------------------------------------------------------------------
# Data: column and migration
# ---------------------------------------------------------------------------

def test_twitch_channel_approval_has_nullable_notified_at_column(db):
    """`twitch_channel_approvals.notified_at` exists (Integer, nullable); new rows start with it empty."""
    cols = {c["name"]: c for c in sa_inspect(db.get_bind()).get_columns("twitch_channel_approvals")}
    assert "notified_at" in cols
    assert cols["notified_at"]["nullable"] is True
    assert "INT" in str(cols["notified_at"]["type"]).upper()
    _add_row(db, "100")
    assert _row(db, "100").notified_at is None


def test_run_migrations_044_adds_notified_at_and_keeps_existing_rows_null():
    """Migration 044_twitch_channel_approvals_notified_at adds the column on a legacy DB; existing pending rows keep NULL so the backlog is announced once."""
    import migrate
    from database import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE twitch_channel_approvals"))
        conn.execute(text("""CREATE TABLE twitch_channel_approvals (
            channel_id TEXT PRIMARY KEY, status TEXT NOT NULL, display_name TEXT, login TEXT,
            first_seen_at INTEGER NOT NULL, last_seen_at INTEGER NOT NULL,
            decided_at INTEGER, decided_by INTEGER)"""))
        conn.execute(text("INSERT INTO twitch_channel_approvals (channel_id, status, first_seen_at, "
                          "last_seen_at) VALUES ('555', 'pending', 1, 1)"))
        conn.commit()
        migrate._ensure_migrations_table(conn)
        for migration_id, _ in migrate.MIGRATIONS:
            if migration_id < "044":
                migrate._record(conn, migration_id)
    assert ("044_twitch_channel_approvals_notified_at", migrate._m044_twitch_channel_approvals_notified_at) \
        in migrate.MIGRATIONS
    migrate.run_migrations(engine)
    assert "notified_at" in {c["name"] for c in sa_inspect(engine).get_columns("twitch_channel_approvals")}
    with engine.connect() as conn:
        assert conn.execute(text("SELECT notified_at FROM twitch_channel_approvals "
                                 "WHERE channel_id = '555'")).scalar() is None
    migrate.run_migrations(engine)  # idempotent


# ---------------------------------------------------------------------------
# Story: Admins Hear About a New Streamer Request Outside the Site
# ---------------------------------------------------------------------------

def test_notify_pending_new_pending_request_is_announced_and_marked(db, monkeypatch):
    """Trigger: a new pending request is sent in one message on the next check and gets `notified_at = now`."""
    import twitch_channels
    posts = _discord(monkeypatch)
    twitch_channels.record_request(db, "123456789", now=_T0 - 60)
    db.commit()
    assert _notify(db) == 1
    assert len(posts) == 1
    assert "channel 123456789" in posts[0][1]["content"]
    assert _row(db, "123456789").notified_at == _T0


def test_notify_pending_several_requests_go_in_one_message(db, monkeypatch):
    """One message for many: three unannounced pending requests produce exactly one Discord post / one email per recipient naming all three."""
    posts = _discord(monkeypatch)
    mails = _email(monkeypatch)
    _admin(db, 1, _ADDR_A)
    _admin(db, 2, _ADDR_B)
    for i, ch in enumerate(("101", "102", "103")):
        _add_row(db, ch, seen=1000 + i)
    assert _notify(db) == 3
    assert len(posts) == 1
    assert sorted(m[0] for m in mails) == [_ADDR_A, _ADDR_B]
    for content in [posts[0][1]["content"], mails[0][2], mails[1][2]]:
        assert all(f"channel {ch}" in content for ch in ("101", "102", "103"))
        assert content.startswith("3 Twitch channels are waiting for MVP approval")


def test_notify_pending_message_names_ten_channels_then_and_n_more(db, monkeypatch):
    """With 13 waiting requests the message names 10 (oldest first), says "and 3 more" and gives the total 13."""
    import twitch_channels
    posts = _discord(monkeypatch)
    for i in range(13):
        _add_row(db, str(500 + i), seen=1000 + i)
    assert _notify(db) == 13
    content = posts[0][1]["content"]
    limit = twitch_channels.NOTIFY_NAME_LIMIT
    named = [str(500 + i) for i in range(13) if f"channel {500 + i}" in content]
    assert named == [str(500 + i) for i in range(limit)]
    assert f"and {13 - limit} more" in content
    assert content.startswith("13 Twitch channels")
    assert all(_row(db, str(500 + i)).notified_at == _T0 for i in range(13))


def test_notify_pending_message_shows_display_name_login_or_channel_id(db, monkeypatch):
    """Names read "Kanaliiga (kanaliiga)"; a channel Helix has no name for reads "channel <id>"."""
    import twitch_channels
    posts = _discord(monkeypatch)
    monkeypatch.setattr(twitch_channels, "_lookup_names",
                        lambda ids: {"111": {"display_name": "Kanaliiga", "login": "kanaliiga"}})
    _add_row(db, "111", seen=1000)
    _add_row(db, "123456789", seen=1001)
    _notify(db)
    content = posts[0][1]["content"]
    assert "Kanaliiga (kanaliiga), channel 123456789." in content
    assert _row(db, "111").display_name == "Kanaliiga"  # names stored


def test_notify_pending_message_link_only_when_app_base_url_set(db, monkeypatch):
    """The admin link (APP_BASE_URL) is in the text when set and left out when unset; subject is "Kana Cards: N streamers waiting for approval"."""
    import twitch_channels
    mails = _email(monkeypatch)
    _admin(db, 1, _ADDR_A)
    _add_row(db, "101", seen=1000)
    _add_row(db, "102", seen=1001)
    _notify(db)
    assert mails[0][1] == "Kana Cards: 2 streamers waiting for approval"
    assert mails[0][2].endswith("Approve or reject them in Admin › Twitch › Approved streamers.")
    assert "https://" not in mails[0][2]

    monkeypatch.setenv("APP_BASE_URL", "https://league.example/")
    _add_row(db, "103", seen=1002)
    _notify(db, now=_T0 + twitch_channels.NOTIFY_SPACING)
    assert mails[1][2].endswith("Approved streamers: https://league.example")


def test_notify_pending_already_notified_channel_is_not_announced_again(db, monkeypatch):
    """Once per channel: a second check with no new requests sends nothing."""
    import twitch_channels
    posts = _discord(monkeypatch)
    _add_row(db, "101")
    assert _notify(db) == 1
    assert _notify(db, now=_T0 + 2 * twitch_channels.NOTIFY_SPACING) == 0
    assert len(posts) == 1


def test_record_request_later_visit_keeps_notified_at_and_is_not_reannounced(db, monkeypatch):
    """A channel's later visit (record_request bumping last_seen_at) leaves notified_at set and triggers no new message."""
    import twitch_channels
    posts = _discord(monkeypatch)
    twitch_channels.record_request(db, "101", now=_T0 - 60)
    db.commit()
    _notify(db)
    twitch_channels.record_request(db, "101", now=_T0 + 3600)
    db.commit()
    row = _row(db, "101")
    assert row.last_seen_at == _T0 + 3600 and row.notified_at == _T0
    assert _notify(db, now=_T0 + 2 * 3600) == 0
    assert len(posts) == 1


def test_notify_pending_approved_and_rejected_channels_are_not_announced(db, monkeypatch):
    """Approved and rejected rows with empty notified_at are never in a message and stay unmarked."""
    posts = _discord(monkeypatch)
    _add_row(db, "201", status="approved")
    _add_row(db, "202", status="rejected")
    assert _notify(db) == 0
    assert posts == []
    _add_row(db, "203")
    _notify(db)
    content = posts[0][1]["content"]
    assert "203" in content and "201" not in content and "202" not in content
    assert _row(db, "201").notified_at is None and _row(db, "202").notified_at is None


def test_notify_pending_within_30_minutes_of_last_message_sends_nothing(db, monkeypatch):
    """Spacing: a new request 10 minutes after the last message is not sent and stays unannounced."""
    posts = _discord(monkeypatch)
    _add_row(db, "101", notified_at=_T0 - 10 * 60)
    _add_row(db, "102")
    assert _notify(db) == 0
    assert posts == []
    assert _row(db, "102").notified_at is None


def test_notify_pending_after_spacing_sends_requests_that_waited(db, monkeypatch):
    """Spacing: a check 30+ minutes after the last message sends the requests that arrived in between."""
    posts = _discord(monkeypatch)
    _add_row(db, "101", notified_at=_T0)
    _add_row(db, "102", seen=1000)
    _add_row(db, "103", seen=1001)
    assert _notify(db, now=_T0 + 29 * 60) == 0
    assert _notify(db, now=_T0 + 31 * 60) == 2
    content = posts[0][1]["content"]
    assert "102" in content and "103" in content and "channel 101" not in content
    assert content.startswith("2 new Twitch channels asked for MVP approval")
    assert "3 are waiting in all" in content


def test_admin_notify_email_recipients_default_to_admins_with_email(db, monkeypatch):
    """Email: by default every is_admin account with an email gets one message; non-admins and email-less admins don't."""
    import admin_notify
    mails = _email(monkeypatch)
    _admin(db, 1, _ADDR_A)
    _admin(db, 2, None)                                   # Steam-only admin
    _admin(db, 3, "player@example.org", is_admin=False)
    _admin(db, 4, _ADDR_B)
    assert admin_notify.channels(db)["email"] == {"ready": True, "recipients": 2, "reason": "set"}
    _add_row(db, "101")
    _notify(db)
    assert sorted(m[0] for m in mails) == [_ADDR_A, _ADDR_B]


def test_admin_notify_email_recipients_env_list_replaces_default(db, monkeypatch):
    """ADMIN_NOTIFY_EMAILS (comma-separated) replaces the admin list; one message per address, no CC."""
    mails = _email(monkeypatch)
    _admin(db, 1, _ADDR_A)
    monkeypatch.setenv("ADMIN_NOTIFY_EMAILS", " ops@example.org, ,mods@example.org ")
    _add_row(db, "101")
    _notify(db)
    assert [m[0] for m in mails] == ["ops@example.org", "mods@example.org"]
    assert all("," not in m[0] for m in mails)


def test_admin_notify_email_off_disables_email_channel(db, monkeypatch):
    """ADMIN_NOTIFY_EMAILS=off: email is not ready and send_email is never called."""
    import admin_notify
    mails = _email(monkeypatch)
    _admin(db, 1, _ADDR_A)
    monkeypatch.setenv("ADMIN_NOTIFY_EMAILS", "off")
    assert admin_notify.channels(db)["email"]["ready"] is False
    _add_row(db, "101")
    assert _notify(db) == 0
    assert mails == []
    assert admin_notify.send("s", "t", db)["email"] == "off"
    assert mails == []


def test_admin_notify_email_without_smtp_is_not_ready_and_not_sent(db, monkeypatch):
    """No SMTP_HOST: email channel reports not ready and nothing is sent."""
    import admin_notify
    mails = _email(monkeypatch, smtp=False)
    _admin(db, 1, _ADDR_A)
    email = admin_notify.channels(db)["email"]
    assert email["ready"] is False and email["reason"] == "SMTP is not configured"
    _add_row(db, "101")
    assert _notify(db) == 0
    assert mails == []
    assert _row(db, "101").notified_at is None


def test_admin_notify_discord_posts_payload_with_mentions_disabled(db, monkeypatch):
    """Discord: posts {"content", "allowed_mentions": {"parse": []}, "username": "Kana Cards"} to the webhook with a timeout."""
    import admin_notify
    posts = _discord(monkeypatch)
    result = admin_notify.send("subject", "hello", db)
    assert result["discord"] == "ok"
    url, payload, timeout = posts[0]
    assert url == _WEBHOOK
    assert payload == {"content": "hello", "allowed_mentions": {"parse": []}, "username": "Kana Cards"}
    assert timeout and timeout > 0


@pytest.mark.parametrize("url", [
    "https://example.com/api/webhooks/1/x",
    "http://discord.com/api/webhooks/1/x",
    "https://discord.com.evil.example/api/webhooks/1/x",
    "https://discord.com/api/other/1/x",
    "https://user@discord.com/api/webhooks/1/x",
    "https://discord.com:8443/api/webhooks/1/x",
    "not a url",
])
def test_admin_notify_non_discord_webhook_url_is_not_ready(db, monkeypatch, url):
    """A webhook URL that isn't https://discord.com|discordapp.com/api/webhooks/… is treated as off and never posted to."""
    import admin_notify
    posts = _discord(monkeypatch, url=url)
    discord = admin_notify.channels(db)["discord"]
    assert discord["ready"] is False
    assert "not a Discord webhook" in discord["reason"]
    assert admin_notify.send("s", "t", db)["discord"] == "off"
    _add_row(db, "101")
    assert _notify(db) == 0
    assert posts == []
    # The other Discord host is accepted.
    monkeypatch.setenv("ADMIN_NOTIFY_DISCORD_WEBHOOK_URL", "https://discordapp.com/api/webhooks/1/x")
    assert admin_notify.channels(db)["discord"]["ready"] is True


def test_notify_pending_all_channels_fail_leaves_requests_unannounced(db, monkeypatch):
    """Failure: Discord 500 and send_email False -> notified_at stays NULL and a later check retries."""
    posts = _discord(monkeypatch, status=500)
    mails = _email(monkeypatch, ok=False)
    _admin(db, 1, _ADDR_A)
    _add_row(db, "101")
    assert _notify(db) == 0
    assert len(posts) == 1 and len(mails) == 1
    assert _row(db, "101").notified_at is None
    assert _audits(db, "twitch_approval_notified") == []
    import twitch_channels
    _discord(monkeypatch, status=204)
    assert _notify(db, now=_T0 + twitch_channels.NOTIFY_SPACING) == 1
    assert _row(db, "101").notified_at == _T0 + twitch_channels.NOTIFY_SPACING


def test_notify_pending_one_channel_failing_still_sends_other_and_marks(db, monkeypatch):
    """Failure: Discord raising requests.Timeout doesn't stop email; requests are marked because one channel sent."""
    import admin_notify
    _discord(monkeypatch, exc=admin_notify.requests.Timeout())
    mails = _email(monkeypatch)
    _admin(db, 1, _ADDR_A)
    _add_row(db, "101")
    assert _notify(db) == 1
    assert len(mails) == 1
    assert _row(db, "101").notified_at == _T0
    assert admin_notify.last_result()["discord"] == "error: timeout"
    assert admin_notify.last_result()["email"] == "ok"


def test_notify_pending_nothing_configured_sends_and_marks_nothing(db, monkeypatch):
    """Unconfigured: no webhook and no SMTP -> nothing sent, notified_at stays NULL so the backlog goes out after setup."""
    import admin_notify
    calls = []
    monkeypatch.setattr(admin_notify.requests, "post", lambda *a, **k: calls.append(a))
    _admin(db, 1, _ADDR_A)
    _add_row(db, "101")
    _add_row(db, "102")
    assert _notify(db) == 0
    assert calls == [] and admin_notify.last_result() == {}
    assert _row(db, "101").notified_at is None and _row(db, "102").notified_at is None
    posts = _discord(monkeypatch)
    assert _notify(db, now=_T0 + 60) == 2
    assert len(posts) == 1


def test_notify_pending_audits_twitch_approval_notified_with_counts_only(db, monkeypatch):
    """A sent batch writes a `twitch_approval_notified` audit row with the channel count and channels used, never addresses or the URL."""
    _discord(monkeypatch)
    _email(monkeypatch)
    _admin(db, 1, _ADDR_A)
    _add_row(db, "101")
    _add_row(db, "102")
    _notify(db)
    rows = _audits(db, "twitch_approval_notified")
    assert len(rows) == 1
    assert rows[0].detail == "channels=2 via=discord,email"
    assert rows[0].actor_username == "system"


def test_week_maintenance_loop_runs_notify_pending_in_its_own_try():
    """main._week_maintenance_loop calls notify_pending through a best-effort helper with its own try/except."""
    import inspect
    import main
    loop = inspect.getsource(main._week_maintenance_loop)
    try_block = loop[loop.index("try:"):loop.index("except Exception")]
    assert "_run_approval_notifications(db)" in try_block
    helper = inspect.getsource(main._run_approval_notifications)
    assert "twitch_channels.notify_pending(db)" in helper
    assert "except Exception" in helper and "db.rollback()" in helper


def test_notify_pending_helper_swallows_exceptions(monkeypatch, caplog):
    """Failure: notify_pending raising inside the loop helper is logged and does not propagate (the loop keeps running)."""
    import main

    class _DB:
        rolled_back = False

        def rollback(self):
            self.rolled_back = True

    def boom(db, now=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(main.twitch_channels, "notify_pending", boom)
    db = _DB()
    with caplog.at_level(logging.ERROR):
        main._run_approval_notifications(db)
    assert db.rolled_back
    assert "Streamer approval notification failed" in caplog.text


# ---------------------------------------------------------------------------
# Story: The Operator Configures and Checks the Notifications
# ---------------------------------------------------------------------------

def test_build_status_approval_notifications_ok_names_ready_channels(db, monkeypatch):
    """Status: with webhook + SMTP and 2 admin emails the check is ok and names "Discord" and "email to 2 recipients"."""
    _discord(monkeypatch)
    _email(monkeypatch)
    _admin(db, 1, _ADDR_A)
    _admin(db, 2, _ADDR_B)
    row = _status_row(db)
    assert row["state"] == "ok"
    assert row["label"] == "Approval notifications"
    assert "Ready: Discord, email to 2 recipients." in row["detail"]


def test_build_status_approval_notifications_warns_when_nothing_ready(db, monkeypatch):
    """Status: no webhook and no SMTP gives a warning state."""
    row = _status_row(db)
    assert row["state"] == "warning"
    assert "No channel is ready" in row["detail"]
    assert "not set" in row["detail"] and "SMTP is not configured" in row["detail"]


def test_build_status_approval_notifications_warns_on_non_discord_webhook(db, monkeypatch):
    """Status: a webhook URL that isn't a Discord webhook (and no email) gives a warning that says so."""
    monkeypatch.setenv("ADMIN_NOTIFY_DISCORD_WEBHOOK_URL", "https://example.com/hook/secret-token")
    row = _status_row(db)
    assert row["state"] == "warning"
    assert "not a Discord webhook address" in row["detail"]
    assert "example.com" not in row["detail"] and "secret-token" not in row["detail"]


def test_build_status_approval_notifications_shows_last_message_time_and_error_kind(db, monkeypatch):
    """Status: after a send with Discord failing (http 404), the detail shows the last message time and the error kind."""
    import time
    import admin_notify
    _discord(monkeypatch, status=404)
    _email(monkeypatch)
    _admin(db, 1, _ADDR_A)
    _add_row(db, "101")
    _notify(db)
    at = admin_notify.last_result()["at"]
    detail = _status_row(db)["detail"]
    assert f"Last message {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(at))}:" in detail
    assert "Discord http 404" in detail and "email sent" in detail

    # After a restart (no in-memory result) the time comes from notified_at.
    admin_notify._reset_for_tests()
    assert "Last message 2027-01-15 08:00 UTC." in _status_row(db)["detail"]


def test_admin_notify_test_route_returns_per_channel_results(monkeypatch):
    """Test: POST /admin/twitch/notify-test sends a test message to each configured channel and returns e.g. {"discord": "ok", "email": ...}."""
    posts = _discord(monkeypatch)
    mails = _email(monkeypatch)
    client, Session = _client()
    _admin(Session(), 1, _ADDR_A)
    resp = client.post("/admin/twitch/notify-test")
    assert resp.status_code == 200
    assert resp.json() == {"discord": "ok", "email": "ok", "email_sent": 1}
    assert len(posts) == 1 and "Test message" in posts[0][1]["content"]
    assert len(mails) == 1 and mails[0][0] == _ADDR_A


def test_admin_notify_test_route_reports_off_and_error_per_channel(monkeypatch):
    """Test: with the webhook unset and SMTP failing, the result shows Discord off and email's error kind (HTTP 200, no exception)."""
    _email(monkeypatch, ok=False)
    client, Session = _client()
    _admin(Session(), 1, _ADDR_A)
    resp = client.post("/admin/twitch/notify-test")
    assert resp.status_code == 200
    assert resp.json() == {"discord": "off", "email": "error: smtp", "email_sent": 0}


def test_admin_notify_test_route_writes_admin_twitch_notify_test_audit(monkeypatch):
    """Test: the route writes an `admin_twitch_notify_test` audit row without the URL or addresses."""
    _discord(monkeypatch, status=404)
    _email(monkeypatch)
    client, Session = _client()
    _admin(Session(), 1, _ADDR_A)
    client.post("/admin/twitch/notify-test")
    rows = _audits(Session(), "admin_twitch_notify_test")
    assert len(rows) == 1
    assert rows[0].actor_id == 1
    assert rows[0].detail == "discord=error: http 404 email=ok email_sent=1"
    assert "secret-token" not in rows[0].detail and _ADDR_A not in rows[0].detail


def test_admin_notify_test_route_requires_recent_reauth():
    """POST /admin/twitch/notify-test has require_recent_reauth as a route dependency."""
    from routers import admin_twitch
    assert _needs_reauth(_route(admin_twitch.router, "/admin/twitch/notify-test", "POST"))


def test_admin_notify_test_route_without_recent_reauth_returns_403_and_sends_nothing(monkeypatch):
    """Without a recent re-auth the route returns 403 reauth_required; no Discord post or email."""
    posts = _discord(monkeypatch)
    mails = _email(monkeypatch)
    client, Session = _client(reauth=False)
    _admin(Session(), 1, _ADDR_A)
    resp = client.post("/admin/twitch/notify-test")
    assert resp.status_code == 403
    assert "reauth_required" in resp.text
    assert posts == [] and mails == []


def test_admin_notify_test_route_non_admin_is_rejected(monkeypatch):
    """A signed-out or non-admin caller gets 401/403 and nothing is sent."""
    from deps import require_recent_reauth
    posts = _discord(monkeypatch)
    app, Session = _build_app(["routers.admin_twitch"])
    app.dependency_overrides[require_recent_reauth] = lambda: dict(_ADMIN)
    client = TestClient(app)
    assert client.post("/admin/twitch/notify-test").status_code in (401, 403)
    db = Session()
    _admin(db, 2, "player@example.org", is_admin=False, username="player")
    client.post("/_test/login/2")
    assert client.post("/admin/twitch/notify-test").status_code == 403
    assert posts == []


def test_admin_notify_test_route_is_rate_limited(monkeypatch):
    """The route is rate-limited (3/minute): the 4th call in a minute returns 429."""
    import importlib
    _discord(monkeypatch)
    client, _ = _client(rate_limited=True)
    admin_twitch = importlib.import_module("routers.admin_twitch")
    assert admin_twitch.RATE_LIMIT_NOTIFY_TEST == "3/minute"
    assert admin_twitch.limiter.enabled
    for _ in range(3):
        assert client.post("/admin/twitch/notify-test").status_code == 200
    assert client.post("/admin/twitch/notify-test").status_code == 429


def test_webhook_url_never_in_status_response_audit_or_logs(db, monkeypatch, caplog):
    """Secrets: the webhook URL/token appears in no status JSON, route response, audit detail or log line (status shows only "set")."""
    import json
    import admin_notify
    caplog.set_level(logging.DEBUG)
    _discord(monkeypatch, status=404)
    _add_row(db, "101")
    _notify(db)
    admin_notify.send_test(db, _ADMIN)
    _discord(monkeypatch, exc=admin_notify.requests.ConnectionError(_WEBHOOK))
    result = admin_notify.send_test(db, _ADMIN)
    assert result["discord"] == "error: connection"
    import twitch_status
    blobs = [json.dumps(twitch_status.build_status(db)), json.dumps(result), caplog.text,
             json.dumps(admin_notify.channels(db))]
    blobs += [a.detail or "" for a in db.query(models.AuditLog).all()]
    for blob in blobs:
        assert "secret-token" not in blob and "api/webhooks" not in blob
    assert "http 404" in caplog.text  # failures are logged, as a kind

    client, _ = _client()
    resp = client.post("/admin/twitch/notify-test")
    assert "secret-token" not in resp.text and "webhooks" not in resp.text


def test_recipient_addresses_never_in_status_or_audit(db, monkeypatch, caplog):
    """Secrets: admin addresses appear only as a count in status and audit, and failure logs carry no address."""
    import json
    import admin_notify
    import twitch_status
    caplog.set_level(logging.DEBUG)
    _email(monkeypatch, ok=False)
    _admin(db, 1, _ADDR_A)
    _admin(db, 2, _ADDR_B)
    _add_row(db, "101")
    _notify(db)
    admin_notify.send_test(db, _ADMIN)
    _email(monkeypatch, ok=True)
    _notify(db, now=_T0 + 60)
    status = json.dumps(twitch_status.build_status(db))
    assert "email to 2 recipients" in status
    blobs = [status, caplog.text] + [a.detail or "" for a in db.query(models.AuditLog).all()]
    for blob in blobs:
        assert _ADDR_A not in blob and _ADDR_B not in blob and "example.org" not in blob
    assert "email failed (smtp)" in caplog.text


def test_env_example_documents_admin_notify_env_vars():
    """Docs: .env.example and markdown/features/reference/commands.md describe ADMIN_NOTIFY_DISCORD_WEBHOOK_URL and ADMIN_NOTIFY_EMAILS."""
    env = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    commands = (REPO_ROOT / "markdown" / "features" / "reference" / "commands.md").read_text(encoding="utf-8")
    for name in ("ADMIN_NOTIFY_DISCORD_WEBHOOK_URL", "ADMIN_NOTIFY_EMAILS"):
        assert name in commands
        lines = [l for l in env.splitlines() if l.lstrip("# ").startswith(name + "=")]
        assert lines, name
        assert all(l.split("=", 1)[1].strip() == "" for l in lines), "no values in .env.example"


def test_feature_doc_documents_admin_notify_env_vars():
    """Docs: markdown/features/reference/streamer-approval-notifications.md names both env vars and the test button."""
    doc = (REPO_ROOT / "markdown" / "features" / "reference" / "streamer-approval-notifications.md").read_text(
        encoding="utf-8")
    for needle in ("ADMIN_NOTIFY_DISCORD_WEBHOOK_URL", "ADMIN_NOTIFY_EMAILS", "Send test notification",
                   "POST /admin/twitch/notify-test", "notified_at"):
        assert needle in doc
    assert "(planned)" not in doc


# ---------------------------------------------------------------------------
# Story: Notifications Can't Be Used to Spam Admins
# ---------------------------------------------------------------------------

def test_notify_pending_burst_sends_at_most_one_message_per_30_minutes(db, monkeypatch):
    """Rate: 50 requests over 59 minutes with checks every 5 minutes yield at most two messages, each with at most 10 names."""
    import twitch_channels
    posts = _discord(monkeypatch)
    arrival = {i: i * 59 // 49 for i in range(50)}  # minute 0 .. 59
    for minute in range(60):
        now = _T0 + minute * 60
        for i in [i for i, m in arrival.items() if m == minute]:
            twitch_channels.record_request(db, str(10_000 + i), now=now)
        db.commit()
        if minute % 5 == 0:
            _notify(db, now=now)
    assert db.query(models.TwitchChannelApproval).count() == 50
    assert 1 <= len(posts) <= 2
    for _, payload, _ in posts:
        assert payload["content"].count("channel ") <= twitch_channels.NOTIFY_NAME_LIMIT
    sent_at = sorted({r.notified_at for r in db.query(models.TwitchChannelApproval).all() if r.notified_at})
    assert len(sent_at) == len(posts)
    assert all(b - a >= twitch_channels.NOTIFY_SPACING for a, b in zip(sent_at, sent_at[1:]))


def test_safe_name_strips_control_and_hidden_characters():
    """Names are cleaned of control and zero-width/bidi characters (clean_display_text) before use."""
    import admin_notify
    assert admin_notify.safe_name("Ka​na‮li\x07iga\n") == "Kanaliiga"
    assert admin_notify.channel_label("1", "​‍", "x") == "channel 1"


def test_safe_name_escapes_discord_markdown():
    """Discord markdown characters (\\ * _ ~ ` | > #) in a name are escaped."""
    import admin_notify
    assert admin_notify.safe_name("a*b_c~d`e|f>g#h\\i", discord=True) == "a\\*b\\_c\\~d\\`e\\|f\\>g\\#h\\\\i"
    assert admin_notify.safe_name("a*b_c", discord=False) == "a*b_c"
    assert admin_notify.channel_label("1", "**Bold**", "bold_one", discord=True) == "\\*\\*Bold\\*\\* (bold\\_one)"


def test_discord_payload_mention_names_cannot_ping(db, monkeypatch):
    """A channel named "@everyone" / "@here" / "<@&123>" is sent with allowed_mentions parse [] so nobody is notified."""
    import twitch_channels
    posts = _discord(monkeypatch)
    names = {"301": "@everyone", "302": "@here", "303": "<@&123>"}
    monkeypatch.setattr(twitch_channels, "_lookup_names",
                        lambda ids: {i: {"display_name": names[i], "login": None} for i in ids if i in names})
    for i, ch in enumerate(names):
        _add_row(db, ch, seen=1000 + i)
    _notify(db)
    payload = posts[0][1]
    assert payload["allowed_mentions"] == {"parse": []}
    for name in ("@everyone", "@here", "<@&123"):
        assert name in payload["content"]


@pytest.mark.parametrize("name", ["http://evil.example", "example.com", "www.free-skins", "Get skins at a.ru"])
def test_notify_pending_link_like_name_shown_as_channel_id(db, monkeypatch, name):
    """A display name that looks like a link (http://…, example.com) is shown as "channel <id>" instead."""
    posts = _discord(monkeypatch)
    _add_row(db, "401", display_name=name, login="evil")
    _notify(db)
    content = posts[0][1]["content"]
    assert "channel 401" in content
    assert name not in content and "(evil)" not in content


def test_notify_pending_request_dropped_by_pending_cap_is_not_announced(db, monkeypatch):
    """Bounded: a request dropped by the 200-row PENDING_CAP is never in a message."""
    import twitch_channels
    posts = _discord(monkeypatch)
    for i in range(twitch_channels.PENDING_CAP):
        twitch_channels.record_request(db, str(1000 + i), now=100 + i)
    db.commit()
    twitch_channels.record_request(db, "999999", now=_T0 - 1)  # drops the oldest, "1000"
    db.commit()
    assert _row(db, "1000") is None
    assert _notify(db) == twitch_channels.PENDING_CAP
    content = posts[0][1]["content"]
    assert "channel 1000," not in content and "channel 1000 " not in content
    assert content.startswith(f"{twitch_channels.PENDING_CAP} Twitch channels")
    assert "channel 1001" in content
    assert db.query(models.TwitchChannelApproval).filter(
        models.TwitchChannelApproval.notified_at == _T0).count() == twitch_channels.PENDING_CAP


# ---------------------------------------------------------------------------
# Security review follow-ups
# ---------------------------------------------------------------------------

def test_notify_pending_holds_no_transaction_while_sending(db, monkeypatch):
    """No write transaction (or unflushed change) is open while the message goes out, even
    when Helix filled in names; the names are stored."""
    import admin_notify
    import twitch_channels
    _discord(monkeypatch)
    monkeypatch.setattr(twitch_channels, "_lookup_names",
                        lambda ids: {"111": {"display_name": "Kanaliiga", "login": "kanaliiga"}})
    _add_row(db, "111")
    real_deliver = admin_notify.deliver
    seen = []

    def checking_deliver(*a, **kw):
        seen.append((db.in_transaction(), bool(db.dirty or db.new or db.deleted)))
        return real_deliver(*a, **kw)

    monkeypatch.setattr(admin_notify, "deliver", checking_deliver)
    assert _notify(db) == 1
    assert seen == [(False, False)]
    row = _row(db, "111")
    assert row.display_name == "Kanaliiga" and row.notified_at == _T0


def test_admin_notify_send_commits_before_network(db, monkeypatch):
    """admin_notify.send (the test route's path) ends the session's transaction before sending."""
    import admin_notify
    _discord(monkeypatch)
    seen = []
    real = admin_notify._send_discord
    monkeypatch.setattr(admin_notify, "_send_discord",
                        lambda url, text: seen.append(db.in_transaction()) or real(url, text))
    db.query(models.User).count()
    assert admin_notify.send("s", "t", db)["discord"] == "ok"
    assert seen == [False]


def test_notify_pending_backs_off_after_every_channel_failed(db, monkeypatch):
    """After a try where every channel failed, the next try waits NOTIFY_SPACING (not every 5-minute tick)."""
    import twitch_channels
    posts = _discord(monkeypatch, status=500)
    _add_row(db, "101")
    assert _notify(db) == 0
    for minutes in (5, 10, 29):
        assert _notify(db, now=_T0 + minutes * 60) == 0
    assert len(posts) == 1
    assert _notify(db, now=_T0 + twitch_channels.NOTIFY_SPACING) == 0
    assert len(posts) == 2
    # Nothing configured is not a failed try: no back-off.
    twitch_channels._reset_notify_backoff()
    monkeypatch.delenv("ADMIN_NOTIFY_DISCORD_WEBHOOK_URL")
    assert _notify(db, now=_T0 + 3600) == 0
    assert twitch_channels._notify_failed_at is None


@pytest.mark.parametrize("status", [301, 302, 307])
def test_admin_notify_discord_redirect_is_an_error_and_not_followed(db, monkeypatch, status):
    """Discord is posted with allow_redirects=False; a 3xx answer is `error: http 3xx` and marks nothing."""
    import admin_notify
    posts = _discord(monkeypatch, status=status)  # the recorder asserts allow_redirects=False
    assert admin_notify.send("s", "t", db)["discord"] == f"error: http {status}"
    _add_row(db, "101")
    assert _notify(db) == 0
    assert len(posts) == 2
    assert _row(db, "101").notified_at is None


def _smtp_mocks(monkeypatch, sendmail=None, raise_on_login=None):
    import smtplib
    from unittest.mock import MagicMock
    smtp = MagicMock()
    smtp.sendmail.return_value = sendmail or {}
    if raise_on_login is not None:
        smtp.login.side_effect = raise_on_login
    calls = []

    def factory(*a, **kw):
        calls.append((a, kw))
        cm = MagicMock()
        cm.__enter__ = lambda self: smtp
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    monkeypatch.setattr(smtplib, "SMTP", factory)
    monkeypatch.setattr(smtplib, "SMTP_SSL", factory)
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SMTP_USER", "login-user@example.net")
    monkeypatch.setenv("SMTP_PASSWORD", "pw")
    monkeypatch.setenv("SMTP_FROM", "sender@example.net")
    return calls


@pytest.mark.parametrize("ssl,tls", [("true", "true"), ("false", "true"), ("false", "false")])
def test_send_email_passes_a_timeout_to_every_smtp_connection(monkeypatch, ssl, tls):
    """smtplib.SMTP / SMTP_SSL get timeout=SMTP_TIMEOUT, so a hung server can't block the loop."""
    import email_utils
    calls = _smtp_mocks(monkeypatch)
    monkeypatch.setenv("SMTP_SSL", ssl)
    monkeypatch.setenv("SMTP_TLS", tls)
    assert email_utils.send_email("to-person@example.org", "Subj", "Body") is True
    assert calls == [(("smtp.example", 587), {"timeout": email_utils.SMTP_TIMEOUT})]
    assert 0 < email_utils.SMTP_TIMEOUT <= 30


def test_send_email_logs_no_address_on_success_refusal_failure_or_no_smtp(monkeypatch, caplog):
    """No email address (recipient, sender or login) reaches the logs on any path."""
    import smtplib
    import email_utils
    caplog.set_level(logging.DEBUG)
    monkeypatch.delenv("SMTP_SSL", raising=False)
    monkeypatch.delenv("SMTP_TLS", raising=False)
    to = "to-person@example.org"
    _smtp_mocks(monkeypatch)
    assert email_utils.send_email(to, "Subj ok", "Body") is True
    _smtp_mocks(monkeypatch, sendmail={to: (550, b"no such user " + to.encode())})
    assert email_utils.send_email(to, "Subj refused", "Body") is True
    _smtp_mocks(monkeypatch, raise_on_login=smtplib.SMTPRecipientsRefused({to: (550, b"x")}))
    assert email_utils.send_email(to, "Subj fail", "Body") is False
    _smtp_mocks(monkeypatch, raise_on_login=smtplib.SMTPAuthenticationError(535, b"bad login-user@example.net"))
    assert email_utils.send_email(to, "Subj auth", "Body") is False
    monkeypatch.delenv("SMTP_HOST")
    assert email_utils.send_email(to, "Subj none", "Body") is False
    messages = [r.getMessage() for r in caplog.records if r.name == "email_utils"]
    assert messages
    assert not any("@" in m for m in messages), messages
    text = "\n".join(messages)
    assert "Sent 'Subj ok'" in text and "refused 1 recipient" in text
    assert "SMTPRecipientsRefused" in text and "SMTPAuthenticationError (SMTP 535)" in text
    assert "would have sent: Subj none" in text
