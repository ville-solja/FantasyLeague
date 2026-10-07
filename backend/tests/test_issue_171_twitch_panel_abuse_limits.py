"""
Tests for plan-issue-171-twitch-panel-abuse-limits.md (resolves GitHub issue #171,
items 9 and 10 of hardening issue #163).

Four fixes to the Twitch panel: soft accounts must be
TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS old (default 24) to be in a drop pool, with
pool-size spike watching in the drop audit; heartbeats from logged-out (A...)
viewers are ignored and the route gets a per-viewer limit; team logos only from
LOGO_HOST_ALLOWLIST hosts (new backend/logo_hosts.py), at ingest and on output;
CORS allows only our own extension's origin. One class per user story, one stub
per acceptance criterion plus the failure path.

Developer notes
---------------

  Existing code these tests target
    - backend/twitch.py: `heartbeat` (no `request: Request` parameter and no
      limiter decorator today; slowapi needs `request`), `_active_pool`,
      `_execute_token_drop` (audit detail today is
      "channel=... match=... count=N winners=..."; no audit entry at all when the
      pool is empty), `_PRESENCE_TTL`, `_TWITCH_DROP_MAX` (module attribute,
      read from TWITCH_DROP_MAX at import), `GET /twitch/me` via `_me_state`
      (add `drops_from`), `RATE_LIMIT_TWITCH_ACTION`.
    - backend/soft_accounts.py: `SOFT = "twitch"`, `get_or_create_soft_account`
      sets `users.created_at = now`. Website accounts have account_type "full".
    - backend/rate_limit.py: `key_by_twitch_viewer_or_ip`, `limiter`
      (default_limits = RATE_LIMIT_GLOBAL is the "existing per-IP limit").
    - backend/ingest.py `_match_logo_url` (also turns "//host/..." into https).
    - Logo fields on output: routers/cards.py (`_build_roster_response`,
      `collection_for_user`, `draw_card`, `booster_deck_for_user` -> GET
      /deck/booster and GET /twitch/teams, `draw_booster`, `get_card`);
      routers/weekly_summary.py `_team_logo_url` / `_team_dict`.
    - routers/players.py GET /teams and GET /teams/{team_id} return NO logo field
      (decision 1: none is added); the parametrized output tests only assert that
      no unknown-host URL appears anywhere in those bodies.
    - backend/image.py `_load_team_logo_for_card` fetches `team_logo_url`
      server-side for GET /cards/{id}/image. Decision 2: it also goes through
      `safe_logo_url`, so the server never fetches from an unknown host
      (test_card_image_fetches_logo_only_from_allowlisted_host).
    - backend/main.py CORS: `allow_origin_regex=r"^https://[a-z0-9]+\\.ext-twitch\\.tv$"`
      plus `CORS_EXTRA_ORIGINS`, `allow_credentials=False`.

  CORS tests
    - The CORS middleware is built when `main` is imported, so each test must set
      or delete TWITCH_EXTENSION_CLIENT_ID (and CORS_EXTRA_ORIGINS) and then
      reload main. Reuse `_build_main_client(monkeypatch, env)` and `_preflight`
      from test_issue_136_security_audit_3.py; note `_build_main_client` does NOT
      delete TWITCH_EXTENSION_CLIENT_ID, so pass/delete it explicitly here (the
      developer shell may export a real one).
    - The "warning once at start-up" check: use caplog around the reload; the
      warning is emitted at import, so count records after a single reload.

  Reusable helpers / fixtures
    - From test_issue_157_twitch_extension_policy_compliance.py: `_viewer`,
      `_ANON`, `_CHANNEL`, `twitch_env`, `twitch_prod_env`, `_join`, `_present`,
      `_website_user`, `_seed_series_match`, `_set_mvp`, `_chat_recorder`,
      `_twitch_app`, `_shared_db`, `_signed`, `_js_function`, `_ext`. Import
      fixtures with `from tests.test_issue_157_... import twitch_env  # noqa: F401`
      (precedent: test_issue_160 imports helpers from test_issue_157).
    - From test_issue_140_twitch_chat_announcement_fix.py: `post_recorder`.
    - Rate-limit tests (lessons-learned 2026-10-06): use `_twitch_app(db)` with
      `twitch.limiter` (not `rate_limit.limiter`), reset() it and restore
      `enabled`; use `_shared_db()` for TestClient.
    - Soft accounts made by `_join` get `created_at = now`; age them by setting
      `user.created_at = now - 25 * 3600` before the drop.
    - Spike tests: seed earlier `AuditLog(action="twitch_token_drop",
      detail="channel=<ch> ... pool_size=N ...")` rows for the channel directly.
      Use `caplog.set_level(logging.WARNING, logger="twitch")`.

  Implementation decisions reflected here
    - Heartbeat is split like the other panel routes: plain `twitch.heartbeat(payload,
      db)` plus `heartbeat_route(request, ...)` carrying both limits (decision 3).
    - When only too-new soft accounts are present, a `twitch_token_drop` audit
      entry `count=0 pool_size=0 excluded_new=N` is written and nothing is claimed
      (decision 4, test_token_drop_audited_when_only_new_accounts_present).
    - Audit detail: `count=N pool_size=N excluded_new=N [pool_spike=true] winners=...`;
      the spike median skips entries without pool_size= and empty pools (decision 5).
    - safe_logo_url also refuses explicit ports, userinfo and non-https schemes
      (decision 7; extra cases in test_safe_logo_url_refuses_unsafe_urls).

  Existing tests this plan will break (update them in the same change)
    - test_issue_157_twitch_extension_policy_compliance.py drop tests that use
      brand-new soft accounts from `_join` (now excluded by the 24 h rule):
      `test_active_pool_includes_present_soft_and_linked_accounts`,
      `test_set_mvp_drops_to_soft_accounts_respecting_drop_max_and_one_per_match`,
      `test_mvp_chat_text_names_mvp_and_winner_count_without_usernames`
      (expects "2 viewers"); check also
      `test_set_mvp_with_no_joined_viewers_sets_mvp_and_chat_says_no_tokens` and
      `test_twitch_drops_disabled_sets_mvp_and_bonus_without_tokens`. Either age
      the accounts or set TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS=0. Tests in 139/140/
      135/test_proxy_trust_and_twitch_uniqueness.py use website ("full")
      accounts in the pool and should be unaffected; re-run them anyway, and any
      that assert the old "count=" audit detail.
    - test_issue_136_security_audit_3.py CORS tests preflight
      https://abc123.ext-twitch.tv with no client id set:
      `test_cors_preflight_from_ext_twitch_origin_allowed`,
      `test_cors_extra_origins_env_adds_origin`,
      `test_cors_allow_credentials_stays_false` need
      TWITCH_EXTENSION_CLIENT_ID=abc123 passed to `_build_main_client`.
      `test_cors_regex_rejects_lookalike_ext_twitch_origins` stays valid.
      `test_origin_check_twitch_paths_exempt` posts /twitch/heartbeat without a
      JWT (401); only asserts not 403, should still pass.
    - test_issue_51_weekly_summary.py and test_issue_100_weekly_report_fixes.py
      seed Team.logo_url = "https://example.com/<id>.png";
      `test_falls_back_to_db_logo_url_when_no_local_file` (51) expects that URL
      back and will now get None: switch the fixture to a Steam CDN host.
    - test_issue_157 `test_panel_sends_heartbeat_only_when_joined` (static) is
      unaffected.
    - test_issue_85_split_admin_router.py: bump the full-suite "N passed"
      tripwire for this file's tests (count the parametrized cases).
"""

import json
import logging
import pathlib
import re
import shutil
import subprocess
import time

import pytest

# Registers every existing table on Base before the conftest db fixture runs
# create_all. New modules (logo_hosts) are imported inside tests.
import models  # noqa: F401

from tests.test_issue_157_twitch_extension_policy_compliance import (  # noqa: F401
    twitch_env, twitch_prod_env)
from tests.test_issue_157_twitch_extension_policy_compliance import (
    _CHANNEL, _backdate, _chat_recorder, _ext, _join, _js_function, _present, _seed_series_match,
    _seed_world, _set_mvp, _shared_db, _signed, _twitch_app, _user_by_opaque, _viewer, _website_user)
from tests.test_issue_136_security_audit_3 import _build_main_client, _preflight

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

_DEFAULT_LOGO_HOSTS = (
    "steamcdn-a.akamaihd.net",
    "steamusercontent-a.akamaihd.net",
    "cdn.steamusercontent.com",
    "cdn.cloudflare.steamstatic.com",
    "shared.cloudflare.steamstatic.com",
)

_REFUSED_LOGO_URLS = (
    "http://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos/1.png",   # not https
    "https://evil.example/logo.png",                                       # unknown host
    "https://steamcdn-a.akamaihd.net.evil.example/logo.png",               # look-alike suffix
    "https://evilsteamcdn-a.akamaihd.net/logo.png",                        # look-alike prefix
    "https://steamcdn-a.akamaihd.net@evil.example/logo.png",               # userinfo trick
    "https://[::1/logo.png",                                               # malformed (urlparse ValueError)
    "javascript:alert(1)",
    "data:image/png;base64,AAAA",
    "",
    None,
    123,
)

# Every response that carries a team logo (plan Story 3). players_* currently
# return no logo field at all (see module docstring).
_LOGO_RESPONSES = (
    "deck_booster",          # GET /deck/booster (booster_deck_for_user)
    "twitch_teams",          # GET /twitch/teams (booster_deck_for_user)
    "card_collection",       # collection_for_user (GET /deck, /twitch/me collection)
    "roster",                # _build_roster_response (GET /roster/{user_id}, /twitch/me roster)
    "draw_card",             # POST /draw result team_logo_url
    "draw_booster",          # POST /draw/booster/{team_id} result team_logo_url
    "get_card",              # GET /cards/{card_id}
    "players_teams",         # GET /teams
    "players_team_detail",   # GET /teams/{team_id}
    "weekly_report",         # weekly_summary _team_dict fallback
)


_EVIL_LOGO = "https://evil.example/logo.png"
_STEAM_LOGO = "https://steamcdn-a.akamaihd.net/apps/dota2/images/team_logos/11.png"
_HOUR = 3600


def _no_min_age_env(monkeypatch):
    monkeypatch.delenv("TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS", raising=False)


def _drop_audits(db):
    from models import AuditLog
    return [a.detail for a in db.query(AuditLog).filter(AuditLog.action == "twitch_token_drop")
            .order_by(AuditLog.id).all()]


def _seed_drop_history(db, sizes, channel=_CHANNEL):
    """Earlier twitch_token_drop audit entries (oldest first) with the given pool sizes;
    None writes a pre-#171 entry with no pool_size=."""
    from models import AuditLog
    for i, size in enumerate(sizes):
        detail = (f"channel={channel} match={9000 + i} count=1 winners=Twitch viewer #1" if size is None
                  else f"channel={channel} match={9000 + i} count={min(size, 20)} pool_size={size}"
                       f" excluded_new=0 winners=")
        db.add(AuditLog(timestamp=int(time.time()) - 1000 + i, actor_id=None, actor_username="twitch",
                        action="twitch_token_drop", detail=detail))
    db.commit()


def _present_website_viewers(db, n, prefix="Uw"):
    for i in range(n):
        _website_user(db, f"{prefix.lower()}{i}", twitch_user_id=f"{prefix}{i}")
        _present(db, f"{prefix}{i}")


# ---------------------------------------------------------------------------
# Story 1 — New Accounts Wait a Day Before Joining Drops
# ---------------------------------------------------------------------------

class TestNewAccountsWaitBeforeDrops:

    def test_active_pool_includes_soft_account_older_than_min_age(self, db, monkeypatch):
        """AC: _active_pool includes a present soft account whose users.created_at is at least 24 h (default) before the drop."""
        import twitch
        _no_min_age_env(monkeypatch)
        _join(db, "Uold")
        _backdate(db, "Uold", hours=24)
        _present(db, "Uold")
        assert twitch._active_pool(db, _CHANNEL) == ["Uold"]

    def test_active_pool_excludes_soft_account_younger_than_min_age(self, db, monkeypatch):
        """AC: _active_pool leaves out a present soft account created less than TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS ago."""
        import twitch
        _no_min_age_env(monkeypatch)
        _join(db, "Unew")
        _backdate(db, "Unew", hours=23)
        _present(db, "Unew")
        assert twitch._active_pool(db, _CHANNEL) == []
        assert twitch._excluded_new_count(db, _CHANNEL) == 1

    def test_active_pool_always_includes_website_accounts(self, db, monkeypatch):
        """AC: website accounts (account_type != "twitch") are in the pool even when created a minute ago."""
        import twitch
        _no_min_age_env(monkeypatch)
        user = _website_user(db, "fresh", twitch_user_id="Uweb")
        user.created_at = int(time.time()) - 60
        db.commit()
        _present(db, "Uweb")
        assert user.account_type != "twitch"
        assert twitch._active_pool(db, _CHANNEL) == ["Uweb"]

    def test_active_pool_min_age_zero_turns_rule_off(self, db, monkeypatch):
        """AC: TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS=0 puts a brand-new soft account in the pool."""
        import twitch
        monkeypatch.setenv("TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS", "0")
        _join(db, "Unew")
        _present(db, "Unew")
        assert twitch._active_pool(db, _CHANNEL) == ["Unew"]

    def test_active_pool_custom_min_age_hours(self, db, monkeypatch):
        """AC: TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS=48 excludes a 30 h old soft account and includes a 49 h old one."""
        import twitch
        monkeypatch.setenv("TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS", "48")
        for oid, hours in (("U30", 30), ("U49", 49)):
            _join(db, oid)
            _backdate(db, oid, hours=hours)
            _present(db, oid)
        assert twitch._active_pool(db, _CHANNEL) == ["U49"]

    def test_active_pool_soft_account_with_null_created_at_counts_as_new(self, db, monkeypatch):
        """Plan Step 2: a soft account with created_at NULL is treated as new and left out."""
        import twitch
        _no_min_age_env(monkeypatch)
        _join(db, "Unull")
        _user_by_opaque(db, "Unull").created_at = None
        db.commit()
        _present(db, "Unull")
        assert twitch._active_pool(db, _CHANNEL) == []

    def test_twitch_me_returns_drops_from_for_new_soft_account(self, db, monkeypatch):
        """AC: GET /twitch/me returns drops_from = created_at + hours*3600 (Unix time) for a soft account younger than the minimum age."""
        import twitch
        _no_min_age_env(monkeypatch)
        _join(db, "Unew")
        user = _backdate(db, "Unew", hours=1)
        me = twitch.me(payload=_viewer("Unew"), db=db)
        assert me["drops_from"] == user.created_at + 24 * _HOUR
        assert me["drops_from"] > time.time()

    @pytest.mark.parametrize("case", ["old_soft_account", "website_account", "rule_off"])
    def test_twitch_me_drops_from_null_when_eligible(self, db, monkeypatch, case):
        """AC: drops_from is null for an old-enough soft account, a website account, and when the rule is off (0)."""
        import twitch
        _no_min_age_env(monkeypatch)
        if case == "old_soft_account":
            _join(db, "Uv")
            _backdate(db, "Uv", hours=25)
        elif case == "website_account":
            _website_user(db, "webby", twitch_user_id="Uv")
        else:
            monkeypatch.setenv("TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS", "0")
            _join(db, "Uv")
        me = twitch.me(payload=_viewer("Uv"), db=db)
        assert me["joined"] is True
        assert me["drops_from"] is None

    def test_panel_live_tab_shows_drops_start_line_when_drops_from_in_future(self):
        """AC: panel.js shows "Drops start for your account on <date>." in the Live tab while drops_from is in the future."""
        html = _ext("panel.html")
        live = html[html.index('id="view-live"'):html.index('id="view-cards"')]
        assert 'id="drops-start"' in live
        js = _ext("panel.js")
        assert "renderDropsStart()" in _js_function(js, "renderAll")
        text_fn = _js_function(js, "dropsStartText")
        assert '"Drops start for your account on "' in text_fn and "drops_from" in text_fn
        assert not re.search(r"[\U0001F300-\U0001FAFF☀-➿]", text_fn)
        node = shutil.which("node")
        if not node:
            return
        script = text_fn + """
var now = Date.now() / 1000;
console.log(JSON.stringify([
  dropsStartText({drops_from: Math.floor(now + 7200)}),
  dropsStartText({drops_from: Math.floor(now - 60)}),
  dropsStartText({drops_from: null}),
  dropsStartText(null)
]));"""
        out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True,
                                        check=True).stdout)
        assert out[0].startswith("Drops start for your account on ") and out[0].endswith(".")
        assert out[1:] == ["", "", ""]

    def test_token_drop_audit_includes_pool_size_and_excluded_new(self, db, twitch_env, monkeypatch):
        """AC: each twitch_token_drop audit detail includes pool_size=<n> and excluded_new=<count>."""
        _no_min_age_env(monkeypatch)
        _chat_recorder(monkeypatch)
        _seed_series_match(db)
        _present_website_viewers(db, 2)
        _join(db, "Unew")
        _present(db, "Unew")
        result = _set_mvp(db)
        assert result["token_drop"]["pool_size"] == 2
        [detail] = _drop_audits(db)
        assert f"channel={_CHANNEL} match=1001 count=2 pool_size=2 excluded_new=1 winners=" in detail
        assert "pool_spike" not in detail

    def test_token_drop_audited_when_only_new_accounts_present(self, db, twitch_env, monkeypatch):
        """Decision 4: when every present account is too new, a count=0 pool_size=0 excluded_new=N entry is written and no drop is claimed."""
        from models import TwitchTokenDrop
        _no_min_age_env(monkeypatch)
        chat = _chat_recorder(monkeypatch)
        _seed_series_match(db)
        for oid in ("Un1", "Un2"):
            _join(db, oid)
            _present(db, oid)
        result = _set_mvp(db)
        assert result["token_drop"]["winner_count"] == 0 and result["token_drop"]["pool_size"] == 0
        [detail] = _drop_audits(db)
        assert f"channel={_CHANNEL} match=1001 count=0 pool_size=0 excluded_new=2" in detail
        assert db.query(TwitchTokenDrop).count() == 0
        assert chat == ["Match MVP: Player102! No tokens were dropped: new accounts join drops 24 hours after joining."]

    def test_mvp_chat_text_only_new_accounts_uses_configured_hours(self, monkeypatch):
        """Follow-up: the "only new accounts" chat copy names the configured drop age; the old
        copy stays when nobody eligible or new was present."""
        import twitch
        monkeypatch.setenv("TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS", "48")
        assert twitch._mvp_chat_text("Savu", 0, True, only_new_accounts=True) == (
            "Match MVP: Savu! No tokens were dropped: new accounts join drops 48 hours after joining.")
        monkeypatch.setenv("TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS", "1")
        assert twitch._mvp_chat_text("Savu", 0, True, only_new_accounts=True).endswith(
            "new accounts join drops 1 hour after joining.")
        assert twitch._mvp_chat_text("Savu", 0, True) == (
            "Match MVP: Savu! No tokens were dropped: no joined viewers were watching.")
        assert twitch._mvp_chat_text("Savu", 0, False, drops_enabled=False, only_new_accounts=True) == "Match MVP: Savu!"

    def test_token_drop_pool_spike_logs_warning_and_audits_flag(self, db, twitch_env, monkeypatch, caplog):
        """AC: pool_size more than 3x the median of the channel's last ten drops (>= 5 earlier entries) logs a warning and adds pool_spike=true."""
        _chat_recorder(monkeypatch)
        _seed_series_match(db)
        _seed_drop_history(db, [1, 1, 1, 1, 1])
        _present_website_viewers(db, 4)
        caplog.set_level(logging.WARNING, logger="twitch")
        _set_mvp(db)
        detail = _drop_audits(db)[-1]
        assert "pool_size=4" in detail and "pool_spike=true" in detail
        assert any("pool spike" in r.getMessage() and r.levelno == logging.WARNING
                   for r in caplog.records if r.name == "twitch")

    def test_token_drop_no_spike_when_pool_at_most_three_times_median(self, db, twitch_env, monkeypatch, caplog):
        """AC: a pool exactly 3x the median is not a spike (no warning, no pool_spike=true)."""
        _chat_recorder(monkeypatch)
        _seed_series_match(db)
        _seed_drop_history(db, [1, 1, 1, 1, 1])
        _present_website_viewers(db, 3)
        caplog.set_level(logging.WARNING, logger="twitch")
        _set_mvp(db)
        detail = _drop_audits(db)[-1]
        assert "pool_size=3" in detail and "pool_spike" not in detail
        assert not any("pool spike" in r.getMessage() for r in caplog.records)

    def test_token_drop_no_spike_with_fewer_than_five_earlier_entries(self, db, twitch_env, monkeypatch, caplog):
        """AC: with only four earlier entries for the channel, even a huge pool is not flagged."""
        _chat_recorder(monkeypatch)
        _seed_series_match(db)
        _seed_drop_history(db, [1, 1, 1, 1])
        _present_website_viewers(db, 10)
        caplog.set_level(logging.WARNING, logger="twitch")
        _set_mvp(db)
        detail = _drop_audits(db)[-1]
        assert "pool_size=10" in detail and "pool_spike" not in detail
        assert not any("pool spike" in r.getMessage() for r in caplog.records)

    def test_token_drop_spike_median_skips_entries_without_pool_size_and_other_channels(self, db, twitch_env, monkeypatch):
        """Plan Step 2: audit entries without pool_size= (pre-change) and other channels' entries are not counted in the median."""
        _chat_recorder(monkeypatch)
        _seed_series_match(db)
        _seed_drop_history(db, [1, 1, 1, 1, 1])
        # Newer entries that must be ignored: pre-#171 ones (no pool_size=) for this
        # channel, and big pools on other channels (one sharing this id as a prefix).
        _seed_drop_history(db, [None] * 10)
        _seed_drop_history(db, [100] * 10, channel="other_channel")
        _seed_drop_history(db, [100] * 10, channel=_CHANNEL + "2")
        _present_website_viewers(db, 4)
        _set_mvp(db)
        assert "pool_spike=true" in _drop_audits(db)[-1]

    def test_set_mvp_new_soft_account_gets_no_token_and_chat_counts_only_eligible(self, db, twitch_env, monkeypatch):
        """Failure path: a soft account created 1 h before the drop gets no token; eligible viewers still win and the chat count reflects only them."""
        _no_min_age_env(monkeypatch)
        chat = _chat_recorder(monkeypatch)
        _seed_series_match(db)
        for oid, hours in (("Uold1", 25), ("Uold2", 48), ("Unew", 1)):
            _join(db, oid)
            _backdate(db, oid, hours=hours)
            _present(db, oid)
        result = _set_mvp(db)
        assert result["token_drop"]["winner_count"] == 2 and result["token_drop"]["pool_size"] == 2
        db.expire_all()
        assert _user_by_opaque(db, "Unew").tokens == 5
        assert _user_by_opaque(db, "Uold1").tokens == 6 and _user_by_opaque(db, "Uold2").tokens == 6
        assert chat == ["Match MVP: Player102! 2 viewers received a token."]


# ---------------------------------------------------------------------------
# Story 2 — Logged-Out Viewers Don't Fill the Presence Table
# ---------------------------------------------------------------------------

class TestLoggedOutHeartbeatsIgnored:

    @pytest.mark.parametrize("opaque_id", ["Aanon123", "", "Xweird1"])
    def test_heartbeat_non_u_id_returns_ok_without_writing(self, db, opaque_id):
        """AC: POST /twitch/heartbeat with an opaque id not starting with U returns {"ok": true} and writes no twitch_presence row."""
        import twitch
        from models import TwitchPresence
        assert twitch.heartbeat(_viewer(opaque_id), db) == {"ok": True}
        assert db.query(TwitchPresence).count() == 0

    def test_heartbeat_logged_in_viewer_upserts_presence(self, db):
        """AC: a U... heartbeat inserts its twitch_presence row, and a second one updates seen_at/channel_id."""
        import twitch
        from models import TwitchPresence
        assert twitch.heartbeat(_viewer("Uviewer"), db) == {"ok": True}
        row = db.query(TwitchPresence).one()
        assert row.twitch_user_id == "Uviewer" and row.channel_id == _CHANNEL
        row.seen_at = 1
        db.commit()
        twitch.heartbeat({**_viewer("Uviewer"), "channel_id": "other_channel"}, db)
        db.expire_all()
        row = db.query(TwitchPresence).one()
        assert row.channel_id == "other_channel" and row.seen_at >= int(time.time()) - 5

    def test_heartbeat_rate_limited_per_viewer(self, twitch_prod_env, monkeypatch):
        """AC: the route is limited per viewer (key_by_twitch_viewer_or_ip, RATE_LIMIT_TWITCH_ACTION): one viewer over the limit gets 429, another viewer on the same IP does not."""
        from fastapi.testclient import TestClient
        from limits import parse
        import twitch
        db = _shared_db()
        was_enabled = twitch.limiter.enabled
        twitch.limiter.enabled = True
        twitch.limiter.reset()
        try:
            client = TestClient(_twitch_app(db))
            per_viewer = parse(twitch.RATE_LIMIT_TWITCH_ACTION).amount
            assert per_viewer < parse(twitch.RATE_LIMIT_TWITCH_JOIN_IP).amount
            statuses = [client.post("/twitch/heartbeat", headers={"Authorization": _signed("Uone")}).status_code
                        for _ in range(per_viewer + 1)]
            assert statuses[:per_viewer] == [200] * per_viewer
            assert statuses[-1] == 429
            assert client.post("/twitch/heartbeat", headers={"Authorization": _signed("Utwo")}).status_code == 200
        finally:
            twitch.limiter.reset()
            twitch.limiter.enabled = was_enabled
            db.close()

    def test_heartbeat_route_declares_per_viewer_and_per_ip_limits(self):
        """AC: heartbeat is decorated with limiter.limit(RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip) and keeps the per-IP limit."""
        import inspect
        import twitch
        src = inspect.getsource(twitch)
        m = re.search(r'@router\.post\("/heartbeat"\)\n((?:@limiter\.limit\([^\n]*\)\n)+)def heartbeat_route\(\s*request: Request', src)
        assert m, "heartbeat route decorators not found"
        decorators = m.group(1)
        assert "@limiter.limit(RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)" in decorators
        assert "@limiter.limit(RATE_LIMIT_TWITCH_JOIN_IP)" in decorators

    def test_heartbeat_anonymous_leaves_presence_table_unchanged(self, db):
        """Failure path: an A... heartbeat leaves existing twitch_presence rows (count and seen_at) unchanged, while a U... heartbeat still upserts."""
        import twitch
        from models import TwitchPresence
        _present(db, "Uexisting", seen_at=1000)
        twitch.heartbeat(_viewer("Aanon123"), db)
        twitch.heartbeat(_viewer("Aexisting"), db)
        db.expire_all()
        rows = db.query(TwitchPresence).all()
        assert [(r.twitch_user_id, r.seen_at) for r in rows] == [("Uexisting", 1000)]
        twitch.heartbeat(_viewer("Uexisting"), db)
        db.expire_all()
        assert db.query(TwitchPresence).one().seen_at > 1000


# ---------------------------------------------------------------------------
# Story 3 — Team Logos Only From Known Hosts
# ---------------------------------------------------------------------------

def _logo_world(db, logo_url):
    """Teams 11/12 (both with `logo_url`), their players and stats, a website user with
    tokens, one card for player 101 and draw weights."""
    from models import Card, Team, User
    _seed_world(db)
    for tid in (11, 12):
        db.get(Team, tid).logo_url = logo_url
    user = User(username="logo_user", email="logo@example.com", password_hash="x", tokens=50,
                created_at=int(time.time()))
    db.add(user)
    db.commit()
    card = Card(player_id=101, owner_id=user.id, card_type="common", is_active=True, generation=1,
                slot_index=0)
    db.add(card)
    db.commit()
    return user, card


def _logo_response(db, monkeypatch, tmp_path, response, user, card):
    """The response body (and the logo values in it) for one entry of _LOGO_RESPONSES."""
    import routers.cards as cards
    import routers.players as players
    import routers.weekly_summary as weekly_summary
    from models import Team
    current = {"user_id": user.id, "username": user.username, "is_admin": False}
    if response == "deck_booster":
        body = cards.booster_deck_for_user(db, None)
        return body, [t["logo_url"] for t in body]
    if response == "twitch_teams":
        import twitch
        from models import User
        u = db.get(User, user.id)
        u.twitch_user_id = "Ulogo"
        db.commit()
        body = twitch.teams(payload=_viewer("Ulogo"), db=db)
        return body, [t["logo_url"] for t in body["teams"]]
    if response == "card_collection":
        body = cards.collection_for_user(db, user.id)
        return body, [c["team_logo_url"] for c in body]
    if response == "roster":
        body = cards._build_roster_response(db, user.id, None)
        return body, [c["team_logo_url"] for c in body["active"] + body["bench"]]
    if response == "draw_card":
        body = cards.draw_card(db=db, current_user=current)
        return body, [body["team_logo_url"]]
    if response == "draw_booster":
        body = cards.draw_booster(team_id=11, db=db, current_user=current)
        return body, [body["team_logo_url"]]
    if response == "get_card":
        body = cards.get_card(card.id, db=db, current_user=current)
        return body, [body["team_logo_url"]]
    if response == "players_teams":
        return players.list_teams(db=db), []
    if response == "players_team_detail":
        return players.get_team(11, db=db), []
    if response == "weekly_report":
        monkeypatch.setattr(weekly_summary, "_LOGO_DIR", str(tmp_path / "no_local_logos"))
        body = weekly_summary._team_dict(db.get(Team, 11))
        return body, [body["logo_url"]]
    raise AssertionError(response)


class TestTeamLogosOnlyFromKnownHosts:

    @pytest.mark.parametrize("host", _DEFAULT_LOGO_HOSTS)
    def test_safe_logo_url_accepts_default_hosts_over_https(self, monkeypatch, host):
        """AC: with LOGO_HOST_ALLOWLIST unset, safe_logo_url returns an https URL on each default Steam CDN host (stripped)."""
        from logo_hosts import DEFAULT_LOGO_HOSTS, safe_logo_url
        monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
        assert tuple(DEFAULT_LOGO_HOSTS) == _DEFAULT_LOGO_HOSTS
        url = f"https://{host}/apps/dota2/images/team_logos/1.png"
        assert safe_logo_url(f"  {url}\n") == url

    @pytest.mark.parametrize("url", _REFUSED_LOGO_URLS + (
        "https://steamcdn-a.akamaihd.net:8443/logo.png",        # explicit port
        "https://steamcdn-a.akamaihd.net:443/logo.png",         # explicit port, even the default
        "https://user:pw@steamcdn-a.akamaihd.net/logo.png",     # userinfo
        "ftp://steamcdn-a.akamaihd.net/logo.png",               # non-https scheme
        "//steamcdn-a.akamaihd.net/logo.png",                   # protocol-relative (ingest normalises it)
    ))
    def test_safe_logo_url_refuses_unsafe_urls(self, monkeypatch, url):
        """AC: safe_logo_url returns None for http, unknown hosts, look-alike hosts, malformed URLs and non-strings
        (decision 7: also explicit ports, userinfo and non-https schemes)."""
        from logo_hosts import safe_logo_url
        monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
        assert safe_logo_url(url) is None

    def test_safe_logo_url_host_compared_case_insensitively(self, monkeypatch):
        """AC: https://SteamCDN-A.Akamaihd.NET/x.png passes, and LOGO_HOST_ALLOWLIST entries in upper case match lower-case hosts."""
        from logo_hosts import safe_logo_url
        monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
        assert safe_logo_url("https://SteamCDN-A.Akamaihd.NET/x.png") == "https://SteamCDN-A.Akamaihd.NET/x.png"
        monkeypatch.setenv("LOGO_HOST_ALLOWLIST", "IMG.EXAMPLE")
        assert safe_logo_url("https://img.example/x.png") == "https://img.example/x.png"

    def test_safe_logo_url_reads_allowlist_env_at_call_time(self, monkeypatch):
        """AC: LOGO_HOST_ALLOWLIST=" img.example , cdn.test" (comma-separated) replaces the defaults and is read on each call."""
        from logo_hosts import safe_logo_url
        monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
        assert safe_logo_url("https://img.example/a.png") is None
        monkeypatch.setenv("LOGO_HOST_ALLOWLIST", " img.example , cdn.test")
        assert safe_logo_url("https://img.example/a.png") == "https://img.example/a.png"
        assert safe_logo_url("https://cdn.test/b.png") == "https://cdn.test/b.png"
        assert safe_logo_url("https://steamcdn-a.akamaihd.net/c.png") is None
        monkeypatch.delenv("LOGO_HOST_ALLOWLIST")
        assert safe_logo_url("https://img.example/a.png") is None

    def test_safe_logo_url_empty_allowlist_falls_back_to_defaults(self, monkeypatch):
        """AC: an empty (or whitespace/commas only) LOGO_HOST_ALLOWLIST falls back to the default Steam CDN list."""
        from logo_hosts import safe_logo_url
        for value in ("", "   ", " , ,"):
            monkeypatch.setenv("LOGO_HOST_ALLOWLIST", value)
            assert safe_logo_url(_STEAM_LOGO) == _STEAM_LOGO, repr(value)
            assert safe_logo_url(_EVIL_LOGO) is None

    def test_match_logo_url_stores_only_allowlisted_urls(self, monkeypatch):
        """AC: ingest._match_logo_url returns allowlisted https URLs (including //host protocol-relative ones) and None otherwise."""
        import ingest
        monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
        assert ingest._match_logo_url(_STEAM_LOGO) == _STEAM_LOGO
        assert ingest._match_logo_url(" " + _STEAM_LOGO + " ") == _STEAM_LOGO
        assert ingest._match_logo_url("//steamcdn-a.akamaihd.net/x.png") == "https://steamcdn-a.akamaihd.net/x.png"
        for bad in (_EVIL_LOGO, "//evil.example/x.png", "http://steamcdn-a.akamaihd.net/x.png", "", None, 5):
            assert ingest._match_logo_url(bad) is None, bad

    def test_ingest_unknown_host_logo_stores_nothing(self, db, monkeypatch):
        """Failure path: ingesting a match whose radiant_logo is https://evil.example/logo.png leaves teams.logo_url NULL."""
        import ingest
        from models import Team
        monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
        payload = {"match_id": 7100, "duration": 2400, "start_time": int(time.time()) - 7200,
                   "radiant_win": True, "radiant_team_id": 31, "dire_team_id": 32,
                   "radiant_name": "Evil Logos", "dire_name": "Steam Logos",
                   "radiant_logo": _EVIL_LOGO, "dire_logo": _STEAM_LOGO,
                   "players": [], "picks_bans": [], "version": 21}
        monkeypatch.setattr(ingest, "opendota_get_json", lambda url, label=None: payload)
        monkeypatch.setattr(ingest, "request_parse", lambda match_id: True)
        ingest.ingest_match(db, 7100, 1, set(), set(), {})
        db.expire_all()
        assert db.get(Team, 31).logo_url is None
        assert db.get(Team, 32).logo_url == _STEAM_LOGO

    @pytest.mark.parametrize("response", _LOGO_RESPONSES)
    def test_response_returns_null_for_stored_unknown_host_logo(self, db, monkeypatch, tmp_path, response):
        """Failure path: a team whose stored logo_url is https://evil.example/logo.png comes back with logo_url/team_logo_url null (no evil.example anywhere in the body)."""
        monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
        user, card = _logo_world(db, _EVIL_LOGO)
        body, logos = _logo_response(db, monkeypatch, tmp_path, response, user, card)
        assert "evil.example" not in json.dumps(body, default=str)
        if not response.startswith("players_"):
            assert logos and all(v is None for v in logos), logos

    @pytest.mark.parametrize("response", [r for r in _LOGO_RESPONSES if not r.startswith("players_")])
    def test_response_keeps_allowlisted_logo(self, db, monkeypatch, tmp_path, response):
        """AC: a stored Steam CDN logo_url is returned unchanged by every logo-carrying response."""
        monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
        user, card = _logo_world(db, _STEAM_LOGO)
        _, logos = _logo_response(db, monkeypatch, tmp_path, response, user, card)
        assert logos and all(v == _STEAM_LOGO for v in logos), logos

    def test_weekly_report_prefers_local_asset_logo(self, db, tmp_path, monkeypatch):
        """AC: the local /assets/dotabuff_league_logos/ PNG stays preferred over any logo_url, allowlisted or not."""
        import routers.weekly_summary as weekly_summary
        from models import Team
        logo_dir = tmp_path / "dotabuff_league_logos"
        logo_dir.mkdir()
        (logo_dir / "Local_Team.png").write_bytes(b"png")
        monkeypatch.setattr(weekly_summary, "_LOGO_DIR", str(logo_dir))
        for tid, stored in ((41, _STEAM_LOGO), (42, _EVIL_LOGO)):
            team = Team(id=tid, name="Local Team", logo_url=stored)
            db.add(team)
            db.commit()
            assert weekly_summary._team_dict(team)["logo_url"] == "/assets/dotabuff_league_logos/Local_Team.png"
            db.delete(team)
            db.commit()

    def test_card_image_fetches_logo_only_from_allowlisted_host(self, monkeypatch):
        """Decision 2: GET /cards/{id}/image (image._load_team_logo_for_card) never fetches a logo from an unknown host."""
        import image
        monkeypatch.delenv("LOGO_HOST_ALLOWLIST", raising=False)
        fetched = []
        monkeypatch.setattr(image, "_fetch_pil_image", lambda url, d: fetched.append(url) or None)
        monkeypatch.setattr(image, "resolve_local_team_logo_path", lambda logo_dir, name: None)
        for bad in (_EVIL_LOGO, "//evil.example/x.png", "http://steamcdn-a.akamaihd.net/x.png",
                    "https://169.254.169.254/latest/meta-data", "https://steamcdn-a.akamaihd.net:8080/x.png"):
            assert image._load_team_logo_for_card("No Team", bad, 104) is None
        assert fetched == []
        image._load_team_logo_for_card("No Team", _STEAM_LOGO, 104)
        image._load_team_logo_for_card("No Team", "//steamcdn-a.akamaihd.net/y.png", 104)
        assert fetched == [_STEAM_LOGO, "https://steamcdn-a.akamaihd.net/y.png"]

    def test_frontend_and_panel_show_monogram_when_logo_null(self):
        """AC: the website card/booster rendering and panel.js fall back to the team monogram when the logo is null.
        The website's booster tile shows a blank circle placeholder (its existing fallback) and the
        Weekly Report shows only the team name; the panel shows the monogram."""
        js = _ext("panel.js")
        teams = _js_function(js, "renderTeams")
        assert re.search(r"if \(t\.logo_url && /\^https:\\/\\//\.test\(t\.logo_url\)\)", teams)
        assert "btn.appendChild(monogram(t.team_name))" in teams
        assert "img.replaceWith(monogram(t.team_name))" in teams
        cards_js = (REPO_ROOT / "frontend" / "app-cards.js").read_text(encoding="utf-8")
        m = re.search(r"const logo = t\.logo_url\s*\?\s*`<img[^`]*`\s*:\s*`(<div[^`]*></div>)`", cards_js)
        assert m and "border-radius:50%" in m.group(1)
        weekly_js = (REPO_ROOT / "frontend" / "app-weekly-summary.js").read_text(encoding="utf-8")
        team_html = _js_function(weekly_js, "_weeklySummaryTeamHtml")
        assert "const logo = logoUrl" in team_html and "teamLink(team.id" in team_html


# ---------------------------------------------------------------------------
# Story 4 — Only Our Extension Can Call the Backend Cross-Origin
# ---------------------------------------------------------------------------

def _acao(client, origin):
    return _preflight(client, origin).headers.get("access-control-allow-origin")


class TestOnlyOurExtensionCors:

    def test_cors_preflight_from_our_client_id_origin_allowed(self, monkeypatch):
        """AC: with TWITCH_EXTENSION_CLIENT_ID=abc123, a preflight from https://abc123.ext-twitch.tv gets Access-Control-Allow-Origin."""
        client = _build_main_client(monkeypatch, {"TWITCH_EXTENSION_CLIENT_ID": "abc123"})
        resp = _preflight(client, "https://abc123.ext-twitch.tv")
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "https://abc123.ext-twitch.tv"

    @pytest.mark.parametrize("origin", [
        "https://other999.ext-twitch.tv",
        "https://abc1234.ext-twitch.tv",
        "https://xabc123.ext-twitch.tv",
        "http://abc123.ext-twitch.tv",
    ])
    def test_cors_preflight_from_other_extension_origin_refused(self, monkeypatch, origin):
        """Failure path: with TWITCH_EXTENSION_CLIENT_ID=abc123, another extension's origin gets no Access-Control-Allow-Origin."""
        client = _build_main_client(monkeypatch, {"TWITCH_EXTENSION_CLIENT_ID": "abc123"})
        assert _acao(client, origin) is None

    def test_cors_client_id_is_regex_escaped(self, monkeypatch):
        """AC: a client id containing regex metacharacters (e.g. "abc.123") matches only literally: https://abcx123.ext-twitch.tv is refused."""
        client = _build_main_client(monkeypatch, {"TWITCH_EXTENSION_CLIENT_ID": "abc.123"})
        assert _acao(client, "https://abcx123.ext-twitch.tv") is None
        assert _acao(client, "https://abc.123.ext-twitch.tv") == "https://abc.123.ext-twitch.tv"
        import main
        assert main._ext_origin_regex == r"^https://abc\.123\.ext-twitch\.tv$"

    def test_cors_without_client_id_allows_no_ext_twitch_origin(self, monkeypatch):
        """AC: with TWITCH_EXTENSION_CLIENT_ID unset, no *.ext-twitch.tv origin gets Access-Control-Allow-Origin."""
        client = _build_main_client(monkeypatch)
        for origin in ("https://abc123.ext-twitch.tv", "https://other999.ext-twitch.tv"):
            assert _acao(client, origin) is None, origin

    def test_cors_without_client_id_logs_warning_once_at_startup(self, monkeypatch, caplog):
        """AC: importing main without TWITCH_EXTENSION_CLIENT_ID logs exactly one warning about no extension origin being allowed."""
        caplog.set_level(logging.WARNING)
        caplog.clear()
        _build_main_client(monkeypatch)
        hits = [r for r in caplog.records if "TWITCH_EXTENSION_CLIENT_ID unset" in r.getMessage()]
        assert len(hits) == 1 and hits[0].levelno == logging.WARNING
        caplog.clear()
        _build_main_client(monkeypatch, {"TWITCH_EXTENSION_CLIENT_ID": "abc123"})
        assert not [r for r in caplog.records if "TWITCH_EXTENSION_CLIENT_ID unset" in r.getMessage()]

    def test_cors_extra_origins_still_work_without_client_id(self, monkeypatch):
        """AC: CORS_EXTRA_ORIGINS=http://localhost:8080 is allowed whether or not TWITCH_EXTENSION_CLIENT_ID is set."""
        for env in ({}, {"TWITCH_EXTENSION_CLIENT_ID": "abc123"}):
            client = _build_main_client(monkeypatch, {"CORS_EXTRA_ORIGINS": "http://localhost:8080", **env})
            assert _acao(client, "http://localhost:8080") == "http://localhost:8080", env

    def test_cors_allow_credentials_stays_false(self, monkeypatch):
        """AC: an allowed preflight from our extension origin carries no Access-Control-Allow-Credentials: true."""
        client = _build_main_client(monkeypatch, {"TWITCH_EXTENSION_CLIENT_ID": "abc123"})
        resp = _preflight(client, "https://abc123.ext-twitch.tv")
        assert resp.headers.get("access-control-allow-origin") == "https://abc123.ext-twitch.tv"
        assert resp.headers.get("access-control-allow-credentials") != "true"

    def test_csp_frame_ancestors_unchanged(self):
        """Plan Step 4: the CSP frame-ancestors still lists https://*.ext-twitch.tv (embedding, not CORS)."""
        src = (REPO_ROOT / "backend" / "main.py").read_text(encoding="utf-8")
        assert "\"frame-ancestors 'self' https://www.twitch.tv https://*.ext-twitch.tv\"" in src
