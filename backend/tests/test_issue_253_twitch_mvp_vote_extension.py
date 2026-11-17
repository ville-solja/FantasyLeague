"""
Tests for plan-issue-253-twitch-mvp-vote-extension.md (resolves GitHub issue #253).

A second Twitch extension, "Kana Cards MVP Vote", runs against the same backend
as the full extension: the streamer opens the #234 MVP poll from a small live
configuration view, any viewer logged in to Twitch votes (no Join, no account),
and voters who accepted Twitch's identity share enter a token drop. A picked
voter with a Kana Cards account is credited at once; one without gets a pending
token (`twitch_pending_tokens`), claimed when the Twitch id is attached to an
account. One class per user story, one stub per acceptance criterion plus the
primary failure path; the last class covers Step 6's migration bullet.

Developer notes
---------------

  Existing code these tests target
    - backend/twitch.py: `verify_twitch_jwt` (today: one secret,
      TWITCH_EXTENSION_SECRET, URL-safe base64; counters `_record_ok` /
      `_record_failure`, `FAILURE_KINDS`, `traffic_snapshot`, `reset_traffic`),
      `_remember_viewer`, `_logged_in_opaque_id` (403 `twitch_login_required`),
      `_pubsub_broadcast` and `_post_chat_message` (both read
      TWITCH_EXTENSION_SECRET / TWITCH_EXTENSION_CLIENT_ID and return early
      under TWITCH_LOCAL_DEV), `join`, `draw`, `roster_activate`,
      `_record_identity_share`, `set_mvp` / `MVPBody(poll_id=...)`,
      `_execute_token_drop`, `_TWITCH_DROP_MAX` (module constant read at
      import: monkeypatch the attribute, not the env var), `drops_enabled`.
    - backend/twitch_mvp_poll.py: `open_poll`, `get_poll`, `vote` (today:
      `_voter_state` requires a joined account old enough for drops, refusal
      detail `not_joined`), `end_poll`, `cancel_poll`, `poll_view`,
      `mark_confirmed`, `_now` (monkeypatch for time).
    - backend/soft_accounts.py: `starter_grant_hash` (the keyed HMAC the plan
      says to reuse for `account_hash`), `find_by_twitch_account_id`,
      `record_twitch_account_id`, `get_or_create_soft_account`.
    - backend/twitch_oauth.py: `connect_account(db, user, sub)`.
    - backend/database.py: `credit_tokens(db, user_id, amount)`.
    - backend/main.py: CORS (`_ext_origin_regex` from TWITCH_EXTENSION_CLIENT_ID,
      `CORS_EXTRA_ORIGINS`), applied twice (CORSMiddleware and the refused-origin
      middleware) with the same allow list.
    - backend/twitch_status.py `build_status`, routers/admin_twitch.py.
    - Check every "as today" claim in the plan against the code before pinning it
      (lessons-learned 2026-10-13).

  Imports
    - Import `twitch_vote_rewards`, `TwitchPendingToken` (name to be confirmed in
      models.py) and anything else the plan adds INSIDE each test: they don't
      exist yet, and a module-level import would break collection.
    - `import models` stays at module level so the conftest `db` fixture creates
      every table.

  Reusable helpers / fixtures (all exist today)
    - From test_issue_157_twitch_extension_policy_compliance.py: `twitch_env`
      (TWITCH_LOCAL_DEV, no real Twitch calls), `_viewer(opaque_id, user_id,
      role)`, `_BROADCASTER`, `_CHANNEL`, `_ANON` (an `A...` viewer), `_join`,
      `_backdate`, `_present`, `_website_user`, `_user_by_opaque`, `_raises`,
      `_chat_recorder`, `_no_twitch_ids`, `_shared_db` (StaticPool session for
      TestClient), `_twitch_app`, `_signed(opaque_id, role, user_id, secret)`,
      `_SECRET_BYTES` / `_SECRET_B64`, `_js_function`, `REPO_ROOT`.
    - From test_issue_234_mvp_poll_for_watchers.py: `_seed_ten`, `_TEN`, `_open`,
      `_vote`, `_get`, `_end`, `_cancel`, `_voter`, `_clock`, `_pubsub`,
      `_poll_row`, `_audits`, `_confirm`, `_mvp_body`, `_closed_poll`. They pass
      plain payload dicts: add `"ext": "vote"` (or `"game"`) to the payload for
      the extension under test, e.g. `{**_viewer("Uv1"), "ext": "vote"}`.
    - From test_issue_180_twitch_integration_status.py: `jwt_env` (real JWT path
      with a known secret), `status_env`, `_status`, `_row`, `_admin_client`,
      `_fresh_traffic`, `_refused_origin_app`, `_CLIENT_ID`.
    - From test_issue_195_twitch_extension_resubmission.py: `_called_paths`,
      `PARAM_BY_PREFIX`, `_coverage_problems`, `_api_routes`,
      `_backend_twitch_routes`, `_route_problems`, `_require_zip`,
      `_run_package`, `_section`, `_flat`. `_packaged_called_paths`,
      `_endpoint_rows`, `_ext_copy` and `_submission_doc` are bound to
      `twitch-extension/` and its guide: write vote-extension equivalents here
      over `VOTE_EXT_DIR` and `VOTE_SUBMISSION_DOC` instead of importing them.
    - From tests/test_migrate.py: `legacy_engine`, `fresh_engine`; migration tests
      that need earlier migrations recorded follow `_legacy_engine` in
      test_issue_129_*.

  Pitfalls
    - A second signing secret for JWT tests: any 32 bytes other than
      `_SECRET_BYTES`, base64-encoded into TWITCH_VOTE_EXTENSION_SECRET.
    - Concurrent-claim test: run it against a claim without the
      `UPDATE ... WHERE claimed_at IS NULL` guard first and confirm it fails
      (lessons-learned 2026-10-13 concurrency), and handle "the other thread
      already finished" as the caller does (2026-11-16 ship).
    - Unique on (`account_hash`, `poll_id`): both columns are NOT NULL here, so a
      plain unique constraint holds; test a duplicate insert explicitly.
    - Never parse HTML with regexes; assert URLs and origins with exact equality.

  Existing tests this plan may break
    - test_issue_175 / test_issue_234 may pin the column sets of
      `twitch_mvp_polls` / `twitch_mvp_votes` and "not in migrate.py"; grep
      backend/tests for both table names before adding columns.
    - test_issue_180 pins the exact list of status check keys
      (`[c["key"] for c in`) with every row "ok": extend the list and configure
      the vote extension in `status_env`.
    - test_issue_234's `_voter_state` / `not_joined` assertions must keep passing
      for payloads with no `ext` key or `ext == "game"`.
    - test_issue_195's `_backend_twitch_routes` and endpoint table: new routes
      called only by the vote extension belong in the vote guide's table, not
      the full extension's.
    - test_issue_85 caps each routers/admin_*.py at 350 lines.
"""

import base64
import json
import random
import re
import shutil
import subprocess
import threading
import time
import zipfile
from html.parser import HTMLParser

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

# Registers every existing table on Base before the conftest db fixture runs
# create_all. New models are imported inside tests.
import models  # noqa: F401

from tests.test_issue_157_twitch_extension_policy_compliance import (  # noqa: F401
    REPO_ROOT, _ANON, _BROADCASTER, _CHANNEL, _SECRET_BYTES, _backdate, _chat_recorder,
    _join, _js_function, _no_twitch_ids, _present, _raises, _shared_db, _signed,
    _twitch_app, _user_by_opaque, _viewer, _website_user, twitch_env,
)
from tests.test_issue_234_mvp_poll_for_watchers import (  # noqa: F401
    _TEN, _audits, _cancel, _clock, _closed_poll, _confirm, _end, _get, _open,
    _poll_row, _pubsub, _seed_ten, _vote, _voter,
)

VOTE_EXT_DIR = REPO_ROOT / "twitch-vote-extension"
VOTE_SUBMISSION_DOC = (
    REPO_ROOT / "markdown" / "features" / "reference" / "twitch-vote-extension-review-submission.md"
)
VOTE_PACKAGED_JS = ["panel.js", "extension.js", "live_config.js", "config.js"]

# A second extension secret, different from the game extension's _SECRET_BYTES.
_VOTE_SECRET_BYTES = b"issue-253-vote-extension-secret!"

# Payloads as verify_twitch_jwt will return them for the vote extension.
_VOTE_BROADCASTER = {**_BROADCASTER, "ext": "vote"}


def _vote_viewer(opaque_id="Uviewer1", user_id=None, role="viewer"):
    """A vote-extension viewer payload; pass `user_id` after the identity share."""
    return {**_viewer(opaque_id, user_id=user_id, role=role), "ext": "vote"}


@pytest.fixture(autouse=True)
def _env(twitch_env, monkeypatch):
    """No real Twitch calls, and the default drop and token rules whatever the shell exports."""
    import twitch
    for name in ("TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS", "TWITCH_DROPS_ENABLED",
                 "TWITCH_VOTE_TOKENS_ENABLED", "TWITCH_VOTE_EXTENSION_CLIENT_ID",
                 "TWITCH_VOTE_EXTENSION_SECRET", "TWITCH_VOTE_EXTENSION_VERSION"):
        monkeypatch.delenv(name, raising=False)
    twitch.reset_traffic()
    yield
    twitch.reset_traffic()




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GAME_ID, _VOTE_ID = "game123clientid", "vote456clientid"
_GAME_B64 = base64.b64encode(_SECRET_BYTES).decode()
_VOTE_B64 = base64.b64encode(_VOTE_SECRET_BYTES).decode()
_THIRD_SECRET = b"issue-253-some-other-ext-secret!"


def _vext(name):
    return (VOTE_EXT_DIR / name).read_text(encoding="utf-8")


def _vopen(db, match_id=1001, duration=120):
    return _open(db, match_id=match_id, duration=duration, payload=_VOTE_BROADCASTER)


def _vvote(db, poll_id, player_id, opaque_id="Uviewer1", user_id=None):
    return _vote(db, poll_id, player_id, payload=_vote_viewer(opaque_id, user_id=user_id))


def _vget(db, opaque_id="Uviewer1", user_id=None):
    import twitch_mvp_poll
    return twitch_mvp_poll.get_poll(_vote_viewer(opaque_id, user_id=user_id), db)


def _vend(db, poll_id):
    import twitch_mvp_poll
    return twitch_mvp_poll.end_poll(poll_id, dict(_VOTE_BROADCASTER), db)


def _vconfirm(db, poll_id, player_id=101):
    return _confirm(db, poll_id, player_id=player_id, payload=_VOTE_BROADCASTER)


def _recorders(monkeypatch):
    """(chat, pubsub): each a list of (extension, message). Unlike the 157/234 recorders
    these take the `ext` keyword a vote-extension poll sends."""
    import twitch
    chat, pubsub = [], []
    monkeypatch.setattr(twitch, "_post_chat_message",
                        lambda channel_id, message, ext="game": chat.append((ext, message)))
    monkeypatch.setattr(twitch, "_pubsub_broadcast",
                        lambda channel_id, message, ext="game": pubsub.append((ext, message)))
    return chat, pubsub


def _votes(db, poll_id):
    from models import TwitchMvpVote
    db.expire_all()
    return db.query(TwitchMvpVote).filter(TwitchMvpVote.poll_id == poll_id).all()


def _pending(db):
    from models import TwitchPendingToken
    db.expire_all()
    return db.query(TwitchPendingToken).order_by(TwitchPendingToken.id).all()


def _tokens(db, user):
    db.expire_all()
    return db.get(type(user), user.id).tokens


def _users(db):
    from models import User
    return db.query(User).count()


def _hash(real_id):
    import soft_accounts
    return soft_accounts.starter_grant_hash(real_id)


def _shared_poll(db, voters, end=True):
    """A vote-extension poll on match 1001 with `voters` ({opaque_id: real Twitch id or
    None}), each voting for player 101; closed by End now unless `end` is False."""
    _seed_ten(db)
    poll = _vopen(db)
    for opaque_id, real_id in voters.items():
        _vvote(db, poll["poll_id"], 101, opaque_id, user_id=real_id)
    if end:
        _vend(db, poll["poll_id"])
    return poll["poll_id"]


class _Markup(HTMLParser):
    """Tags, attributes and text of a markup string (never a regex over HTML)."""

    def __init__(self, markup):
        super().__init__()
        self.tags, self.texts = [], []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        if data.strip():
            self.texts.append(" ".join(data.split()))

    def has(self, tag, **attrs):
        return any(t == tag and all(a.get(k) == v for k, v in attrs.items()) for t, a in self.tags)

    def ids(self):
        return {a["id"] for _, a in self.tags if "id" in a}

    @property
    def text(self):
        return " ".join(self.texts)


_PANEL_FUNCTIONS = ("votesText", "secondsLeft", "countdownText", "playerName", "idleHtml",
                    "dropStepHtml", "openHtml", "resultHtml", "panelHtml")


def _panel_html(tmp_path, data, view):
    """panel.js's panelHtml(data, view) run under Node (skips without Node)."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    panel = _vext("panel.js")
    constants = "\n".join(line for line in panel.splitlines() if re.match(r"var [A-Z_]+ = .*;$", line))
    functions = "\n".join(_js_function(panel, name) for name in _PANEL_FUNCTIONS)
    script = "\n".join([
        _js_function(_vext("extension.js"), "_escHtml"), constants, functions,
        f"console.log(JSON.stringify(panelHtml({json.dumps(data)}, {json.dumps(view)})));",
    ])
    path = tmp_path / "panel_harness.js"
    path.write_text(script, encoding="utf-8")
    out = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


_TEAMS = [{"team_name": "Team11", "players": [{"player_id": 101, "player_name": "Player101"},
                                              {"player_id": 102, "player_name": "<b>P102</b>"}]},
          {"team_name": "Team12", "players": [{"player_id": 201, "player_name": "Player201"}]}]


def _js_poll(**over):
    poll = {"poll_id": 7, "match_id": 1001, "status": "open", "closes_at": 1090, "now": 1000,
            "team1_name": "Team11", "team2_name": "Team12", "match_number": 2, "teams": _TEAMS,
            "total_votes": 3, "my_vote": None, "confirmed_player_id": None,
            "token_drop": {"enabled": True, "entered": False, "pending_win": False}}
    poll.update(over)
    return poll


def _js_view(**over):
    view = {"loaded": True, "unavailable": "", "loggedIn": True, "shared": False, "pick": None,
            "error": "", "nowSec": 1000}
    view.update(over)
    return view


# ---------------------------------------------------------------------------
# Story 1 — The Streamer Runs an MVP Vote After the Match
# ---------------------------------------------------------------------------

class TestStreamerRunsMvpVote:

    def test_vote_live_config_lists_series_and_has_start_viewer_vote_with_durations(self):
        """twitch-vote-extension/live_config.html has Start viewer vote with a 60/120/180 second choice, and live_config.js loads the current series and posts match_id and duration_seconds to /twitch/mvp-poll."""
        page = _Markup(_vext("live_config.html"))
        assert "Start viewer vote" in page.text
        assert page.has("select", id="poll-duration")
        assert [a["value"] for t, a in page.tags if t == "option"] == ["60", "120", "180"]
        assert page.has("button", id="btn-open-vote")
        js = _vext("live_config.js")
        assert 'ebsGet("/twitch/matches/current")' in _js_function(js, "loadSeries")
        start = _js_function(js, "startViewerVote")
        assert 'ebsPost("/twitch/mvp-poll", {' in start
        assert "match_id: _selectedMatch.match_id" in start
        assert 'duration_seconds: Number(el("poll-duration").value)' in start
        # The vote is this extension's main mode: it is the one shown for a match.
        assert 'showMatchMode("vote")' in _js_function(js, "selectMatch")

    def test_open_poll_from_vote_extension_stores_extension_on_poll(self, db):
        """open_poll with a vote-extension broadcaster payload returns an open poll and the twitch_mvp_polls row has extension == "vote"; a game-extension payload stores "game"."""
        _seed_ten(db)
        poll = _vopen(db)
        assert poll["status"] == "open"
        assert _poll_row(db, poll["poll_id"]).extension == "vote"
        _cancel(db, poll["poll_id"])
        for payload in (dict(_BROADCASTER), {**_BROADCASTER, "ext": "game"}):
            other = _open(db, payload=payload)
            assert _poll_row(db, other["poll_id"]).extension == "game"
            _cancel(db, other["poll_id"])

    def test_open_poll_from_vote_extension_posts_one_chat_message_and_pubsub_open(self, db, monkeypatch):
        """Opening the vote posts exactly one chat message (open_chat_text) and broadcasts one mvp_poll open PubSub message."""
        import twitch_mvp_poll
        chat, pubsub = _recorders(monkeypatch)
        _seed_ten(db)
        poll = _vopen(db, duration=180)
        expected = twitch_mvp_poll.open_chat_text("Team11", "Team12", 1, 180, ext="vote")
        assert chat == [("vote", expected)]
        assert expected == ("MVP vote open for Team11 vs Team12, game 1: vote in the "
                            "Kana Cards MVP Vote panel. Closes in 3 min.")
        assert pubsub == [("vote", {"type": "mvp_poll", "state": "open", "poll_id": poll["poll_id"]})]
        # The full extension's line is unchanged.
        assert "vote in the Kana Cards panel." in twitch_mvp_poll.open_chat_text("A", "B", 1, 60)

    def test_open_poll_from_vote_extension_by_viewer_returns_403(self, db):
        """A vote-extension viewer or moderator payload cannot open a poll: 403 and no poll row or audit is written."""
        from models import TwitchMvpPoll
        _seed_ten(db)
        for role in ("viewer", "moderator"):
            _raises(lambda: _open(db, payload=_vote_viewer("Uv1", role=role)), 403)
        assert db.query(TwitchMvpPoll).count() == 0
        assert _audits(db, "twitch_mvp_poll_opened") == []

    def test_open_poll_from_vote_extension_unapproved_channel_returns_403_and_records_request(self, db, monkeypatch):
        """With TWITCH_MVP_CHANNEL_IDS naming another channel, the vote extension's open is refused with 403, a pending TwitchChannelApproval row is recorded and no poll is written."""
        from models import TwitchChannelApproval, TwitchMvpPoll
        import twitch_channels
        monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", "some_other_channel")
        _seed_ten(db)
        payload = {**_VOTE_BROADCASTER, "channel_id": "123456"}    # approval rows need a numeric id
        _raises(lambda: _open(db, payload=payload), 403, "This channel cannot set match MVPs")
        row = db.get(TwitchChannelApproval, "123456")
        assert row is not None and row.status == twitch_channels.PENDING
        assert db.query(TwitchMvpPoll).count() == 0

    def test_open_poll_second_poll_on_channel_returns_409_across_extensions(self, db):
        """With a poll already open on the channel (opened by either extension), a second open from the other extension answers 409 and writes no second row."""
        from models import TwitchMvpPoll
        _seed_ten(db)
        first = _vopen(db)
        _raises(lambda: _open(db), 409, "A viewer vote is already open on this channel")
        assert db.query(TwitchMvpPoll).count() == 1
        _cancel(db, first["poll_id"])
        _open(db)
        _raises(lambda: _vopen(db), 409, "A viewer vote is already open on this channel")
        assert db.query(TwitchMvpPoll).count() == 2

    def test_end_now_from_vote_extension_returns_tally_with_sole_winner(self, db):
        """end_poll with the vote-extension broadcaster closes the poll and returns each player's votes with the sole leader as winner."""
        _seed_ten(db)
        poll = _vopen(db)
        for opaque_id, pid in (("Ua", 101), ("Ub", 101), ("Uc", 202)):
            _vvote(db, poll["poll_id"], pid, opaque_id)
        closed = _vend(db, poll["poll_id"])
        assert closed["status"] == "closed"
        assert closed["winner_player_id"] == 101 and closed["tied_player_ids"] == []
        votes = {r["player_id"]: r["votes"] for r in closed["results"]}
        assert votes[101] == 2 and votes[202] == 1 and sum(votes.values()) == 3
        assert len(closed["results"]) == 10

    def test_poll_closes_on_timer_for_vote_extension_poll(self, db, monkeypatch):
        """After closes_at (clock moved with _clock), get_poll shows the vote-extension poll as closed with its tally, without End now."""
        _seed_ten(db)
        poll = _vopen(db, duration=60)
        _vvote(db, poll["poll_id"], 103, "Ua")
        _clock(monkeypatch, 61)
        view = _vget(db, "Ub")["poll"]
        assert view["status"] == "closed" and view["closed_at"] == poll["closes_at"]
        assert view["winner_player_id"] == 103 and view["total_votes"] == 1
        assert _poll_row(db, poll["poll_id"]).status == "closed"

    def test_tie_or_no_votes_has_no_winner_and_streamer_can_pick(self, db):
        """A tied or empty vote-extension poll reports no winner, and set_mvp with poll_id and a hand-picked player of the match succeeds."""
        from models import TwitchMVP
        _seed_ten(db)
        _seed_ten(db, match_id=1002)
        tied = _vopen(db)
        _vvote(db, tied["poll_id"], 101, "Ua")
        _vvote(db, tied["poll_id"], 202, "Ub")
        closed = _vend(db, tied["poll_id"])
        assert closed["winner_player_id"] is None and closed["tied_player_ids"] == [101, 202]
        assert _vconfirm(db, tied["poll_id"], player_id=202)["player_id"] == 202
        empty = _vopen(db, match_id=1002)
        closed = _vend(db, empty["poll_id"])
        assert closed["winner_player_id"] is None and closed["total_votes"] == 0
        result = _confirm(db, empty["poll_id"], player_id=104, match_id=1002, payload=_VOTE_BROADCASTER)
        assert result["player_id"] == 104
        assert {m.match_id: m.player_id for m in db.query(TwitchMVP).all()} == {1001: 202, 1002: 104}

    def test_confirm_mvp_from_vote_extension_sets_mvp_bonus_chat_and_audit(self, db, monkeypatch):
        """set_mvp with poll_id from the vote-extension broadcaster writes the TwitchMVP row, sets is_mvp and the fantasy bonus, posts one chat message, writes the MVP audit and marks the poll confirmed."""
        from models import PlayerMatchStats, TwitchMVP
        import scoring
        poll_id = _shared_poll(db, {"Ua": None, "Ub": None})
        chat, pubsub = _recorders(monkeypatch)
        result = _vconfirm(db, poll_id, player_id=101)
        assert result["player_id"] == 101 and result["player_name"] == "Player101"
        mvp = db.query(TwitchMVP).one()
        assert (mvp.match_id, mvp.player_id, mvp.channel_id) == (1001, 101, _CHANNEL)
        row = db.query(PlayerMatchStats).filter_by(match_id=1001, player_id=101).one()
        base = scoring.fantasy_score(scoring.stat_dict_from_row(row), {})
        assert row.is_mvp is True and base > 0
        assert row.fantasy_points == round(base * 1.10, 4)        # the default 10% MVP bonus
        assert db.query(PlayerMatchStats).filter_by(match_id=1001, is_mvp=True).count() == 1
        assert chat == [("vote", "Match MVP by viewer vote: Player101 (100% of 2 votes)!")]
        assert [m for ext, m in pubsub if m["type"] == "mvp"] == [
            {"type": "mvp", "player_name": "Player101", "match_id": 1001,
             "token_drop": {"count": 0, "refresh": False}}]
        assert all(ext == "vote" for ext, _ in pubsub)
        audit = _audits(db, "twitch_mvp_set")
        assert len(audit) == 1 and f"poll={poll_id}" in audit[0] and "player=Player101" in audit[0]
        row = _poll_row(db, poll_id)
        assert row.status == "confirmed" and row.confirmed_player_id == 101

    def test_confirm_mvp_on_open_vote_extension_poll_returns_409(self, db):
        """set_mvp with the poll_id of a still-open poll answers 409 and writes no MVP row."""
        from models import TwitchMVP
        poll_id = _shared_poll(db, {"Ua": "9001"}, end=False)
        _raises(lambda: _vconfirm(db, poll_id), 409, "The vote is not closed")
        assert db.query(TwitchMVP).count() == 0
        assert _poll_row(db, poll_id).status == "open"
        assert _pending(db) == []

    def test_cancel_vote_from_vote_extension_ends_poll_with_no_mvp(self, db, monkeypatch):
        """cancel_poll sets the poll cancelled, writes no TwitchMVP row, drops no tokens and creates no pending tokens."""
        from models import TwitchMVP, TwitchTokenDrop
        user = _website_user(db, "alice")
        user.twitch_account_id = "9001"
        db.commit()
        poll_id = _shared_poll(db, {"Ua": "9001", "Ub": "9002"}, end=False)
        chat, pubsub = _recorders(monkeypatch)
        assert _cancel(db, poll_id, payload=_VOTE_BROADCASTER) == {"poll_id": poll_id, "status": "cancelled"}
        assert db.query(TwitchMVP).count() == 0 and db.query(TwitchTokenDrop).count() == 0
        assert _pending(db) == [] and _tokens(db, user) == 5
        assert chat == []
        assert pubsub == [("vote", {"type": "mvp_poll", "state": "cancelled", "poll_id": poll_id})]
        _raises(lambda: _vconfirm(db, poll_id), 409)

    def test_vote_live_config_has_end_now_cancel_confirm_and_manual_pick(self):
        """The vote extension's live_config has End now, Cancel vote and Confirm MVP controls, shows per-player votes with the winner preselected, and lets the streamer pick a player on a tie or no votes."""
        page = _Markup(_vext("live_config.html"))
        assert {"btn-poll-end", "btn-poll-cancel", "btn-poll-confirm", "btn-confirm-mvp",
                "poll-result-list", "player-grid"} <= page.ids()
        for label in ("End now", "Cancel vote", "Confirm MVP", "Pick MVP"):
            assert label in page.text
        assert "Drop Tokens" not in page.text       # tokens go to voters, not on every confirm
        js = _vext("live_config.js")
        assert '"/twitch/mvp-poll/" + _poll.poll_id + "/end"' in _js_function(js, "endViewerVote")
        assert '"/twitch/mvp-poll/" + _poll.poll_id + "/cancel"' in _js_function(js, "cancelViewerVote")
        confirm = _js_function(js, "confirmPollMVP")
        assert 'ebsPost("/twitch/mvp", {' in confirm and "poll_id:   _poll.poll_id" in confirm
        state = _js_function(js, "pollResultState")
        assert 'kind: "winner", preselect: poll.winner_player_id' in state
        assert 'kind: "tie", preselect: null' in state and 'kind: "none"' in state
        result = _js_function(js, "renderPollResult")
        assert "voteCountText(r.votes)" in result and "pickPollPlayer(r, div)" in result
        assert "pickAfterNoVotes()" in result
        assert "won a token" in _js_function(js, "dropNote")


# ---------------------------------------------------------------------------
# Story 2 — A Viewer Votes With Only a Twitch Login
# ---------------------------------------------------------------------------

class TestViewerVotesWithTwitchLogin:

    def test_vote_panel_no_poll_state_shows_last_mvp_and_waiting_text(self, tmp_path):
        """twitch-vote-extension/panel.js renders, with no poll, the channel's last MVP when there is one and the text "The streamer starts the vote after the match"."""
        assert 'var WAITING_TEXT = "The streamer starts the vote after the match";' in _vext("panel.js")
        with_mvp = _Markup(_panel_html(tmp_path, {"poll": None, "last_mvp": {"player_name": "<i>Ace</i>"}},
                                       _js_view()))
        assert "Last MVP" in with_mvp.text and "<i>Ace</i>" in with_mvp.text      # escaped, shown as text
        assert not with_mvp.has("i") and not with_mvp.has("button")
        assert "The streamer starts the vote after the match." in with_mvp.text
        without = _Markup(_panel_html(tmp_path, {"poll": None, "last_mvp": None}, _js_view()))
        assert "Last MVP" not in without.text
        assert without.text == "The streamer starts the vote after the match."

    def test_get_poll_with_no_poll_returns_last_confirmed_mvp_of_channel(self, db):
        """get_poll from a vote-extension viewer with no open or recent poll returns no poll and the channel's last confirmed MVP (player name and match), or none when the channel never set one."""
        import twitch
        import twitch_mvp_poll
        _seed_ten(db)
        _seed_ten(db, match_id=1002)
        assert _vget(db) == {"poll": None, "last_mvp": None}
        twitch.set_mvp(twitch.MVPBody(match_id=1001, player_id=102), payload=dict(_VOTE_BROADCASTER), db=db)
        twitch.set_mvp(twitch.MVPBody(match_id=1002, player_id=203), payload=dict(_VOTE_BROADCASTER), db=db)
        assert _vget(db) == {"poll": None, "last_mvp": {"match_id": 1002, "player_id": 203,
                                                        "player_name": "Player203"}}
        # Another channel's MVP is not this channel's, and the full extension's answer is unchanged.
        other = {**_vote_viewer(), "channel_id": "another_channel"}
        assert twitch_mvp_poll.get_poll(other, db) == {"poll": None, "last_mvp": None}
        assert twitch_mvp_poll.get_poll(_viewer(), db) == {"poll": None}

    def test_vote_panel_open_poll_state_shows_teams_countdown_and_vote(self, tmp_path):
        """With an open poll the panel renders both teams' players, a countdown to closes_at and a Vote button, and handles the mvp_poll PubSub messages."""
        page = _Markup(_panel_html(tmp_path, {"poll": _js_poll()}, _js_view(pick=101)))
        players = [a for t, a in page.tags if t == "button" and a.get("class") == "poll-player"]
        assert [a["data-player"] for a in players] == ["101", "102", "201"]
        assert [a["aria-pressed"] for a in players] == ["true", "false", "false"]
        assert "Team11 vs Team12 · game 2" in page.text and "<b>P102</b>" in page.text
        assert "1:30 left · 3 votes" in page.text
        vote = [a for t, a in page.tags if t == "button" and a.get("id") == "btn-vote"]
        assert len(vote) == 1 and "disabled" not in vote[0]
        nothing_picked = _Markup(_panel_html(tmp_path, {"poll": _js_poll()}, _js_view()))
        assert "disabled" in [a for t, a in nothing_picked.tags if a.get("id") == "btn-vote"][0]
        js = _vext("panel.js")
        pubsub = _js_function(js, "onPubSub")
        assert 'msg.type === "mvp_poll"' in pubsub and 'msg.type === "mvp"' in pubsub and "loadPoll()" in pubsub
        assert 'ebsGet("/twitch/mvp-poll")' in _js_function(js, "loadPoll")
        assert '"/twitch/mvp-poll/" + encodeURIComponent(p.poll_id) + "/vote"' in _js_function(js, "sendVote")

    def test_vote_by_logged_in_viewer_without_account_is_recorded(self, db):
        """A vote-extension U... viewer with no soft or website account votes: one twitch_mvp_votes row, my_vote and total_votes == 1 in the response, and no users row is created."""
        _seed_ten(db)
        poll = _vopen(db)
        assert _users(db) == 0
        result = _vvote(db, poll["poll_id"], 104, "Unewcomer")
        assert result == {"poll_id": poll["poll_id"], "my_vote": 104, "total_votes": 1}
        rows = _votes(db, poll["poll_id"])
        assert [(r.twitch_user_id, r.player_id) for r in rows] == [("Unewcomer", 104)]
        assert _users(db) == 0
        view = _vget(db, "Unewcomer")["poll"]
        assert view["my_vote"] == 104
        assert view["voter"] == {"can_vote": True, "reason": "ok", "votes_from": None}

    def test_vote_by_logged_out_viewer_returns_403_twitch_login_required(self, db):
        """A vote-extension A... viewer gets 403 with detail twitch_login_required and no vote is stored."""
        _seed_ten(db)
        poll = _vopen(db)
        _raises(lambda: _vote(db, poll["poll_id"], 101, payload={**_ANON, "ext": "vote"}),
                403, "twitch_login_required")
        assert _votes(db, poll["poll_id"]) == []
        import twitch_mvp_poll
        view = twitch_mvp_poll.get_poll({**_ANON, "ext": "vote"}, db)["poll"]
        assert view["voter"]["can_vote"] is False and view["voter"]["reason"] == "login"

    def test_vote_panel_logged_out_viewer_sees_log_in_to_twitch_to_vote(self, tmp_path):
        """The vote panel shows "Log in to Twitch to vote." to a viewer whose opaque id does not start with U, and no Vote button."""
        js = _vext("panel.js")
        assert 'String(opaqueId || "").charAt(0) === "U"' in _js_function(js, "viewerLoggedIn")
        assert "loggedIn: viewerLoggedIn(ext.userId)" in _js_function(js, "render")
        page = _Markup(_panel_html(tmp_path, {"poll": _js_poll()}, _js_view(loggedIn=False)))
        assert "Log in to Twitch to vote." in page.text
        assert not page.has("button")
        assert "Player101" in page.text and "Share your Twitch identity" not in page.text

    def test_vote_from_game_extension_still_requires_joined_account(self, db):
        """A game-extension (or untagged) U... viewer who has not joined still gets 403 not_joined: the vote extension's rule does not loosen the full extension's."""
        _seed_ten(db)
        poll = _vopen(db)
        for payload in (_viewer("Ustranger"), {**_viewer("Ustranger"), "ext": "game"}):
            _raises(lambda: _vote(db, poll["poll_id"], 101, payload=payload), 403, "not_joined")
        assert _votes(db, poll["poll_id"]) == []

    def test_vote_change_replaces_previous_vote_one_row_per_viewer(self, db):
        """A second vote from the same vote-extension viewer replaces the first: one row for (poll, opaque id), the new player_id, total_votes still 1."""
        _seed_ten(db)
        poll = _vopen(db)
        _vvote(db, poll["poll_id"], 101, "Ua")
        result = _vvote(db, poll["poll_id"], 205, "Ua")
        assert result["my_vote"] == 205 and result["total_votes"] == 1
        rows = _votes(db, poll["poll_id"])
        assert [(r.twitch_user_id, r.player_id) for r in rows] == [("Ua", 205)]

    def test_vote_after_close_returns_409(self, db, monkeypatch):
        """A vote-extension vote after closes_at or after End now answers 409 poll_closed and the stored vote is unchanged."""
        _seed_ten(db)
        _seed_ten(db, match_id=1002)
        poll = _vopen(db)
        _vvote(db, poll["poll_id"], 101, "Ua")
        _vend(db, poll["poll_id"])
        _raises(lambda: _vvote(db, poll["poll_id"], 102, "Ua"), 409, "poll_closed")
        assert [r.player_id for r in _votes(db, poll["poll_id"])] == [101]
        _cancel(db, poll["poll_id"])
        timed = _vopen(db, match_id=1002, duration=60)
        _clock(monkeypatch, 60)
        _raises(lambda: _vvote(db, timed["poll_id"], 101, "Ub"), 409, "poll_closed")
        assert _votes(db, timed["poll_id"]) == []

    def test_votes_from_both_extensions_count_in_the_same_poll(self, db):
        """A joined game-extension viewer and an account-less vote-extension viewer vote in one poll and the closed tally counts both."""
        _seed_ten(db)
        _voter(db, "Ujoined")
        poll = _vopen(db)
        _vote(db, poll["poll_id"], 101, "Ujoined")
        _vvote(db, poll["poll_id"], 101, "Unoaccount")
        closed = _vend(db, poll["poll_id"])
        assert closed["total_votes"] == 2 and closed["winner_player_id"] == 101
        assert {r["player_id"]: r["votes"] for r in closed["results"]}[101] == 2

    def test_get_poll_while_open_shows_only_total_votes(self, db):
        """While open, the vote-extension poll view has total_votes and the viewer's own pick, and no per-player counts or shares."""
        _seed_ten(db)
        poll = _vopen(db)
        _vvote(db, poll["poll_id"], 101, "Ua")
        _vvote(db, poll["poll_id"], 202, "Ub")
        view = _vget(db, "Ua")["poll"]
        assert view["status"] == "open" and view["total_votes"] == 2 and view["my_vote"] == 101
        for key in ("results", "winner_player_id", "tied_player_ids"):
            assert key not in view
        assert "votes" not in json.dumps(view["teams"]) and "pct" not in json.dumps(view)

    def test_get_poll_after_close_shows_result_and_confirmed_mvp(self, db, monkeypatch):
        """After closing, any vote-extension viewer (voter or not) sees per-player results, and after Confirm MVP the confirmed player."""
        poll_id = _shared_poll(db, {"Ua": None, "Ub": None})
        for opaque_id in ("Ua", "Ubystander"):
            view = _vget(db, opaque_id)["poll"]
            assert view["status"] == "closed" and view["winner_player_id"] == 101
            top = view["results"][0]
            assert (top["player_id"], top["votes"], top["pct"]) == (101, 2, 100)
            assert view["confirmed_player_id"] is None
        _vconfirm(db, poll_id)
        view = _vget(db, "Ubystander")["poll"]
        assert view["status"] == "confirmed" and view["confirmed_player_id"] == 101
        assert view["my_vote"] is None

    def test_vote_panel_has_no_join_cards_roster_or_required_link(self, tmp_path):
        """The vote extension's viewer files (panel.html, panel.js, extension.js) call no /twitch/join, /twitch/draw, /twitch/roster or /twitch/me path and contain no Join button, card or roster markup, nor a link in the voting flow."""
        from tests.test_issue_195_twitch_extension_resubmission import _called_paths
        called = set()
        for name in ("panel.js", "extension.js"):
            called |= _called_paths(_vext(name))
        assert called == {"/twitch/mvp-poll", "/twitch/mvp-poll/{poll_id}/vote"}
        for name in ("panel.html", "panel.js", "extension.js"):
            source = _vext(name)
            for word in ("/twitch/join", "/twitch/draw", "/twitch/roster", "/twitch/me",
                         "/twitch/heartbeat", "/twitch/leave", "Join", "roster", "Roster"):
                assert word not in source, (name, word)
        page = _Markup(_vext("panel.html"))
        assert not page.has("a") and not page.has("form") and not page.has("input")
        for data, view in (({"poll": None, "last_mvp": None}, _js_view()),
                           ({"poll": _js_poll(my_vote=101)}, _js_view()),
                           ({"poll": _js_poll(status="closed", results=[], my_vote=101)}, _js_view())):
            rendered = _Markup(_panel_html(tmp_path, data, view))
            assert not rendered.has("a") and not rendered.has("form") and not rendered.has("input")

    def test_poll_responses_and_pubsub_contain_no_viewer_ids_or_hashes(self, db, monkeypatch):
        """No open, get, vote, end or confirm response and no PubSub message contains another viewer's opaque id, real Twitch id, account_hash or individual vote (_no_twitch_ids)."""
        chat, pubsub = _recorders(monkeypatch)
        _seed_ten(db)
        secrets = ["Uprivate1", "Uprivate2", "880011", "880022", _hash("880011"), _hash("880022")]
        opened = _vopen(db)
        poll_id = opened["poll_id"]
        responses = [opened,
                     _vvote(db, poll_id, 101, "Uprivate1", user_id="880011"),
                     _vvote(db, poll_id, 202, "Uprivate2", user_id="880022"),
                     _vget(db, "Uonlooker"), _vend(db, poll_id), _vget(db, "Uonlooker"),
                     _vconfirm(db, poll_id, player_id=101), _vget(db, "Uonlooker"),
                     _vget(db, "Uprivate1", user_id="880011")]
        assert len(_pending(db)) == 2
        for obj in responses + [m for _, m in pubsub] + [m for _, m in chat]:
            _no_twitch_ids(obj, *secrets)
            assert "account_hash" not in json.dumps(obj, default=str)


# ---------------------------------------------------------------------------
# Story 3 — Voters Can Win Tokens
# ---------------------------------------------------------------------------

def _account(db, username, real_id, tokens=5):
    """A website account connected with Twitch (twitch_account_id set)."""
    user = _website_user(db, username, tokens=tokens)
    user.twitch_account_id = real_id
    db.commit()
    return user


def _pending_row(db, real_id, poll_id, created_at=None, expires_in=3600):
    """A pending token for a Twitch id, written directly."""
    from models import TwitchPendingToken
    now = int(time.time())
    row = TwitchPendingToken(account_hash=_hash(real_id), poll_id=poll_id,
                             created_at=created_at if created_at is not None else now,
                             expires_at=now + expires_in)
    db.add(row)
    db.commit()
    return row


def _two_polls(db):
    """Two cancelled polls to hang pending tokens on (poll_id is a foreign key)."""
    _seed_ten(db)
    ids = []
    for _ in range(2):
        poll = _vopen(db)
        _cancel(db, poll["poll_id"], payload=_VOTE_BROADCASTER)
        ids.append(poll["poll_id"])
    return ids


class TestVotersCanWinTokens:

    def test_vote_panel_offers_identity_share_after_voting_with_reason(self, tmp_path):
        """After a vote, panel.js shows "Share your Twitch identity to enter the token drop" with one sentence of explanation and calls Twitch.ext.actions.requestIdShare() from its button; voting does not depend on it."""
        js = _vext("panel.js")
        before = _Markup(_panel_html(tmp_path, {"poll": _js_poll()}, _js_view(pick=101)))
        assert "Share your Twitch identity" not in before.text and not before.has("button", id="btn-share")
        assert before.has("button", id="btn-vote")                 # voting never waits for the share
        after = _Markup(_panel_html(tmp_path, {"poll": _js_poll(my_vote=101)}, _js_view()))
        assert "Share your Twitch identity to enter the token drop" in after.text
        assert "Kana Cards uses it only to give a token to voters picked in the drop." in after.text
        assert "Your vote counts either way." in after.text
        assert after.has("button", id="btn-share") and after.has("button", id="btn-vote")
        entered = _js_poll(my_vote=101, token_drop={"enabled": True, "entered": True, "pending_win": False})
        done = _Markup(_panel_html(tmp_path, {"poll": entered}, _js_view(shared=True)))
        assert "You are in the token drop for this vote." in done.text and not done.has("button", id="btn-share")
        share = _js_function(js, "shareIdentity")
        assert "actions.requestIdShare()" in share and "window.Twitch.ext.actions" in share
        assert 'shareBtn.addEventListener("click", shareIdentity)' in _js_function(js, "render")
        # After Twitch re-authorises with the shared identity, the same vote is sent once more.
        enter = _js_function(js, "enterDropIfShared")
        assert "sendVote(p.my_vote)" in enter and "state.enteredWith === ext.token" in enter
        assert "requestIdShare" not in _js_function(js, "castVote")

    def test_vote_with_shared_identity_stores_keyed_hash_never_the_twitch_id(self, db):
        """A vote-extension vote whose payload carries user_id stores account_hash == soft_accounts.starter_grant_hash(user_id) on the vote, and the real id appears in no column of twitch_mvp_votes."""
        poll_id = _shared_poll(db, {"Ua": "7700123"}, end=False)
        (row,) = _votes(db, poll_id)
        assert row.account_hash == _hash("7700123") and len(row.account_hash) == 64
        raw = db.execute(text("SELECT * FROM twitch_mvp_votes")).fetchall()
        assert "7700123" not in json.dumps([list(r) for r in raw], default=str)
        assert _vget(db, "Ua")["poll"]["token_drop"] == {"enabled": True, "entered": True,
                                                         "pending_win": False}

    def test_vote_without_shared_identity_is_counted_with_no_account_hash(self, db, monkeypatch):
        """A vote without user_id is stored and counted with account_hash NULL, and that voter is never in the drop pool."""
        poll_id = _shared_poll(db, {"Ua": None})
        (row,) = _votes(db, poll_id)
        assert row.account_hash is None
        assert _vget(db, "Ua")["poll"]["token_drop"]["entered"] is False
        result = _vconfirm(db, poll_id)
        assert result["token_drop"] == {"enabled": True, "winner_count": 0, "pool_size": 0,
                                        "already_dropped": False}
        assert _pending(db) == [] and _audits(db, "twitch_token_drop") == []

    def test_sharing_after_voting_enters_the_drop_on_the_next_request(self, db):
        """A viewer who voted without user_id and then votes again (or re-sends the vote) with user_id while the poll is open gets account_hash set on the existing row."""
        poll_id = _shared_poll(db, {"Ua": None}, end=False)
        assert _votes(db, poll_id)[0].account_hash is None
        _vvote(db, poll_id, 101, "Ua", user_id="7700123")
        (row,) = _votes(db, poll_id)
        assert row.account_hash == _hash("7700123") and row.player_id == 101
        # A later vote without the id (an older tab) changes the pick but keeps the entry.
        _vvote(db, poll_id, 102, "Ua")
        (row,) = _votes(db, poll_id)
        assert row.account_hash == _hash("7700123") and row.player_id == 102

    def test_confirm_drops_only_to_voters_who_shared(self, db, monkeypatch):
        """On Confirm MVP of a vote-extension poll, every token (credit or pending row) goes to a voter with an account_hash; voters who did not share get nothing."""
        known = _account(db, "alice", "9001")
        bystander = _website_user(db, "bob", twitch_user_id="Uplain1")
        poll_id = _shared_poll(db, {"Ushared1": "9001", "Ushared2": "9002", "Uplain1": None, "Uplain2": None})
        result = _vconfirm(db, poll_id)
        assert result["token_drop"]["winner_count"] == 2 and result["token_drop"]["pool_size"] == 2
        assert _tokens(db, known) == 6 and _tokens(db, bystander) == 5
        assert [p.account_hash for p in _pending(db)] == [_hash("9002")]

    def test_confirm_drops_at_most_twitch_drop_max_tokens_one_each(self, db, monkeypatch):
        """With _TWITCH_DROP_MAX patched to 2 and five sharing voters, exactly two distinct voters get exactly one token each."""
        import twitch
        monkeypatch.setattr(twitch, "_TWITCH_DROP_MAX", 2)
        accounts = {str(9000 + i): _account(db, f"user{i}", str(9000 + i)) for i in range(3)}
        voters = {f"Uv{i}": str(9000 + i) for i in range(5)}        # three with accounts, two without
        poll_id = _shared_poll(db, voters)
        result = _vconfirm(db, poll_id)
        credited = [rid for rid, user in accounts.items() if _tokens(db, user) == 6]
        assert all(_tokens(db, user) in (5, 6) for user in accounts.values())
        pending = _pending(db)
        assert len(credited) + len(pending) == 2
        assert len({p.account_hash for p in pending} | {_hash(r) for r in credited}) == 2
        assert result["token_drop"]["winner_count"] == 2 and result["token_drop"]["pool_size"] == 5
        from models import TwitchTokenDrop
        assert db.query(TwitchTokenDrop).one().count == 2

    def test_confirm_chat_message_says_how_many_tokens_dropped(self, db, monkeypatch):
        """The confirmation chat message for a vote-extension poll names the number of tokens dropped (known accounts plus pending), and has no drop sentence when nobody shared."""
        import twitch
        _account(db, "alice", "9001")
        poll_id = _shared_poll(db, {"Ua": "9001", "Ub": "9002", "Uc": None})
        chat, _ = _recorders(monkeypatch)
        _vconfirm(db, poll_id)
        assert chat == [("vote", "Match MVP by viewer vote: Player101 (100% of 3 votes)! 2 voters won a token.")]
        assert twitch._mvp_chat_text("P", 1, pool_empty=False, voters=True) == "Match MVP: P! 1 voter won a token."
        assert twitch._mvp_chat_text("P", 0, pool_empty=True, voters=True) == "Match MVP: P!"
        # Nobody shared: the MVP line alone, never "no joined viewers were watching".
        _seed_ten(db, match_id=1002)
        poll = _vopen(db, match_id=1002)
        _vvote(db, poll["poll_id"], 101, "Ud")
        _vend(db, poll["poll_id"])
        _confirm(db, poll["poll_id"], match_id=1002, payload=_VOTE_BROADCASTER)
        assert chat[-1] == ("vote", "Match MVP by viewer vote: Player101 (100% of 1 vote)!")

    def test_picked_voter_with_website_account_is_credited_at_once_and_audited(self, db, monkeypatch):
        """A picked voter whose Twitch id is a website account's twitch_account_id gets tokens + 1 at confirmation, no pending row, and the drop is audited like today's drops."""
        user = _account(db, "alice", "9001")
        poll_id = _shared_poll(db, {"Ua": "9001"})
        _vconfirm(db, poll_id)
        assert _tokens(db, user) == 6 and _pending(db) == []
        (detail,) = _audits(db, "twitch_token_drop")
        assert detail == (f"channel={_CHANNEL} match=1001 count=1 pool_size=1 excluded_new=0"
                          f" poll={poll_id} pending=0 winners=alice")

    def test_picked_voter_with_soft_account_is_credited_at_once(self, db, monkeypatch):
        """A picked voter whose Twitch id is on a soft account (identity share at Join in the full extension) gets the token on that account, with no pending row."""
        _join(db, "Ugameopaque", user_id="9001")
        soft = _user_by_opaque(db, "Ugameopaque")
        before = _tokens(db, soft)
        # The vote extension gives the same person another opaque id; the real id links them.
        poll_id = _shared_poll(db, {"Uvoteopaque": "9001"})
        _vconfirm(db, poll_id)
        assert _tokens(db, soft) == before + 1 and _pending(db) == []

    def test_picked_voter_with_no_account_gets_pending_token_expiring_in_60_days(self, db, monkeypatch):
        """A picked voter with no account gets one twitch_pending_tokens row: account_hash, poll_id, created_at, expires_at == created_at + 60 days, claimed_by_user_id and claimed_at NULL; no users row is created."""
        poll_id = _shared_poll(db, {"Ua": "9002"})
        before = int(time.time())
        _vconfirm(db, poll_id)
        (row,) = _pending(db)
        assert row.account_hash == _hash("9002") and row.poll_id == poll_id
        assert before <= row.created_at <= int(time.time())
        assert row.expires_at == row.created_at + 60 * 86400
        assert row.claimed_by_user_id is None and row.claimed_at is None
        assert _users(db) == 0

    def test_pending_tokens_store_keyed_hash_never_the_twitch_id(self, db, monkeypatch):
        """twitch_pending_tokens.account_hash equals starter_grant_hash(real id) and the real Twitch id appears in no column of the row or of the drop's audit detail."""
        import soft_accounts
        poll_id = _shared_poll(db, {"Ua": "7700123"})
        _vconfirm(db, poll_id)
        raw = db.execute(text("SELECT * FROM twitch_pending_tokens")).fetchall()
        assert len(raw) == 1 and soft_accounts.starter_grant_hash("7700123") in raw[0]
        dumped = json.dumps([list(r) for r in raw], default=str) + " ".join(_audits(db, "twitch_token_drop"))
        assert "7700123" not in dumped
        (detail,) = _audits(db, "twitch_token_drop")
        assert "pending=1 winners=" in detail and soft_accounts.starter_grant_hash("7700123") not in detail
        # Keyed: another SECRET_KEY gives another hash for the same id.
        monkeypatch.setenv("SECRET_KEY", "another-secret-key-for-issue-253-tests")
        assert soft_accounts.starter_grant_hash("7700123") != raw[0][1]

    def test_poll_view_tells_pending_winner_how_to_claim(self, db, monkeypatch, tmp_path):
        """After confirmation, the poll view for a picked account-less voter (same user_id in the payload) flags the win, and panel.js shows "You won a token. Claim it at kana-cards.com by signing in with Twitch."; other viewers get no such flag."""
        _account(db, "alice", "9001")
        poll_id = _shared_poll(db, {"Uwinner": "9002", "Uknown": "9001", "Uplain": None})
        assert _vget(db, "Uwinner", user_id="9002")["poll"]["token_drop"]["pending_win"] is False
        _vconfirm(db, poll_id)
        assert _vget(db, "Uwinner", user_id="9002")["poll"]["token_drop"]["pending_win"] is True
        for opaque_id, real_id in (("Uwinner", None), ("Uknown", "9001"), ("Uplain", None), ("Uother", "9003")):
            assert _vget(db, opaque_id, user_id=real_id)["poll"]["token_drop"]["pending_win"] is False
        won = _js_poll(status="confirmed", confirmed_player_id=101, my_vote=101, results=[],
                       token_drop={"enabled": True, "entered": True, "pending_win": True})
        text_won = _Markup(_panel_html(tmp_path, {"poll": won}, _js_view())).text
        assert "You won a token. Claim it at kana-cards.com by signing in with Twitch." in text_won
        lost = dict(won, token_drop={"enabled": True, "entered": True, "pending_win": False})
        assert "You won a token" not in _Markup(_panel_html(tmp_path, {"poll": lost}, _js_view())).text

    def test_confirm_twice_does_not_drop_twice(self, db, monkeypatch):
        """A repeated Confirm MVP for the same poll credits no account again and adds no second pending row (unique account_hash + poll_id)."""
        import twitch_vote_rewards
        user = _account(db, "alice", "9001")
        poll_id = _shared_poll(db, {"Ua": "9001", "Ub": "9002"})
        _vconfirm(db, poll_id)
        _raises(lambda: _vconfirm(db, poll_id), 409, "The vote is not closed")
        assert _tokens(db, user) == 6 and len(_pending(db)) == 1
        # The drop itself is once per match too, whatever calls it.
        assert twitch_vote_rewards.drop_for_poll(db, _poll_row(db, poll_id)) == ([], 0, 0, True)
        db.commit()
        assert _tokens(db, user) == 6 and len(_pending(db)) == 1
        assert len(_audits(db, "twitch_token_drop")) == 1

    def test_connect_twitch_claims_unexpired_pending_tokens_once(self, db, monkeypatch):
        """twitch_oauth.connect_account for a Twitch id with two unexpired pending tokens credits the website account 2 tokens in the same commit and sets claimed_by_user_id and claimed_at on both; connecting again (after disconnect) credits nothing more."""
        import twitch_oauth
        monkeypatch.setenv("TWITCH_CONNECT_BONUS_TOKENS", "0")      # only the pending tokens move the balance
        first, second = _two_polls(db)
        _pending_row(db, "9002", first)
        _pending_row(db, "9002", second)
        _pending_row(db, "9999", first)                              # someone else's
        user = _website_user(db, "alice")
        assert twitch_oauth.connect_account(db, user, "9002") == "connected"
        assert user.tokens == 7                                      # refreshed after the commit
        rows = {p.account_hash: p for p in _pending(db) if p.account_hash == _hash("9999")}
        assert rows[_hash("9999")].claimed_at is None
        mine = [p for p in _pending(db) if p.account_hash == _hash("9002")]
        assert [p.claimed_by_user_id for p in mine] == [user.id, user.id]
        assert all(p.claimed_at is not None for p in mine)
        assert _audits(db, "twitch_pending_tokens_claimed") == [f"user_id={user.id} count=2"]
        twitch_oauth.disconnect(db, {"user_id": user.id, "username": "alice", "is_admin": False})
        db.commit()
        db.refresh(user)
        assert twitch_oauth.connect_account(db, user, "9002") == "connected"
        assert _tokens(db, user) == 7
        assert len(_audits(db, "twitch_pending_tokens_claimed")) == 1

    def test_join_with_identity_share_claims_pending_tokens_once(self, db, monkeypatch):
        """twitch.join in the full extension with user_id in the payload credits the soft account its unexpired pending tokens and marks them claimed; a second join credits nothing more."""
        first, second = _two_polls(db)
        _pending_row(db, "9002", first)
        _pending_row(db, "9002", second)
        joined = _join(db, "Ugame1", user_id="9002")
        soft = _user_by_opaque(db, "Ugame1")
        assert joined["created"] is True and joined["tokens"] == 7 and _tokens(db, soft) == 7
        assert [p.claimed_by_user_id for p in _pending(db)] == [soft.id, soft.id]
        again = _join(db, "Ugame1", user_id="9002")
        assert again["created"] is False and _tokens(db, soft) == 7
        assert _audits(db, "twitch_pending_tokens_claimed") == [f"user_id={soft.id} count=2"]

    def test_existing_account_sharing_identity_later_claims_pending_tokens(self, db, monkeypatch):
        """A joined soft account that had no Twitch id gets its pending tokens when a later panel request records the identity share (_record_identity_share)."""
        import twitch
        (first, _) = _two_polls(db)
        _pending_row(db, "9002", first)
        _join(db, "Ugame1")
        soft = _user_by_opaque(db, "Ugame1")
        assert _tokens(db, soft) == 5 and _pending(db)[0].claimed_at is None
        state = twitch.me(payload=_viewer("Ugame1", user_id="9002"), db=db)
        assert state["tokens"] == 6 and _tokens(db, soft) == 6
        (row,) = _pending(db)
        assert row.claimed_by_user_id == soft.id and row.claimed_at is not None

    def test_concurrent_claims_credit_a_pending_token_once(self, monkeypatch, tmp_path):
        """Two threads claiming the same pending token at once (connect and join, barrier-released, shared engine) leave it claimed by exactly one account and credit exactly one token in total."""
        from database import Base, credit_tokens
        from models import TwitchMvpPoll, TwitchPendingToken, User
        import twitch_vote_rewards
        engine = create_engine(f"sqlite:///{tmp_path / 'claims.db'}",
                               connect_args={"check_same_thread": False, "timeout": 30})
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)

        def naive_claim(s, user, real_id, wait):
            """The claim without its guard: read the unclaimed rows, then write."""
            rows = s.query(TwitchPendingToken).filter_by(account_hash=_hash(real_id), claimed_at=None).all()
            wait()
            for row in rows:
                row.claimed_by_user_id, row.claimed_at = user.id, int(time.time())
            credit_tokens(s, user.id, len(rows))
            return len(rows)

        def guarded_claim(s, user, real_id, wait):
            wait()
            return twitch_vote_rewards.claim_pending(s, user, real_id)

        def race(claim, real_id):
            with Session() as s:
                now = int(time.time())
                poll = TwitchMvpPoll(channel_id="c", match_id=1, status="confirmed", opened_at=now,
                                     closes_at=now, extension="vote")
                users = [User(username=f"u{real_id}{i}", tokens=0, created_at=now) for i in range(2)]
                s.add_all([poll, *users])
                s.flush()
                s.add(TwitchPendingToken(account_hash=_hash(real_id), poll_id=poll.id,
                                         created_at=now, expires_at=now + 3600))
                s.commit()
                ids = [u.id for u in users]
            barrier = threading.Barrier(2, timeout=20)
            claimed, errors = [], []

            def worker(uid):
                try:
                    with Session() as s:
                        user = s.get(User, uid)
                        claimed.append(claim(s, user, real_id, barrier.wait))
                        s.commit()
                except Exception as exc:        # pragma: no cover - reported below
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(uid,)) for uid in ids]
            for t in threads:
                t.start()
            for t in threads:
                t.join(30)
            assert errors == []
            with Session() as s:
                credited = sum(u.tokens for u in s.query(User).filter(User.id.in_(ids)))
                row = s.query(TwitchPendingToken).filter_by(account_hash=_hash(real_id)).one()
                return sorted(claimed), credited, row.claimed_by_user_id in ids

        # The race is real: without the guard both threads credit the same token.
        assert race(naive_claim, "111") == ([1, 1], 2, True)
        assert race(guarded_claim, "222") == ([0, 1], 1, True)
        engine.dispose()

    def test_one_account_cannot_collect_pending_tokens_of_several_twitch_accounts(self, db, monkeypatch):
        """Security review: an account that claimed tokens won by one Twitch id claims nothing after disconnecting and connecting another; those tokens stay unclaimed, the refusal is audited, and the claim record outlives the token's own expiry for 60 days."""
        import twitch_oauth
        import twitch_vote_rewards
        monkeypatch.setenv("TWITCH_CONNECT_BONUS_TOKENS", "0")
        first, second = _two_polls(db)
        _pending_row(db, "9002", first)
        alt_a = _pending_row(db, "9003", first)
        alt_b = _pending_row(db, "9003", second)
        user = _website_user(db, "alice")
        acting = {"user_id": user.id, "username": "alice", "is_admin": False}
        assert twitch_oauth.connect_account(db, user, "9002") == "connected"
        assert _tokens(db, user) == 6
        twitch_oauth.disconnect(db, acting)
        db.commit()
        db.refresh(user)
        assert twitch_oauth.connect_account(db, user, "9003") == "connected"     # connecting still works
        assert _tokens(db, user) == 6
        by_id = {p.id: p for p in _pending(db)}
        assert by_id[alt_a.id].claimed_at is None and by_id[alt_b.id].claimed_at is None
        assert _audits(db, "twitch_pending_tokens_refused") == [
            f"user_id={user.id} count=2 reason=other_twitch_account"]
        # Another account connecting that Twitch id later still gets them.
        twitch_oauth.disconnect(db, acting)
        db.commit()
        other = _website_user(db, "bob")
        assert twitch_oauth.connect_account(db, other, "9003") == "connected"
        assert _tokens(db, other) == 7
        # The same Twitch id again is not "another account": later wins are claimed.
        third = _vopen(db)
        _cancel(db, third["poll_id"], payload=_VOTE_BROADCASTER)
        _pending_row(db, "9003", third["poll_id"])
        assert twitch_vote_rewards.claim_pending(db, other, "9003") == 1
        db.commit()
        # The claim record is kept 60 days from the claim, not from the token's expiry.
        now = int(time.time())
        assert twitch_vote_rewards.purge_expired(db, now + 59 * 86400) == 0
        assert twitch_vote_rewards.claim_pending(db, user, "9004") == 0
        assert twitch_vote_rewards.purge_expired(db, now + 60 * 86400 + 5) == 4
        assert _pending(db) == []

    def test_expired_pending_token_is_not_claimed(self, db, monkeypatch):
        """A pending token whose expires_at has passed is not credited on connect or join and stays unclaimed; an unexpired one beside it is credited."""
        import twitch_oauth
        import twitch_vote_rewards
        monkeypatch.setenv("TWITCH_CONNECT_BONUS_TOKENS", "0")
        first, second = _two_polls(db)
        expired = _pending_row(db, "9002", first, expires_in=-1)
        live = _pending_row(db, "9002", second)
        expired_other = _pending_row(db, "9003", first, expires_in=-1)
        user = _website_user(db, "alice")
        twitch_oauth.connect_account(db, user, "9002")
        assert _tokens(db, user) == 6
        _join(db, "Ugame9", user_id="9003")
        assert _tokens(db, _user_by_opaque(db, "Ugame9")) == 5
        by_id = {p.id: p for p in _pending(db)}
        assert by_id[live.id].claimed_by_user_id == user.id
        assert by_id[expired.id].claimed_at is None and by_id[expired_other.id].claimed_at is None
        # The daily job removes what has expired and keeps the rest.
        assert twitch_vote_rewards.purge_expired(db) == 2
        assert [p.id for p in _pending(db)] == [live.id]

    def test_claim_with_no_pending_tokens_credits_nothing(self, db, monkeypatch):
        """Connecting or joining with a Twitch id that has no pending tokens changes no balance beyond today's starter rules and writes no claim audit."""
        import twitch_oauth
        import twitch_vote_rewards
        monkeypatch.setenv("TWITCH_CONNECT_BONUS_TOKENS", "0")
        user = _website_user(db, "alice")
        assert twitch_oauth.connect_account(db, user, "9002") == "connected"
        assert _tokens(db, user) == 5
        assert _join(db, "Ugame1", user_id="9003")["tokens"] == 5
        assert twitch_vote_rewards.claim_pending(db, user, None) == 0
        assert _audits(db, "twitch_pending_tokens_claimed") == [] and _pending(db) == []

    def test_tokens_switch_off_voting_works_and_nothing_drops(self, db, monkeypatch):
        """With TWITCH_VOTE_TOKENS_ENABLED=false, vote-extension viewers still vote and the MVP is confirmed, no account_hash is stored, no account is credited, no pending row is created and the chat message has no drop sentence."""
        from models import TwitchMVP, TwitchTokenDrop
        monkeypatch.setenv("TWITCH_VOTE_TOKENS_ENABLED", "false")
        user = _account(db, "alice", "9001")
        poll_id = _shared_poll(db, {"Ua": "9001", "Ub": "9002"})
        assert [v.account_hash for v in _votes(db, poll_id)] == [None, None]
        chat, _ = _recorders(monkeypatch)
        result = _vconfirm(db, poll_id)
        assert result["token_drop"] == {"enabled": False, "winner_count": 0, "pool_size": 0,
                                        "already_dropped": False}
        assert db.query(TwitchMVP).one().player_id == 101
        assert _tokens(db, user) == 5 and _pending(db) == []
        assert db.query(TwitchTokenDrop).count() == 0 and _audits(db, "twitch_token_drop") == []
        assert chat == [("vote", "Match MVP by viewer vote: Player101 (100% of 2 votes)!")]

    def test_tokens_switch_off_hides_share_prompt(self, db, monkeypatch, tmp_path):
        """With TWITCH_VOTE_TOKENS_ENABLED=false the poll view tells the panel tokens are off, and panel.js shows the identity-share prompt only when that flag is on."""
        import twitch_vote_rewards
        poll_id = _shared_poll(db, {"Ua": None}, end=False)
        assert _vget(db, "Ua")["poll"]["token_drop"]["enabled"] is True
        for value in ("false", "0", "off", "No"):
            monkeypatch.setenv("TWITCH_VOTE_TOKENS_ENABLED", value)
            assert twitch_vote_rewards.tokens_enabled() is False
        assert _vget(db, "Ua")["poll"]["token_drop"] == {"enabled": False, "entered": False,
                                                         "pending_win": False}
        monkeypatch.delenv("TWITCH_VOTE_TOKENS_ENABLED")
        monkeypatch.setenv("TWITCH_DROPS_ENABLED", "false")          # the global kill switch covers it too
        assert _vget(db, "Ua")["poll"]["token_drop"]["enabled"] is False
        off = _js_poll(my_vote=101, token_drop={"enabled": False, "entered": False, "pending_win": False})
        page = _Markup(_panel_html(tmp_path, {"poll": off}, _js_view()))
        assert "Share your Twitch identity" not in page.text and not page.has("button", id="btn-share")
        assert page.has("button", id="btn-vote") and "You voted for Player101" in page.text
        assert "if (!drop.enabled || !poll.my_vote) return \"\";" in _js_function(_vext("panel.js"), "dropStepHtml")

    def test_game_extension_poll_keeps_todays_presence_drop(self, db, monkeypatch):
        """Confirming a poll opened by the game extension still runs _execute_token_drop over present joined viewers and creates no pending tokens."""
        from tests.test_issue_157_twitch_extension_policy_compliance import _chat_recorder
        chat = _chat_recorder(monkeypatch)                           # the two-argument call still works
        closed = _closed_poll(db, monkeypatch, {"Ujoined1": 101, "Ujoined2": 101})
        _present(db, "Ujoined1")
        before = _tokens(db, _user_by_opaque(db, "Ujoined1"))
        result = _confirm(db, closed["poll_id"])
        assert result["token_drop"] == {"enabled": True, "winner_count": 1, "pool_size": 1,
                                        "already_dropped": False}
        assert _tokens(db, _user_by_opaque(db, "Ujoined1")) == before + 1
        assert _tokens(db, _user_by_opaque(db, "Ujoined2")) == before
        assert _pending(db) == [] and all(v.account_hash is None for v in _votes(db, closed["poll_id"]))
        assert chat == ["MVP vote open for Team11 vs Team12, game 1: vote in the Kana Cards panel. Closes in 2 min.",
                        "Match MVP by viewer vote: Player101 (100% of 2 votes)! 1 viewer received a token."]
        assert "poll=" not in _audits(db, "twitch_token_drop")[0]


# ---------------------------------------------------------------------------
# Story 4 — The Operator Sets Up the Second Extension
# ---------------------------------------------------------------------------

@pytest.fixture
def two_ext_env(monkeypatch):
    """The real JWT path with both extensions configured (no TWITCH_LOCAL_DEV bypass)."""
    monkeypatch.delenv("TWITCH_LOCAL_DEV", raising=False)
    monkeypatch.setenv("TWITCH_EXTENSION_CLIENT_ID", _GAME_ID)
    monkeypatch.setenv("TWITCH_EXTENSION_SECRET", _GAME_B64)
    monkeypatch.setenv("TWITCH_EXTENSION_VERSION", "1.4.0")
    monkeypatch.setenv("TWITCH_VOTE_EXTENSION_CLIENT_ID", _VOTE_ID)
    monkeypatch.setenv("TWITCH_VOTE_EXTENSION_SECRET", _VOTE_B64)
    monkeypatch.setenv("TWITCH_VOTE_EXTENSION_VERSION", "1.0.0")


def _verify(token, origin=None):
    import twitch
    request = None
    if origin is not None:
        from types import SimpleNamespace
        request = SimpleNamespace(headers={"origin": origin}, state=SimpleNamespace())
    return twitch.verify_twitch_jwt(request, token)


def _signed_claims(secret, **claims):
    import jwt as pyjwt
    body = {"exp": int(time.time()) + 300, "opaque_user_id": "Uv1", "role": "viewer",
            "channel_id": _CHANNEL, **claims}
    return "Bearer " + pyjwt.encode(body, secret, algorithm="HS256")


def _both_app(db):
    """The /twitch routes of both modules behind the real JWT check."""
    import twitch_mvp_poll
    from fastapi.testclient import TestClient
    app = _twitch_app(db)
    app.include_router(twitch_mvp_poll.router)
    return TestClient(app)


def _capture_posts(monkeypatch):
    """Record what would be sent to Twitch instead of sending it."""
    import twitch
    posts = []

    class _Ok:
        ok, status_code, text = True, 204, ""

    def post(url, headers=None, json=None, timeout=None):
        posts.append({"url": url, "headers": headers, "json": json})
        return _Ok()

    monkeypatch.setattr(twitch._requests, "post", post)
    return posts


def _signer(post):
    """Which extension's secret signed a captured request's token: game, vote or None."""
    import jwt as pyjwt
    token = post["headers"]["Authorization"].removeprefix("Bearer ")
    for name, secret in (("game", _SECRET_BYTES), ("vote", _VOTE_SECRET_BYTES)):
        try:
            pyjwt.decode(token, secret, algorithms=["HS256"])
            return name
        except pyjwt.InvalidTokenError:
            continue
    return None


class TestOperatorSetsUpSecondExtension:

    def test_verify_twitch_jwt_accepts_game_secret_and_tags_ext_game(self, two_ext_env):
        """A token signed with TWITCH_EXTENSION_SECRET is accepted and the returned payload has ext == "game"."""
        payload = _verify(_signed("Ugame1", user_id="42"))
        assert payload["ext"] == "game"
        assert (payload["opaque_user_id"], payload["user_id"], payload["channel_id"]) == ("Ugame1", "42", _CHANNEL)

    def test_verify_twitch_jwt_accepts_vote_secret_and_tags_ext_vote(self, two_ext_env):
        """A token signed with TWITCH_VOTE_EXTENSION_SECRET is accepted and the returned payload has ext == "vote"."""
        import twitch
        payload = _verify(_signed("Uvote1", role="broadcaster", secret=_VOTE_SECRET_BYTES))
        assert payload["ext"] == "vote" and payload["role"] == "broadcaster"
        assert twitch.payload_ext(payload) == "vote"
        assert twitch.payload_ext({"role": "viewer"}) == "game"      # untagged: the full extension

    def test_verify_twitch_jwt_rejects_token_signed_with_neither_secret(self, two_ext_env):
        """A token signed with a third secret answers 401 "Invalid Twitch token", and an expired token signed with the vote secret answers 401 "Twitch token expired"."""
        _raises(lambda: _verify(_signed("Ux", secret=_THIRD_SECRET)), 401, "Invalid Twitch token")
        _raises(lambda: _verify("Bearer not-a-token"), 401, "Invalid Twitch token")
        expired = _signed_claims(_VOTE_SECRET_BYTES, exp=int(time.time()) - 10)
        _raises(lambda: _verify(expired), 401, "Twitch token expired")
        # A vote-signed token for Twitch's own APIs is no viewer token either.
        _raises(lambda: _verify(_signed_claims(_VOTE_SECRET_BYTES, role="external")), 403)

    def test_verify_twitch_jwt_ignores_ext_claim_in_token(self, two_ext_env):
        """A game-signed token carrying its own "ext": "vote" claim is tagged "game": the tag comes from the secret that verified it, never from the token."""
        assert _verify(_signed_claims(_SECRET_BYTES, ext="vote"))["ext"] == "game"
        assert _verify(_signed_claims(_VOTE_SECRET_BYTES, ext="game"))["ext"] == "vote"

    def test_verify_twitch_jwt_without_vote_secret_still_accepts_game_tokens(self, two_ext_env, monkeypatch):
        """With TWITCH_VOTE_EXTENSION_SECRET unset, game tokens are accepted as today and a vote-signed token answers 401, not 500."""
        import twitch
        monkeypatch.delenv("TWITCH_VOTE_EXTENSION_SECRET")
        assert _verify(_signed("Ugame1"))["ext"] == "game"
        _raises(lambda: _verify(_signed("Uvote1", secret=_VOTE_SECRET_BYTES)), 401, "Invalid Twitch token")
        assert twitch.traffic_snapshot()["failures"] == {"expired": 0, "invalid": 1, "not_configured": 0}
        # Neither secret set is still the server's fault.
        monkeypatch.delenv("TWITCH_EXTENSION_SECRET")
        _raises(lambda: _verify(_signed("Ugame1")), 500, "TWITCH_EXTENSION_SECRET not configured")
        # Only the vote extension configured: its tokens work, the full extension's are refused.
        monkeypatch.setenv("TWITCH_VOTE_EXTENSION_SECRET", _VOTE_B64)
        assert _verify(_signed("Uvote1", secret=_VOTE_SECRET_BYTES))["ext"] == "vote"
        _raises(lambda: _verify(_signed("Ugame1")), 401, "Invalid Twitch token")

    def test_verify_twitch_jwt_counts_ok_and_failures_per_extension(self, two_ext_env):
        """traffic_snapshot reports ok and failure counts for the game and the vote extension separately: a good vote token raises only the vote count, an expired vote token only the vote extension's "expired"."""
        import twitch
        zero = {"expired": 0, "invalid": 0, "not_configured": 0}
        _verify(_signed("Uvote1", secret=_VOTE_SECRET_BYTES))
        snap = twitch.traffic_snapshot()
        assert snap["last_ok_at"] is None and isinstance(snap["vote"]["last_ok_at"], int)
        _raises(lambda: _verify(_signed_claims(_VOTE_SECRET_BYTES, exp=int(time.time()) - 10)), 401)
        snap = twitch.traffic_snapshot()
        assert snap["vote"]["failures"] == {**zero, "expired": 1} and snap["failures"] == zero
        assert isinstance(snap["vote"]["last_failure_at"], int) and snap["last_failure_at"] is None
        _verify(_signed("Ugame1"))
        _raises(lambda: _verify(_signed_claims(_SECRET_BYTES, exp=int(time.time()) - 10)), 401)
        snap = twitch.traffic_snapshot()
        assert isinstance(snap["last_ok_at"], int) and snap["failures"] == {**zero, "expired": 1}
        assert snap["vote"]["failures"] == {**zero, "expired": 1}
        # A token no secret verifies is filed by the request's origin: the vote extension's
        # own origin, or else the full extension.
        junk = _signed("Ux", secret=_THIRD_SECRET)
        _raises(lambda: _verify(junk, origin=f"https://{_VOTE_ID}.ext-twitch.tv"), 401)
        _raises(lambda: _verify(junk, origin=f"https://{_VOTE_ID}.ext-twitch.tv.evil.example"), 401)
        _raises(lambda: _verify(junk), 401)
        snap = twitch.traffic_snapshot()
        assert snap["vote"]["failures"]["invalid"] == 1 and snap["failures"]["invalid"] == 2

    def test_game_routes_refuse_vote_extension_tokens_with_403(self, two_ext_env):
        """Through TestClient with a vote-signed token, POST /twitch/join, the draw routes and the roster routes answer 403 and create no account, card or roster change."""
        from models import Card, TwitchPresence
        db = _shared_db()
        client = _both_app(db)
        headers = {"Authorization": _signed("Uvote1", secret=_VOTE_SECRET_BYTES)}
        swap = {"bench_card_id": 1, "active_card_id": 2, "slot_index": 0}
        calls = [("post", "/twitch/join", None), ("post", "/twitch/draw", None),
                 ("post", "/twitch/draw/booster/11", None), ("get", "/twitch/teams", None),
                 ("get", "/twitch/me", None), ("post", "/twitch/roster/activate/1", None),
                 ("post", "/twitch/roster/deactivate/1", None), ("post", "/twitch/roster/swap", swap),
                 ("post", "/twitch/heartbeat", None), ("post", "/twitch/leave", None)]
        for method, path, body in calls:
            resp = client.request(method.upper(), path, headers=headers, json=body)
            assert resp.status_code == 403, (path, resp.status_code, resp.text)
            assert resp.json()["detail"] == "This route is not available to the MVP Vote extension"
        assert _users(db) == 0 and db.query(Card).count() == 0 and db.query(TwitchPresence).count() == 0
        db.close()

    def test_game_routes_accept_game_extension_tokens(self, two_ext_env):
        """With a game-signed token, POST /twitch/join still answers 200 and creates the soft account (require_game_extension lets it through)."""
        import twitch
        db = _shared_db()
        client = _both_app(db)
        resp = client.post("/twitch/join", headers={"Authorization": _signed("Ugame1")})
        assert resp.status_code == 200 and resp.json()["created"] is True
        assert _user_by_opaque(db, "Ugame1") is not None
        assert client.get("/twitch/me", headers={"Authorization": _signed("Ugame1")}).json()["joined"] is True
        # The guard is a plain function too: untagged and game payloads pass through unchanged.
        for payload in ({"role": "viewer"}, {"role": "viewer", "ext": "game"}):
            assert twitch.require_game_extension(payload) is payload
        _raises(lambda: twitch.require_game_extension({"role": "viewer", "ext": "vote"}), 403)
        db.close()

    def test_poll_routes_accept_tokens_from_both_extensions(self, two_ext_env):
        """Through TestClient, GET /twitch/mvp-poll answers 200 for a game-signed and for a vote-signed token."""
        db = _shared_db()
        client = _both_app(db)
        game = client.get("/twitch/mvp-poll", headers={"Authorization": _signed("Ugame1")})
        vote = client.get("/twitch/mvp-poll",
                          headers={"Authorization": _signed("Uvote1", secret=_VOTE_SECRET_BYTES)})
        assert game.status_code == 200 and game.json() == {"poll": None}
        assert vote.status_code == 200 and vote.json() == {"poll": None, "last_mvp": None}
        other = client.get("/twitch/mvp-poll", headers={"Authorization": _signed("Ux", secret=_THIRD_SECRET)})
        assert other.status_code == 401
        for path in ("/twitch/matches/current", "/twitch/check"):
            resp = client.get(path, headers={"Authorization": _signed("Uvote1", role="broadcaster",
                                                                       secret=_VOTE_SECRET_BYTES)})
            assert resp.status_code == 200, path
        db.close()

    def test_pubsub_for_vote_extension_poll_uses_vote_extension_credentials(self, db, monkeypatch, two_ext_env):
        """PubSub messages for a poll opened by the vote extension are signed with TWITCH_VOTE_EXTENSION_SECRET and sent with TWITCH_VOTE_EXTENSION_CLIENT_ID as Client-Id; a game-extension poll uses the game credentials."""
        posts = _capture_posts(monkeypatch)
        _seed_ten(db)
        poll = _vopen(db)
        _vend(db, poll["poll_id"])
        _cancel(db, poll["poll_id"], payload=_VOTE_BROADCASTER)
        pubsub = [p for p in posts if p["url"] == "https://api.twitch.tv/helix/extensions/pubsub"]
        assert [json.loads(p["json"]["message"])["state"] for p in pubsub] == ["open", "closed", "cancelled"]
        assert {p["headers"]["Client-Id"] for p in pubsub} == {_VOTE_ID}
        assert {_signer(p) for p in pubsub} == {"vote"}
        del posts[:]
        game = _open(db)
        _cancel(db, game["poll_id"])
        pubsub = [p for p in posts if p["url"].endswith("/extensions/pubsub")]
        assert len(pubsub) == 2 and {p["headers"]["Client-Id"] for p in pubsub} == {_GAME_ID}
        assert {_signer(p) for p in pubsub} == {"game"}

    def test_chat_for_vote_extension_poll_uses_vote_extension_credentials(self, db, monkeypatch, two_ext_env):
        """The open and confirmation chat messages of a vote-extension poll are posted with the vote extension's client id, secret and version as extension_id / extension_version; a game-extension poll uses the game extension's."""
        posts = _capture_posts(monkeypatch)
        _seed_ten(db)
        _seed_ten(db, match_id=1002)
        poll = _vopen(db)
        _vvote(db, poll["poll_id"], 101, "Ua")
        _vend(db, poll["poll_id"])
        # Confirmed by a broadcaster token of either kind, the messages follow the poll.
        _confirm(db, poll["poll_id"])
        chat = [p for p in posts if "/extensions/chat" in p["url"]]
        assert [p["json"]["text"].split(":")[0] for p in chat] == ["MVP vote open for Team11 vs Team12, game 1",
                                                                  "Match MVP by viewer vote"]
        for p in chat:
            assert p["url"] == f"https://api.twitch.tv/helix/extensions/chat?broadcaster_id={_CHANNEL}"
            assert p["headers"]["Client-Id"] == _VOTE_ID and _signer(p) == "vote"
            assert (p["json"]["extension_id"], p["json"]["extension_version"]) == (_VOTE_ID, "1.0.0")
        assert all(p["headers"]["Client-Id"] == _VOTE_ID for p in posts)
        del posts[:]
        _voter(db, "Ujoined")
        game = _open(db, match_id=1002)
        _vote(db, game["poll_id"], 201, "Ujoined")
        _end(db, game["poll_id"])
        _confirm(db, game["poll_id"], player_id=201, match_id=1002, payload=_VOTE_BROADCASTER)
        chat = [p for p in posts if "/extensions/chat" in p["url"]]
        assert len(chat) == 2
        for p in chat:
            assert p["headers"]["Client-Id"] == _GAME_ID and _signer(p) == "game"
            assert (p["json"]["extension_id"], p["json"]["extension_version"]) == (_GAME_ID, "1.4.0")

    def test_messages_skipped_when_opening_extension_has_no_credentials(self, db, monkeypatch, two_ext_env):
        """With the vote extension's client id or secret unset, a vote-extension poll's PubSub and chat sends are skipped without raising and never fall back to the game extension's credentials."""
        import twitch
        posts = _capture_posts(monkeypatch)
        _seed_ten(db)
        monkeypatch.delenv("TWITCH_VOTE_EXTENSION_CLIENT_ID")
        poll = _vopen(db)
        _vvote(db, poll["poll_id"], 101, "Ua")
        _vend(db, poll["poll_id"])
        assert _vconfirm(db, poll["poll_id"])["player_id"] == 101
        assert posts == []
        monkeypatch.setenv("TWITCH_VOTE_EXTENSION_CLIENT_ID", _VOTE_ID)
        monkeypatch.delenv("TWITCH_VOTE_EXTENSION_SECRET")
        twitch.broadcast_as("vote", _CHANNEL, {"type": "mvp_poll"})
        twitch.chat_as("vote", _CHANNEL, "hello")
        assert posts == []
        # Without its version only chat is skipped; the full extension is unaffected throughout.
        monkeypatch.setenv("TWITCH_VOTE_EXTENSION_SECRET", _VOTE_B64)
        monkeypatch.delenv("TWITCH_VOTE_EXTENSION_VERSION")
        twitch.chat_as("vote", _CHANNEL, "hello")
        assert posts == []
        twitch.broadcast_as("vote", _CHANNEL, {"type": "mvp_poll"})
        twitch.chat_as("game", _CHANNEL, "hello")
        assert [p["headers"]["Client-Id"] for p in posts] == [_VOTE_ID, _GAME_ID]

    def test_cors_allows_both_extension_origins(self, monkeypatch):
        """With both client ids set, a preflight from https://<game id>.ext-twitch.tv and one from https://<vote id>.ext-twitch.tv each get Access-Control-Allow-Origin equal to that exact origin."""
        from tests.test_issue_136_security_audit_3 import _build_main_client, _preflight
        import twitch_status
        client = _build_main_client(monkeypatch, {"TWITCH_EXTENSION_CLIENT_ID": _GAME_ID,
                                                  "TWITCH_VOTE_EXTENSION_CLIENT_ID": _VOTE_ID})
        for client_id in (_GAME_ID, _VOTE_ID):
            origin = f"https://{client_id}.ext-twitch.tv"
            resp = _preflight(client, origin)
            assert resp.status_code == 200
            assert resp.headers.get("access-control-allow-origin") == origin
        # Only the vote extension configured: its origin alone is allowed.
        client = _build_main_client(monkeypatch, {"TWITCH_VOTE_EXTENSION_CLIENT_ID": _VOTE_ID})
        assert _preflight(client, f"https://{_VOTE_ID}.ext-twitch.tv").headers.get(
            "access-control-allow-origin") == f"https://{_VOTE_ID}.ext-twitch.tv"
        assert "access-control-allow-origin" not in _preflight(client, f"https://{_GAME_ID}.ext-twitch.tv").headers
        assert twitch_status.extension_origin_regex(["a.b", "", "a.b", " c "]) == r"^https://(?:a\.b|c)\.ext-twitch\.tv$"
        assert twitch_status.extension_origin_regex(["", "  "]) is None

    def test_cors_refuses_any_other_origin(self, monkeypatch):
        """An origin with another client id, a suffixed or prefixed look-alike of the vote origin, or http instead of https gets no Access-Control-Allow-Origin, and is recorded as a refused origin."""
        from tests.test_issue_136_security_audit_3 import _build_main_client, _preflight
        client = _build_main_client(monkeypatch, {"TWITCH_EXTENSION_CLIENT_ID": _GAME_ID,
                                                  "TWITCH_VOTE_EXTENSION_CLIENT_ID": _VOTE_ID})
        import twitch
        twitch.reset_traffic()
        refused = [f"https://other789clientid.ext-twitch.tv",
                   f"https://{_VOTE_ID}.ext-twitch.tv.evil.example",
                   f"https://evil{_VOTE_ID}.ext-twitch.tv",
                   f"https://{_VOTE_ID}xext-twitch.tv",
                   f"http://{_VOTE_ID}.ext-twitch.tv",
                   f"https://{_VOTE_ID}.ext-twitch.tv:8443",
                   f"https://{_GAME_ID}|{_VOTE_ID}.ext-twitch.tv"]
        for origin in refused:
            assert "access-control-allow-origin" not in _preflight(client, origin).headers, origin
        # The last five distinct hosts, newest first (host and port only, so the http
        # look-alike shows as the bare host).
        assert twitch.traffic_snapshot()["refused_origins"] == [
            f"{_GAME_ID}|{_VOTE_ID}.ext-twitch.tv", f"{_VOTE_ID}.ext-twitch.tv:8443",
            f"{_VOTE_ID}.ext-twitch.tv", f"{_VOTE_ID}xext-twitch.tv", f"evil{_VOTE_ID}.ext-twitch.tv"]
        # The two real origins are never recorded as refused.
        twitch.reset_traffic()
        for client_id in (_GAME_ID, _VOTE_ID):
            _preflight(client, f"https://{client_id}.ext-twitch.tv")
        snap = twitch.traffic_snapshot()
        assert snap["refused_origins"] == [] and snap["last_extension_request_at"] is not None

    def test_twitch_status_has_vote_extension_rows(self, db, monkeypatch, two_ext_env):
        """build_status lists the vote extension's client id, secret and version checks as their own rows, "ok" when configured, next to the full extension's rows."""
        import twitch_status
        status = twitch_status.build_status(db)
        keys = [c["key"] for c in status["checks"]]
        assert keys[:6] == ["extension_client_id", "extension_secret", "extension_version",
                            "vote_extension_client_id", "vote_extension_secret", "vote_extension_version"]
        rows = {c["key"]: c for c in status["checks"]}
        for key in keys[:6]:
            assert rows[key]["state"] == "ok", rows[key]
        assert rows["vote_extension_client_id"]["label"] == "TWITCH_VOTE_EXTENSION_CLIENT_ID"
        assert f"https://{_VOTE_ID}.ext-twitch.tv" in rows["vote_extension_client_id"]["detail"]
        # Nothing about the secret itself leaves the server.
        dumped = json.dumps(status)
        assert _VOTE_B64 not in dumped and _GAME_B64 not in dumped
        js = (REPO_ROOT / "frontend" / "app-admin-users.js").read_text(encoding="utf-8")
        render = _js_function(js, "_renderTwitchStatus")
        assert "const v = t.vote;" in render and "MVP Vote: refused Twitch tokens" in render

    def test_twitch_status_reports_unconfigured_vote_extension_and_its_token_failures(self, db, monkeypatch, two_ext_env):
        """With the vote extension's settings unset its rows are not "ok" while the full extension's stay "ok", and the vote extension's last token failures are shown separately from the full extension's."""
        import twitch
        import twitch_status
        _raises(lambda: _verify(_signed_claims(_VOTE_SECRET_BYTES, exp=int(time.time()) - 10)), 401)
        traffic = twitch_status.build_status(db)["traffic"]
        assert traffic["vote"]["failures"] == {"expired": 1, "invalid": 0, "not_configured": 0}
        assert traffic["failures"] == {"expired": 0, "invalid": 0, "not_configured": 0}
        for name in ("TWITCH_VOTE_EXTENSION_CLIENT_ID", "TWITCH_VOTE_EXTENSION_SECRET",
                     "TWITCH_VOTE_EXTENSION_VERSION"):
            monkeypatch.delenv(name)
        rows = {c["key"]: c for c in twitch_status.build_status(db)["checks"]}
        for key in ("vote_extension_client_id", "vote_extension_secret", "vote_extension_version"):
            assert rows[key]["state"] == "warning", rows[key]
        for key in ("extension_client_id", "extension_secret", "extension_version"):
            assert rows[key]["state"] == "ok", rows[key]
        # Half configured is a problem, and start-up says which setting is missing.
        monkeypatch.setenv("TWITCH_VOTE_EXTENSION_CLIENT_ID", _VOTE_ID)
        rows = {c["key"]: c for c in twitch_status.build_status(db)["checks"]}
        assert rows["vote_extension_secret"]["state"] == "problem"
        assert rows["vote_extension_client_id"]["state"] == "ok"
        warnings = []
        monkeypatch.setattr(twitch.logger, "warning", lambda msg, *args: warnings.append(msg % args))
        twitch.warn_if_vote_extension_incomplete()
        assert len(warnings) == 1 and "TWITCH_VOTE_EXTENSION_SECRET is not set" in warnings[0]
        monkeypatch.setenv("TWITCH_VOTE_EXTENSION_SECRET", "not base64 !!!")
        rows = {c["key"]: c for c in twitch_status.build_status(db)["checks"]}
        assert rows["vote_extension_secret"]["state"] == "problem"
        twitch.warn_if_vote_extension_incomplete()
        assert len(warnings) == 1

    def test_vote_package_sh_builds_zip_with_fixed_ebs_origins(self, tmp_path):
        """bash twitch-vote-extension/package.sh <version> --ebs-origin https://kana-cards.com (on a copy) exits 0 and writes a zip holding panel, live_config, config, extension.js, extension.css and an ebs-origins.js with that origin."""
        from tests.test_issue_195_twitch_extension_resubmission import _require_zip, _run_package
        _require_zip()
        ext_dir = _vote_ext_copy(tmp_path)
        result = _run_package(ext_dir, "1.0.0", "--ebs-origin", "https://kana-cards.com")
        assert result.returncode == 0, result.stderr
        with zipfile.ZipFile(ext_dir / "twitch-vote-extension-1.0.0.zip") as z:
            names = set(z.namelist())
            origins = z.read("ebs-origins.js").decode()
            packed_panel = z.read("panel.js").decode()
        assert names == {"panel.html", "panel.js", "config.html", "config.js", "live_config.html",
                         "live_config.js", "extension.js", "ebs-origins.js", "extension.css",
                         "fonts/BigShouldersText-VariableFont_wght.ttf", "fonts/BigShouldersText-OFL.txt"}
        assert 'var EBS_ALLOWED_ORIGINS = ["https://kana-cards.com"];' in origins
        assert 'var EXT_BUILD = {version: "1.0.0", origins: ["https://kana-cards.com"]};' in origins
        assert packed_panel == _vext("panel.js")
        # The repository's own ebs-origins.js stays empty (unpackaged files are local-only).
        assert "var EBS_ALLOWED_ORIGINS = [];" in (ext_dir / "ebs-origins.js").read_text()
        assert "var EBS_ALLOWED_ORIGINS = [];" in _vext("ebs-origins.js")

    def test_vote_package_sh_without_ebs_origin_fails_and_writes_no_zip(self, tmp_path):
        """package.sh without --ebs-origin (or with a non-https origin) exits non-zero and leaves no zip behind."""
        from tests.test_issue_195_twitch_extension_resubmission import _require_zip, _run_package
        _require_zip()
        ext_dir = _vote_ext_copy(tmp_path)
        for args in (("1.0.0",), ("1.0.0", "--ebs-origin", "http://kana-cards.com"),
                     ("1.0.0", "--ebs-origin", "https://kana-cards.com/path"), ('1.0.0"; x', "--ebs-origin",
                                                                              "https://kana-cards.com")):
            result = _run_package(ext_dir, *args)
            assert result.returncode != 0, args
            assert list(ext_dir.glob("*.zip")) == []
        # A viewer file with a game route or a link is refused too.
        with open(ext_dir / "panel.js", "a", encoding="utf-8") as f:
            f.write('\nebsPost("/twitch/join");\n')
        result = _run_package(ext_dir, "1.0.0", "--ebs-origin", "https://kana-cards.com")
        assert result.returncode != 0 and "/twitch/join" in result.stderr
        assert list(ext_dir.glob("*.zip")) == []


def _vote_ext_copy(tmp_path):
    dest = tmp_path / "twitch-vote-extension"
    shutil.copytree(VOTE_EXT_DIR, dest, ignore=shutil.ignore_patterns("*.zip"))
    return dest


# ---------------------------------------------------------------------------
# Story 5 — The Extension Is Ready for Twitch Review
# ---------------------------------------------------------------------------

_GAME_ROUTE_PARTS = ("/twitch/join", "/twitch/draw", "/twitch/roster", "/twitch/me",
                     "/twitch/teams", "/twitch/heartbeat", "/twitch/leave", "/twitch/panel")


def _vote_doc():
    return VOTE_SUBMISSION_DOC.read_text(encoding="utf-8")


def _doc_section(heading):
    """Body of a `## ` section of the vote guide, up to the next `## ` heading."""
    doc = _vote_doc()
    start = doc.index("\n", doc.index(f"\n## {heading}") + 1)
    end = doc.find("\n## ", start)
    return doc[start:end if end != -1 else len(doc)]


def _quote_after(section, label):
    """The flattened block quote that follows a `**label` line in a section."""
    from tests.test_issue_195_twitch_extension_resubmission import _flat
    lines = section[section.index(label):].splitlines()[1:]
    quote = []
    for line in lines:
        if line.startswith(">"):
            quote.append(line)
        elif quote:
            break
    assert quote, f"no quote after {label}"
    return _flat("\n".join(quote))


def _vote_endpoint_rows():
    """(paths, method) for each row of the vote guide's endpoint table."""
    section = _doc_section("EBS URL disclosure")
    table = section[section.index("### Endpoints the Extension frontend calls"):]
    rows = []
    for line in table.splitlines():
        if not line.startswith("|") or line.startswith("|---") or line.startswith("| Path"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append((re.findall(r"`(/twitch/[^`]+)`", cells[0]), cells[1]))
    return rows


def _vote_called_paths():
    from tests.test_issue_195_twitch_extension_resubmission import _called_paths
    paths = set()
    for name in VOTE_PACKAGED_JS:
        paths |= _called_paths(_vext(name))
    return paths


def _table_paths(rows):
    return {p for paths, _ in rows for p in paths}


class TestExtensionReadyForTwitchReview:

    def test_vote_submission_guide_has_required_sections(self):
        """twitch-vote-extension-review-submission.md exists and has the listing text, the endpoint disclosure table, both chat messages, the identity-share explanation and reviewer testing steps."""
        import twitch
        import twitch_mvp_poll
        doc = _vote_doc()
        headings = [line[3:].strip() for line in doc.splitlines() if line.startswith("## ")]
        for wanted in ("Listing copy", "EBS URL disclosure", "Chat capability disclosure",
                       "Identity share explanation", "Testing instructions", "Vote-only variant"):
            assert any(h.startswith(wanted) for h in headings), wanted
        assert len(_vote_endpoint_rows()) >= 7
        chat = _doc_section("Chat capability disclosure")
        opened = twitch_mvp_poll.open_chat_text("Team A", "Team B", 1, 120, ext="vote")
        confirmed = twitch._mvp_chat_text("PlayerName", 3, pool_empty=False, vote=(60, 5), voters=True)
        no_drop = twitch._mvp_chat_text("PlayerName", 0, pool_empty=True, vote=(60, 5), voters=True)
        for message in (opened, confirmed, no_drop, "Match MVP: PlayerName!"):
            assert f"`{message}`" in chat, message
        steps = _doc_section("Testing instructions")
        for phrase in ("As the broadcaster", "As a viewer", "Start viewer vote", "End now",
                       "Confirm MVP", "Cancel vote", "Log in to Twitch to vote."):
            assert phrase in steps, phrase
        # The steps name the controls the package really has.
        live = _Markup(_vext("live_config.html")).text
        for label in ("Start viewer vote", "End now", "Confirm MVP", "Cancel vote", "Select match MVP"):
            assert label in live and label in steps

    def test_vote_listing_says_tokens_are_for_kana_cards_and_how_claimed(self):
        """The listing text says tokens are for the Kana Cards game, that they are claimed by signing in with Twitch at kana-cards.com or joining the full extension, and that voting works without either."""
        import twitch
        import twitch_mvp_poll
        listing = _doc_section("Listing copy")
        description = _quote_after(listing, "**Description**")
        assert len(description) < 1024
        assert "Tokens are for the Kana Cards game" in description
        assert "signing in with Twitch at kana-cards.com" in description
        assert "joining the Kana Cards extension" in description
        assert "Voting works without either." in description
        assert "Voting needs no account, sign-up or website." in description
        assert "no money value" in description
        # The chat paragraph quotes the messages the code builds.
        assert twitch_mvp_poll.open_chat_text("Team A", "Team B", 1, 120, ext="vote") in description
        assert twitch._mvp_chat_text("PlayerName", 3, pool_empty=False, vote=(60, 5), voters=True) in description
        assert "Kana Cards MVP Vote" in listing

    def test_vote_guide_explains_identity_share_is_optional_and_hashed(self):
        """The identity-share explanation says the share is optional, used only for the token drop, and that only a keyed hash of the Twitch id is stored, for at most 60 days when unclaimed."""
        from tests.test_issue_195_twitch_extension_resubmission import _flat
        import twitch_mvp_poll
        import twitch_vote_rewards
        text_ = _flat(_doc_section("Identity share explanation"))
        for phrase in ("The identity share is optional.", "used only for the token drop",
                       "only a keyed hash", "does not store the Twitch user id",
                       "at most 60 days", "Votes are deleted 30 days after the vote ends",
                       "Twitch.ext.actions.requestIdShare()"):
            assert phrase in text_, phrase
        assert twitch_vote_rewards.PENDING_TOKEN_DAYS == 60
        assert twitch_mvp_poll.VOTE_RETENTION_DAYS == 30
        # The quoted panel copy is the panel's own.
        panel = _vext("panel.js")
        for const in ("SHARE_TITLE", "SHARE_REASON", "PENDING_WIN_TEXT"):
            literal = re.search(rf'var {const} = "([^"]+)";', panel).group(1)
            assert literal in text_, const

    def test_vote_endpoint_table_lists_every_packaged_twitch_path(self):
        """Every /twitch/... path called by the vote extension's packaged JS files (_called_paths) has a row in the vote guide's endpoint table."""
        from tests.test_issue_195_twitch_extension_resubmission import _coverage_problems
        called = _vote_called_paths()
        assert called == {"/twitch/mvp-poll", "/twitch/mvp-poll/{poll_id}/vote",
                          "/twitch/mvp-poll/{poll_id}/end", "/twitch/mvp-poll/{poll_id}/cancel",
                          "/twitch/matches/current", "/twitch/mvp", "/twitch/ping", "/twitch/check"}
        missing, _ = _coverage_problems(called, _table_paths(_vote_endpoint_rows()))
        assert missing == []

    def test_vote_endpoint_table_has_no_path_the_package_does_not_call(self):
        """The vote guide's endpoint table has no path that the packaged files never call, and no game route (join, draw, roster)."""
        from tests.test_issue_195_twitch_extension_resubmission import _coverage_problems
        table = _table_paths(_vote_endpoint_rows())
        _, never_called = _coverage_problems(_vote_called_paths(), table)
        assert never_called == []
        for path in table:
            assert not path.startswith(_GAME_ROUTE_PARTS), path
        # GET and POST on /twitch/mvp-poll are two rows.
        methods = sorted(m for paths, m in _vote_endpoint_rows() if paths == ["/twitch/mvp-poll"])
        assert methods == ["GET", "POST"]

    def test_vote_endpoint_coverage_detects_missing_table_row(self):
        """Removing one called path from the table rows makes the coverage check report exactly that path as missing (the drift test can fail)."""
        from tests.test_issue_195_twitch_extension_resubmission import _coverage_problems
        rows = [r for r in _vote_endpoint_rows() if r[0] != ["/twitch/mvp-poll/{poll_id}/vote"]]
        assert len(rows) == len(_vote_endpoint_rows()) - 1
        missing, never_called = _coverage_problems(_vote_called_paths(), _table_paths(rows))
        assert missing == ["/twitch/mvp-poll/{poll_id}/vote"] and never_called == []
        _, extra = _coverage_problems(_vote_called_paths(),
                                      _table_paths(_vote_endpoint_rows()) | {"/twitch/join"})
        assert extra == ["/twitch/join"]

    def test_vote_endpoint_table_paths_have_backend_routes(self):
        """Each method and path in the vote guide's endpoint table matches a registered backend /twitch route (_route_problems is empty)."""
        from tests.test_issue_195_twitch_extension_resubmission import (
            _backend_twitch_routes, _route_problems)
        routes = _backend_twitch_routes()
        rows = _vote_endpoint_rows()
        assert _route_problems(rows, routes) == []
        assert _route_problems([(["/twitch/mvp-poll/{poll_id}/vote"], "GET")], routes) != []

    def test_vote_guide_has_vote_only_variant_for_tokens_switched_off(self):
        """The guide has a vote-only variant: listing text with no mention of tokens or the identity share, and the instruction to set TWITCH_VOTE_TOKENS_ENABLED=false before submitting it."""
        import twitch
        variant = _doc_section("Vote-only variant")
        assert "Set `TWITCH_VOTE_TOKENS_ENABLED=false` on the server before submitting." in variant
        assert "Request Identity Link" in variant
        description = _quote_after(variant, "**Description (vote-only):**")
        lowered = description.lower()
        for word in ("token", "identity", "share", "kana-cards.com", "claim"):
            assert word not in lowered, word
        assert "Voting needs no account, sign-up or website." in description
        assert twitch._mvp_chat_text("PlayerName", 0, pool_empty=True, vote=(60, 5), voters=True) in description
        assert len(description) < 1024

    def test_feature_docs_and_env_example_name_the_new_settings(self):
        """.env.example and the vote extension feature doc name TWITCH_VOTE_EXTENSION_CLIENT_ID, TWITCH_VOTE_EXTENSION_SECRET and TWITCH_VOTE_TOKENS_ENABLED, and markdown/features/README.md links both new docs."""
        env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        feature = (REPO_ROOT / "markdown" / "features" / "reference" / "twitch-mvp-vote-extension.md").read_text(
            encoding="utf-8")
        for name in ("TWITCH_VOTE_EXTENSION_CLIENT_ID", "TWITCH_VOTE_EXTENSION_SECRET",
                     "TWITCH_VOTE_EXTENSION_VERSION", "TWITCH_VOTE_TOKENS_ENABLED"):
            assert f"# {name}=" in env_example, name
            assert f"`{name}`" in feature, name
        assert "*(planned)*" not in feature and "stub created at feature planning time" not in feature
        readme = (REPO_ROOT / "markdown" / "features" / "README.md").read_text(encoding="utf-8")
        assert "(reference/twitch-mvp-vote-extension.md)" in readme
        assert "(reference/twitch-vote-extension-review-submission.md)" in readme
        row = [ln for ln in readme.splitlines() if "(reference/twitch-mvp-vote-extension.md)" in ln][0]
        assert "planned" not in row
        core = (REPO_ROOT / "markdown" / "features" / "core" / "twitch-extension.md").read_text(encoding="utf-8")
        assert "(../reference/twitch-mvp-vote-extension.md)" in core
        assert "twitch-vote-extension/*.zip" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Step 6 — Migration and schema coverage
# ---------------------------------------------------------------------------

def _pre_253_engine():
    """The current schema with twitch_mvp_polls and twitch_mvp_votes in their #234 shape
    (one poll and one vote in them), and every earlier migration recorded as applied."""
    import migrate
    from database import Base
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys = OFF"))
        conn.execute(text("DROP TABLE twitch_pending_tokens"))
        conn.execute(text("DROP TABLE twitch_mvp_votes"))
        conn.execute(text("DROP TABLE twitch_mvp_polls"))
        conn.execute(text("""CREATE TABLE twitch_mvp_polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id VARCHAR NOT NULL, match_id INTEGER NOT NULL,
            status VARCHAR NOT NULL, opened_at INTEGER NOT NULL, closes_at INTEGER NOT NULL,
            closed_at INTEGER, confirmed_player_id INTEGER, tally_json TEXT, info_json TEXT)"""))
        conn.execute(text("""CREATE TABLE twitch_mvp_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, poll_id INTEGER NOT NULL REFERENCES twitch_mvp_polls (id),
            twitch_user_id VARCHAR NOT NULL, player_id INTEGER NOT NULL, voted_at INTEGER NOT NULL,
            CONSTRAINT uq_twitch_mvp_vote_poll_voter UNIQUE (poll_id, twitch_user_id))"""))
        conn.execute(text("INSERT INTO twitch_mvp_polls (id, channel_id, match_id, status, opened_at, closes_at) "
                          "VALUES (1, 'c1', 1001, 'closed', 100, 220)"))
        conn.execute(text("INSERT INTO twitch_mvp_votes (poll_id, twitch_user_id, player_id, voted_at) "
                          "VALUES (1, 'Uold', 101, 150)"))
        conn.commit()
        migrate._ensure_migrations_table(conn)
        for migration_id, _ in migrate.MIGRATIONS:
            if migration_id < "045":
                migrate._record(conn, migration_id)
    return engine


def _cols(engine, table):
    return [c["name"] for c in sa_inspect(engine).get_columns(table)]


class TestSchemaAndMigration:

    def test_migration_adds_extension_column_to_twitch_mvp_polls(self):
        """run_migrations on a database with the #234 twitch_mvp_polls table adds the extension column, and existing polls read as the game extension."""
        import migrate
        from models import TwitchMvpPoll
        engine = _pre_253_engine()
        assert "extension" not in _cols(engine, "twitch_mvp_polls")
        migrate.run_migrations(engine)
        assert "extension" in _cols(engine, "twitch_mvp_polls")
        with sessionmaker(bind=engine)() as s:
            poll = s.get(TwitchMvpPoll, 1)
            assert poll.extension == "game" and poll.status == "closed" and poll.match_id == 1001
            s.add(TwitchMvpPoll(channel_id="c2", match_id=5, status="open", opened_at=1, closes_at=2))
            s.commit()
            assert s.query(TwitchMvpPoll).filter_by(channel_id="c2").one().extension == "game"

    def test_migration_adds_account_hash_column_to_twitch_mvp_votes(self):
        """run_migrations on a database with the #234 twitch_mvp_votes table adds a nullable account_hash column and keeps existing votes."""
        import migrate
        from models import TwitchMvpVote
        engine = _pre_253_engine()
        assert "account_hash" not in _cols(engine, "twitch_mvp_votes")
        migrate.run_migrations(engine)
        column = [c for c in sa_inspect(engine).get_columns("twitch_mvp_votes") if c["name"] == "account_hash"]
        assert len(column) == 1 and column[0]["nullable"] is True
        with sessionmaker(bind=engine)() as s:
            vote = s.query(TwitchMvpVote).one()
            assert (vote.twitch_user_id, vote.player_id, vote.account_hash) == ("Uold", 101, None)

    def test_migrations_are_idempotent_for_the_new_columns(self):
        """Running run_migrations twice on the legacy database raises nothing and leaves one extension and one account_hash column."""
        import migrate
        engine = _pre_253_engine()
        migrate.run_migrations(engine)
        migrate.run_migrations(engine)
        with engine.connect() as conn:
            migrate._m045_twitch_mvp_polls_extension(conn)        # applied again by hand: still a no-op
            migrate._m046_twitch_mvp_votes_account_hash(conn)
            applied = {r[0] for r in conn.execute(text("SELECT id FROM schema_migrations")).fetchall()}
        assert {"045_twitch_mvp_polls_extension", "046_twitch_mvp_votes_account_hash"} <= applied
        assert _cols(engine, "twitch_mvp_polls").count("extension") == 1
        assert _cols(engine, "twitch_mvp_votes").count("account_hash") == 1
        # A database without the tables yet (they come from create_all) is left alone.
        empty = create_engine("sqlite:///:memory:")
        with empty.connect() as conn:
            migrate._m045_twitch_mvp_polls_extension(conn)
            migrate._m046_twitch_mvp_votes_account_hash(conn)
        assert sa_inspect(empty).get_table_names() == []

    def test_twitch_pending_tokens_table_has_planned_columns(self, db):
        """twitch_pending_tokens has exactly id, account_hash, poll_id, created_at, expires_at, claimed_by_user_id and claimed_at, and is created by create_all with no CREATE TABLE in migrate.py."""
        from models import TwitchPendingToken
        assert TwitchPendingToken.__tablename__ == "twitch_pending_tokens"
        assert _cols(db.get_bind(), "twitch_pending_tokens") == [
            "id", "account_hash", "poll_id", "created_at", "expires_at", "claimed_by_user_id", "claimed_at"]
        migrate_source = (REPO_ROOT / "backend" / "migrate.py").read_text(encoding="utf-8")
        assert "twitch_pending_tokens" not in migrate_source

    def test_twitch_pending_tokens_unique_on_account_hash_and_poll(self, db):
        """A second twitch_pending_tokens row with the same account_hash and poll_id is refused (IntegrityError, or ignored by ON CONFLICT DO NOTHING); the same hash in another poll is allowed."""
        from models import TwitchPendingToken
        import twitch
        first, second = _two_polls(db)
        _pending_row(db, "9002", first)
        db.add(TwitchPendingToken(account_hash=_hash("9002"), poll_id=first, created_at=1, expires_at=2))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        stmt = twitch._dialect_insert(db)(TwitchPendingToken).values(
            account_hash=_hash("9002"), poll_id=first, created_at=1, expires_at=2,
        ).on_conflict_do_nothing(index_elements=[TwitchPendingToken.account_hash, TwitchPendingToken.poll_id])
        assert db.execute(stmt).rowcount == 0
        db.commit()
        _pending_row(db, "9002", second)                           # another poll: allowed
        _pending_row(db, "9003", first)                            # another viewer: allowed
        assert len(_pending(db)) == 3

    def test_all_model_columns_present_after_migration(self):
        """After run_migrations on a legacy database, every column of TwitchMvpPoll, TwitchMvpVote and the pending-token model exists in the database (as test_migrate's TestSchemaCoverage checks)."""
        import migrate
        from database import Base
        from models import TwitchMvpPoll, TwitchMvpVote, TwitchPendingToken
        engine = _pre_253_engine()
        migrate.run_migrations(engine)
        Base.metadata.create_all(engine)                           # creates twitch_pending_tokens
        for model in (TwitchMvpPoll, TwitchMvpVote, TwitchPendingToken):
            have = set(_cols(engine, model.__tablename__))
            missing = {c.name for c in model.__table__.columns} - have
            assert missing == set(), (model.__tablename__, missing)
