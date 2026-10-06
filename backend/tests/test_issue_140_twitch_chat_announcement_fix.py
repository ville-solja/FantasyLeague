"""
Tests for plan-issue-140-twitch-chat-announcement-fix.md (resolves GitHub issue #140).

`_post_chat_message` must send the three fields Twitch requires
(`text`, `extension_id`, `extension_version`), skip with one warning when
`TWITCH_EXTENSION_VERSION` is unset, keep the announcement within 280
characters, and log non-2xx chat/PubSub responses without the JWT. Chat stays
best-effort: `POST /twitch/mvp` never fails because of it.

Testing approach:

  Direct helper calls (`twitch._post_chat_message`, `twitch._pubsub_broadcast`)
    - Use the `twitch_prod_env` fixture below: a valid base64
      TWITCH_EXTENSION_SECRET, TWITCH_EXTENSION_CLIENT_ID,
      TWITCH_EXTENSION_VERSION, and TWITCH_LOCAL_DEV unset.
    - Patch `twitch._requests.post` with the `post_recorder` fixture. It
      records (url, kwargs) per call and returns a `_FakeResponse`
      (status_code / ok / text). No network.
    - Decode the Bearer JWT from the recorded headers with
      `pyjwt.decode(token, _SECRET_BYTES, algorithms=["HS256"])`.
    - Use `caplog.set_level(logging.WARNING, logger="twitch")` for log
      assertions.
    - The "warn once" flag is module-level: reset it at the start of the test
      (e.g. `monkeypatch.setattr(twitch, "<flag name>", False)` with whatever
      name the implementation picks) so test order does not matter.

  Message text (`twitch._mvp_chat_text`)
    - Call the helper directly:
      `_mvp_chat_text(player_name, winner_count, pool_empty)` (a count, not
      usernames, since issue #157).

  Endpoint (`twitch.set_mvp`)
    - Call the router function directly (precedent: Story 1 of
      test_issue_135_security_review_fixes.py, reused in
      test_issue_139_early_mvp_selection.py): `_seed_match`, `_add_viewer`,
      `_call_set_mvp`. Match 1001 (teams 11 vs 12, one hour ago) is in the
      series window. Use `twitch_prod_env` + `post_recorder` so the real chat
      and PubSub helpers run against the patched `_requests.post`. For the
      message length check, patch `twitch._post_chat_message` with a recorder
      instead. Do NOT import or reload `main`.
"""

import base64
import logging
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import models  # noqa: F401, E402  (registers every table before create_all)

# ===========================================================================
# Shared helpers
# ===========================================================================

_SECRET_BYTES = b"issue-140-test-extension-secret!"
_SECRET_B64 = base64.b64encode(_SECRET_BYTES).decode()
_CLIENT_ID = "test-client-id-140"
_VERSION = "1.1.7"
_CHANNEL = "test_channel"
_BROADCASTER = {"channel_id": _CHANNEL, "role": "broadcaster", "opaque_user_id": "Utest"}


class _FakeResponse:
    def __init__(self, status_code=204, text=""):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = text


@pytest.fixture
def twitch_prod_env(monkeypatch):
    """Real (non-dev) Twitch code path with valid extension credentials."""
    monkeypatch.delenv("TWITCH_LOCAL_DEV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)
    monkeypatch.setenv("TWITCH_EXTENSION_SECRET", _SECRET_B64)
    monkeypatch.setenv("TWITCH_EXTENSION_CLIENT_ID", _CLIENT_ID)
    monkeypatch.setenv("TWITCH_EXTENSION_VERSION", _VERSION)


@pytest.fixture
def post_recorder(monkeypatch):
    """Patch twitch._requests.post; set `.response` or `.exc` to control the outcome."""
    import twitch

    class _Recorder:
        def __init__(self):
            self.calls = []
            self.response = _FakeResponse()
            self.exc = None

        def __call__(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if self.exc:
                raise self.exc
            return self.response

    rec = _Recorder()
    monkeypatch.setattr(twitch._requests, "post", rec)
    return rec


def _seed_match(db, match_id, team1_id, team2_id, start_time, player_ids=(), with_stats=True):
    from models import Match, Player, PlayerMatchStats, Team
    for tid in (team1_id, team2_id):
        if not db.get(Team, tid):
            db.add(Team(id=tid, name=f"Team{tid}"))
    db.add(Match(match_id=match_id, radiant_team_id=team1_id, dire_team_id=team2_id,
                 start_time=start_time, radiant_win=True))
    if with_stats:
        for i, pid in enumerate(player_ids):
            if not db.get(Player, pid):
                db.add(Player(id=pid, name=f"Player{pid}"))
            db.add(PlayerMatchStats(player_id=pid, match_id=match_id,
                                    team_id=team1_id if i % 2 == 0 else team2_id,
                                    fantasy_points=10.0, kills=3, is_mvp=False))
    db.commit()


def _add_viewer(db):
    from models import TwitchPresence, User
    db.add(User(id=50, username="viewer", tokens=0, twitch_user_id="Uviewer"))
    db.add(TwitchPresence(twitch_user_id="Uviewer", channel_id=_CHANNEL, seen_at=int(time.time())))
    db.commit()


def _call_set_mvp(db, match_id, player_id, payload=_BROADCASTER):
    import twitch
    return twitch.set_mvp(twitch.MVPBody(match_id=match_id, player_id=player_id),
                          payload=dict(payload), db=db)


# ===========================================================================
# Story 1 — MVP Announcement Reaches Chat
# ===========================================================================

def test_post_chat_message_sends_text_extension_id_and_version(twitch_prod_env, post_recorder):
    """AC: _post_chat_message sends {"text", "extension_id", "extension_version"} from
    TWITCH_EXTENSION_CLIENT_ID and TWITCH_EXTENSION_VERSION.

    Approach: call twitch._post_chat_message(_CHANNEL, "hello"); assert exactly one
    call to .../helix/extensions/chat and json == {"text": "hello",
    "extension_id": _CLIENT_ID, "extension_version": _VERSION}.
    """
    import twitch
    twitch._post_chat_message(_CHANNEL, "hello")
    assert len(post_recorder.calls) == 1
    url, kwargs = post_recorder.calls[0]
    assert url.startswith("https://api.twitch.tv/helix/extensions/chat")
    assert kwargs["json"] == {
        "text": "hello",
        "extension_id": _CLIENT_ID,
        "extension_version": _VERSION,
    }


def test_post_chat_message_keeps_broadcaster_id_and_external_jwt(twitch_prod_env, post_recorder):
    """AC: the request keeps broadcaster_id as a query parameter and a JWT with
    role "external", user_id and channel_id equal to the broadcaster's channel.

    Approach: parse the recorded URL's query string (broadcaster_id == _CHANNEL);
    decode the Bearer token from headers["Authorization"] with _SECRET_BYTES and
    assert role/user_id/channel_id; assert headers["Client-Id"] == _CLIENT_ID.
    """
    from urllib.parse import parse_qs, urlparse
    import jwt as pyjwt
    import twitch
    twitch._post_chat_message(_CHANNEL, "hello")
    url, kwargs = post_recorder.calls[0]
    assert parse_qs(urlparse(url).query) == {"broadcaster_id": [_CHANNEL]}
    headers = kwargs["headers"]
    assert headers["Client-Id"] == _CLIENT_ID
    assert headers["Authorization"].startswith("Bearer ")
    claims = pyjwt.decode(headers["Authorization"].removeprefix("Bearer "),
                          _SECRET_BYTES, algorithms=["HS256"])
    assert claims["role"] == "external"
    assert claims["user_id"] == _CHANNEL
    assert claims["channel_id"] == _CHANNEL


def test_post_chat_message_without_version_skips_and_warns_once(twitch_prod_env, post_recorder, monkeypatch, caplog):
    """AC: when TWITCH_EXTENSION_VERSION is unset, no request is sent and a warning
    naming the missing setting is logged once per process.

    Approach: delenv TWITCH_EXTENSION_VERSION (also try "  " whitespace-only), reset
    the module's warn-once flag, call _post_chat_message twice; assert
    post_recorder.calls == [] and exactly one WARNING record containing
    "TWITCH_EXTENSION_VERSION".
    """
    import twitch
    caplog.set_level(logging.WARNING, logger="twitch")
    for unset in (None, "  "):
        monkeypatch.setattr(twitch, "_chat_version_warned", False)
        if unset is None:
            monkeypatch.delenv("TWITCH_EXTENSION_VERSION", raising=False)
        else:
            monkeypatch.setenv("TWITCH_EXTENSION_VERSION", unset)
        caplog.clear()
        twitch._post_chat_message(_CHANNEL, "hello")
        twitch._post_chat_message(_CHANNEL, "hello again")
        assert post_recorder.calls == []
        warnings = [r for r in caplog.records
                    if r.levelno == logging.WARNING and "TWITCH_EXTENSION_VERSION" in r.getMessage()]
        assert len(warnings) == 1


def test_post_chat_message_local_dev_logs_instead_of_calling_twitch(post_recorder, monkeypatch, caplog):
    """AC: local dev (TWITCH_LOCAL_DEV=true) still logs the message instead of calling Twitch.

    Approach: setenv TWITCH_LOCAL_DEV=true (credentials and version may be unset);
    caplog at INFO for logger "twitch"; call _post_chat_message; assert no
    recorded calls, the message text appears in the log, and no
    TWITCH_EXTENSION_VERSION warning is logged.
    """
    import twitch
    monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("TWITCH_EXTENSION_VERSION", raising=False)
    monkeypatch.delenv("TWITCH_EXTENSION_SECRET", raising=False)
    monkeypatch.delenv("TWITCH_EXTENSION_CLIENT_ID", raising=False)
    monkeypatch.setattr(twitch, "_chat_version_warned", False)
    caplog.set_level(logging.INFO, logger="twitch")
    twitch._post_chat_message(_CHANNEL, "dev chat text 140")
    assert post_recorder.calls == []
    assert "dev chat text 140" in caplog.text
    assert "TWITCH_EXTENSION_VERSION" not in caplog.text


# ===========================================================================
# Story 2 — Announcements Fit Twitch's Limit
# ===========================================================================

def test_mvp_chat_text_all_winners_fit_within_280(monkeypatch):
    """AC: the announcement text is at most 280 characters.

    Updated for issue #157: the text names the MVP and only how many viewers
    received a token, never their usernames. With no joined viewers in the pool
    the chat says no tokens were dropped.
    """
    import twitch
    text = twitch._mvp_chat_text("PlayerOne", 2, False)
    assert len(text) <= 280
    assert text == "Match MVP: PlayerOne! 2 viewers received a token."
    assert twitch._mvp_chat_text("PlayerOne", 1, False) == "Match MVP: PlayerOne! 1 viewer received a token."

    empty = twitch._mvp_chat_text("PlayerOne", 0, True)
    assert empty == "Match MVP: PlayerOne! No tokens were dropped: no joined viewers were watching."
    assert twitch._mvp_chat_text("PlayerOne", 0, False) == "Match MVP: PlayerOne!"


def test_mvp_chat_text_too_many_winners_truncates_with_and_n_more():
    """AC: a large drop still fits in 280 characters.

    Updated for issue #157: there is no winner list to truncate any more; 20
    winners are reported as a count ("20 viewers received a token")."""
    import twitch
    text = twitch._mvp_chat_text("PlayerOne", 20, False)
    assert len(text) <= 280
    assert text == "Match MVP: PlayerOne! 20 viewers received a token."
    assert "more" not in text


def test_mvp_chat_text_long_mvp_name_always_included_in_full():
    """AC: the MVP name is always included in full.

    Approach: a long player name (60 chars) plus a 20-winner drop; the full name
    is in the text and len <= 280.
    """
    import twitch
    name = "M" * 60
    text = twitch._mvp_chat_text(name, 20, False)
    assert text.startswith(f"Match MVP: {name}!")
    assert len(text) <= 280
    assert text.endswith("received a token.")


def test_set_mvp_large_token_drop_chat_message_within_280(db, twitch_prod_env, post_recorder, monkeypatch):
    """AC: a 20-winner drop with long usernames yields a chat message of 280 characters
    or fewer (endpoint wiring). Since issue #157 it names the MVP and the winner
    count only, so no username appears in chat.

    Approach: seed match 1001 (teams 11 vs 12, now - 3600, player_ids=(102, 103))
    and 20 linked viewers with 25-char usernames present in TwitchPresence for
    _CHANNEL; patch twitch._post_chat_message with a recorder; call
    _call_set_mvp(db, 1001, 102); assert the recorded message.
    """
    import twitch
    from models import TwitchPresence, User
    _seed_match(db, 1001, 11, 12, int(time.time()) - 3600, player_ids=(102, 103))
    now = int(time.time())
    for i in range(20):
        db.add(User(id=100 + i, username=f"viewer{i:02d}".ljust(25, "x"), tokens=0,
                    twitch_user_id=f"U{i:03d}"))
        db.add(TwitchPresence(twitch_user_id=f"U{i:03d}", channel_id=_CHANNEL, seen_at=now))
    db.commit()
    chat = []
    monkeypatch.setattr(twitch, "_post_chat_message",
                        lambda channel_id, message: chat.append((channel_id, message)))
    result = _call_set_mvp(db, 1001, 102)
    assert result["token_drop"]["winner_count"] == 20
    assert "winners" not in result["token_drop"]
    assert result["token_drop"]["winner_count"] == 20
    assert len(chat) == 1
    channel_id, message = chat[0]
    assert channel_id == _CHANNEL
    assert message == "Match MVP: Player102! 20 viewers received a token."
    assert len(message) <= 280
    assert "viewer00" not in message


# ===========================================================================
# Story 3 — Failures Are Visible to Operators
# ===========================================================================

def test_post_chat_message_non_2xx_logs_status_and_body_without_jwt(twitch_prod_env, post_recorder, caplog):
    """AC: a non-2xx chat response logs a warning with the HTTP status and Twitch's
    error message (body truncated to 300 characters), and never the JWT.

    Approach: post_recorder.response = _FakeResponse(403, '{"message":"chat disabled"}'
    + "x" * 500); call _post_chat_message; assert a WARNING contains "403" and
    "chat disabled", the body portion is at most 300 chars, and the Bearer
    token from the recorded headers does not appear in caplog.text.
    """
    import twitch
    caplog.set_level(logging.WARNING, logger="twitch")
    body = '{"message":"chat disabled"}' + "x" * 500
    post_recorder.response = _FakeResponse(403, body)
    twitch._post_chat_message(_CHANNEL, "hello")
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "403" in msg and "chat disabled" in msg
    assert body[:300] in msg and body[:301] not in msg
    token = post_recorder.calls[0][1]["headers"]["Authorization"].removeprefix("Bearer ")
    assert token not in caplog.text


def test_pubsub_broadcast_non_2xx_logs_status_and_body_without_jwt(twitch_prod_env, post_recorder, caplog):
    """AC: a non-2xx PubSub response logs a warning with the HTTP status and body
    (truncated to 300 characters), and never the JWT.

    Approach: post_recorder.response = _FakeResponse(401, "invalid token" + "y" * 500);
    call _pubsub_broadcast(_CHANNEL, {"type": "mvp"}); assert WARNING has "401"
    and "invalid token", no JWT in caplog.text. A 204 response logs no warning.
    """
    import twitch
    caplog.set_level(logging.WARNING, logger="twitch")
    body = "invalid token" + "y" * 500
    post_recorder.response = _FakeResponse(401, body)
    twitch._pubsub_broadcast(_CHANNEL, {"type": "mvp"})
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    msg = warnings[0].getMessage()
    assert "401" in msg and "invalid token" in msg
    assert body[:300] in msg and body[:301] not in msg
    token = post_recorder.calls[0][1]["headers"]["Authorization"].removeprefix("Bearer ")
    assert token not in caplog.text

    caplog.clear()
    post_recorder.response = _FakeResponse(204)
    twitch._pubsub_broadcast(_CHANNEL, {"type": "mvp"})
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_post_chat_message_timeout_still_logged(twitch_prod_env, post_recorder, caplog):
    """AC: a timeout or connection error is still logged, as today (chat and PubSub).

    Approach: post_recorder.exc = requests.exceptions.Timeout("timed out") (then
    ConnectionError); call _post_chat_message and _pubsub_broadcast; assert
    neither raises and each logs an error record ("Twitch chat message failed"
    / "Twitch PubSub broadcast failed").
    """
    import requests
    import twitch
    caplog.set_level(logging.WARNING, logger="twitch")
    for exc in (requests.exceptions.Timeout("timed out"),
                requests.exceptions.ConnectionError("refused")):
        post_recorder.exc = exc
        caplog.clear()
        twitch._post_chat_message(_CHANNEL, "hello")
        twitch._pubsub_broadcast(_CHANNEL, {"type": "mvp"})
        errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
        assert "Twitch chat message failed" in errors
        assert "Twitch PubSub broadcast failed" in errors


def test_set_mvp_chat_and_pubsub_failure_still_returns_result_and_keeps_drop(db, twitch_prod_env, post_recorder):
    """AC: POST /twitch/mvp returns 200 and keeps the MVP, bonus and token drop when
    the chat or PubSub call fails.

    Approach: seed a Weight(mvp_bonus_pct), match 1001 (player_ids=(102, 103)) and
    _add_viewer; post_recorder.response = _FakeResponse(403, "forbidden");
    _call_set_mvp(db, 1001, 102) returns normally with winners == ["viewer"];
    assert TwitchMVP row exists, PlayerMatchStats(102, 1001).is_mvp is True,
    one TwitchTokenDrop, viewer.tokens == 1. Repeat with post_recorder.exc =
    ConnectionError on a fresh match to cover the exception path.
    """
    from models import PlayerMatchStats, TwitchMVP, TwitchTokenDrop, User, Weight
    db.add(Weight(key="mvp_bonus_pct", label="MVP bonus (%)", value=10.0))
    now = int(time.time())
    _seed_match(db, 1001, 11, 12, now - 3600, player_ids=(102, 103))
    _seed_match(db, 1002, 11, 12, now - 1800, player_ids=(102, 103))
    _add_viewer(db)

    import requests
    outcomes = [(1001, lambda: setattr(post_recorder, "response", _FakeResponse(403, "forbidden"))),
                (1002, lambda: setattr(post_recorder, "exc", requests.exceptions.ConnectionError("down")))]
    for expected_tokens, (match_id, arrange) in enumerate(outcomes, start=1):
        arrange()
        calls_before = len(post_recorder.calls)
        result = _call_set_mvp(db, match_id, 102)
        assert len(post_recorder.calls) - calls_before == 2  # PubSub + chat both attempted
        assert result["token_drop"]["winner_count"] == 1
        assert "winners" not in result["token_drop"]
        assert db.query(TwitchMVP).filter_by(match_id=match_id, player_id=102).count() == 1
        row = db.query(PlayerMatchStats).filter_by(player_id=102, match_id=match_id).one()
        assert row.is_mvp is True
        assert db.query(TwitchTokenDrop).filter_by(channel_id=_CHANNEL,
                                                   series_id=str(match_id)).count() == 1
        assert db.get(User, 50).tokens == expected_tokens
