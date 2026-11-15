"""
Tests for plan-issue-234-mvp-poll-for-watchers.md (resolves GitHub issue #234).

Viewers choose a match MVP by a timed poll in the Twitch panel. The broadcaster
opens the poll from Quick Actions (series -> match picker), joined viewers who
are eligible for drops vote, the poll closes lazily at `closes_at` (or on End
now / Cancel), and the broadcaster confirms through the existing
`POST /twitch/mvp` with an optional `poll_id`. New tables `twitch_mvp_polls`
(`TwitchMvpPoll`) and `twitch_mvp_votes` (`TwitchMvpVote`), new module
`backend/twitch_mvp_poll.py` with its router under `/twitch`. One class per user
story, one stub per acceptance criterion plus the primary failure path.

Developer notes
---------------

  Existing code these tests target
    - backend/twitch.py: `set_mvp` / `MVPBody` (gains optional `poll_id`),
      `verify_twitch_jwt`, `_require_broadcaster`, `mvp_channel_allowed`
      (refusal records an approval request), `_eligible_mvp_match_ids`,
      `_active_pool` and the soft-account age rule
      (TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS), `_execute_token_drop`,
      `_pubsub_broadcast`, `_post_chat_message`, `_mvp_chat_text`,
      `chat_safe_name`, `_panel_account`, Leave Kana Cards.
    - backend/main.py: router mount and the daily cleanup task (vote retention).
    - Check every "as today" claim in the plan against the code before pinning it
      (lessons-learned 2026-10-13).

  Imports
    - Import `TwitchMvpPoll`, `TwitchMvpVote` and `twitch_mvp_poll` INSIDE each
      test: they don't exist yet, and a module-level import would break
      collection of every stub.

  Reusable helpers / fixtures
    - From test_issue_157_twitch_extension_policy_compliance.py: `twitch_env`,
      `_viewer`, `_CHANNEL`, `_join`, `_backdate`, `_present`,
      `_seed_series_match`, `_set_mvp`, `_chat_recorder`, `_twitch_app`,
      `_shared_db`, `_signed`, `_js_function`, `_ext`, `_raises`,
      `_no_twitch_ids` (precedent: test_issue_171 imports them).
    - Live (no-stats) match players: `_seed_live` from
      test_issue_139_early_mvp_selection.py.
    - Rate-limit tests: use the router module's own `limiter`, reset it and
      restore `enabled` (lessons-learned 2026-10-31).
    - Time: make "now" injectable or monkeypatch the module's clock so lazy close
      can be tested without sleeping.

  Existing tests this plan may break
    - Grep backend/tests for `MVPBody`, `_mvp_chat_text`, `set_mvp(` and the
      live_config / panel element ids before changing them.
    - test_issue_85 full-suite "N passed" tripwire, if still present.
"""

import json
import re
import time

import pytest

# Registers every existing table on Base before the conftest db fixture runs
# create_all. New models are imported inside tests.
import models  # noqa: F401

from tests.test_issue_157_twitch_extension_policy_compliance import (  # noqa: F401
    REPO_ROOT, _BROADCASTER, _CHANNEL, _backdate, _chat_recorder, _ext, _join, _js_function,
    _no_twitch_ids, _present, _raises, _shared_db, _viewer, twitch_env,
)

# Teams 11 and 12 with five players each, all with stats in the match.
_TEN = {11: [101, 102, 103, 104, 105], 12: [201, 202, 203, 204, 205]}


def _seed_ten(db, match_id=1001, start_time=None):
    """A match in the MVP series window (teams 11 vs 12, one hour ago) with 10 players."""
    from models import Match, Player, PlayerMatchStats, Team
    for tid in _TEN:
        if not db.get(Team, tid):
            db.add(Team(id=tid, name=f"Team{tid}"))
    db.add(Match(match_id=match_id, radiant_team_id=11, dire_team_id=12,
                 start_time=start_time if start_time is not None else int(time.time()) - 3600,
                 radiant_win=True))
    for tid, pids in _TEN.items():
        for pid in pids:
            if not db.get(Player, pid):
                db.add(Player(id=pid, name=f"Player{pid}"))
            db.add(PlayerMatchStats(player_id=pid, match_id=match_id, team_id=tid,
                                    fantasy_points=10.0, kills=3, is_mvp=False))
    db.commit()


def _open(db, match_id=1001, duration=120, payload=None):
    import twitch_mvp_poll
    body = twitch_mvp_poll.PollOpenBody(match_id=match_id, duration_seconds=duration)
    return twitch_mvp_poll.open_poll(body, dict(payload or _BROADCASTER), db)


def _vote(db, poll_id, player_id, opaque_id="Uviewer1", payload=None):
    import twitch_mvp_poll
    return twitch_mvp_poll.vote(poll_id, twitch_mvp_poll.VoteBody(player_id=player_id),
                                dict(payload or _viewer(opaque_id)), db)


def _get(db, payload=None):
    import twitch_mvp_poll
    return twitch_mvp_poll.get_poll(dict(payload or _viewer()), db)["poll"]


def _end(db, poll_id):
    import twitch_mvp_poll
    return twitch_mvp_poll.end_poll(poll_id, dict(_BROADCASTER), db)


def _cancel(db, poll_id, payload=None):
    import twitch_mvp_poll
    return twitch_mvp_poll.cancel_poll(poll_id, dict(payload or _BROADCASTER), db)


def _voter(db, opaque_id="Uviewer1"):
    """A joined soft account old enough for drops (and so for votes)."""
    _join(db, opaque_id)
    _backdate(db, opaque_id)
    return opaque_id


def _clock(monkeypatch, offset):
    """Move the poll module's clock `offset` seconds ahead of real time."""
    import twitch_mvp_poll
    monkeypatch.setattr(twitch_mvp_poll, "_now", lambda: int(time.time()) + offset)


def _pubsub(monkeypatch):
    import twitch
    sent = []
    monkeypatch.setattr(twitch, "_pubsub_broadcast", lambda channel_id, message: sent.append(message))
    return sent


def _poll_row(db, poll_id):
    from models import TwitchMvpPoll
    db.expire_all()
    return db.get(TwitchMvpPoll, poll_id)


def _audits(db, action):
    from models import AuditLog
    return [a.detail for a in db.query(AuditLog).filter(AuditLog.action == action).all()]


def _nothing_written(db):
    from models import TwitchMvpPoll
    assert db.query(TwitchMvpPoll).count() == 0
    assert _audits(db, "twitch_mvp_poll_opened") == []


def _mvp_body(match_id=1001, player_id=101, poll_id=None):
    import twitch
    return twitch.MVPBody(match_id=match_id, player_id=player_id, poll_id=poll_id)


def _confirm(db, poll_id, player_id=101, match_id=1001, payload=None):
    import twitch
    return twitch.set_mvp(_mvp_body(match_id, player_id, poll_id), payload=dict(payload or _BROADCASTER), db=db)


def _closed_poll(db, monkeypatch, votes):
    """A poll on match 1001 with `votes` ({opaque_id: player_id}), closed by End now."""
    _seed_ten(db)
    for opaque_id in votes:
        _voter(db, opaque_id)
    poll = _open(db)
    for opaque_id, pid in votes.items():
        _vote(db, poll["poll_id"], pid, opaque_id)
    return _end(db, poll["poll_id"])


def _live_config():
    return _ext("live_config.js"), _ext("live_config.html")


@pytest.fixture(autouse=True)
def _env(twitch_env, monkeypatch):
    """No real Twitch calls, and the default drop rules whatever the shell exports."""
    for name in ("TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS", "TWITCH_DROPS_ENABLED"):
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# Story 1 — The Streamer Starts a Viewer Vote for a Match
# ---------------------------------------------------------------------------

class TestStreamerStartsViewerVote:

    def test_live_config_match_view_has_start_viewer_vote_and_timer_choice(self):
        """The MVP tool's match view has Start viewer vote next to Pick MVP, with a 1/2/3 minute timer (2 by default)."""
        js, html = _live_config()
        step3 = html[html.index('id="mvp-step-3"'):html.index('id="mvp-step-4"')]
        assert ">Pick MVP<" in step3 and ">Start viewer vote<" in step3
        assert step3.index('id="btn-mode-pick"') < step3.index('id="btn-mode-vote"')
        select = step3[step3.index('<select id="poll-duration">'):step3.index("</select>")]
        assert re.findall(r'value="(\d+)"', select) == ["60", "120", "180"]
        assert '<option value="120" selected>2 min</option>' in select
        assert ">1 min<" in select and ">3 min<" in select
        start = _js_function(js, "startViewerVote")
        assert '"/twitch/mvp-poll"' in start and "duration_seconds" in start and "_selectedMatch.match_id" in start
        assert 'showMatchMode("pick")' in _js_function(js, "selectMatch")

    def test_open_poll_rejects_duration_outside_choices(self, db):
        """A duration other than 60, 120 or 180 seconds is refused (422) and nothing is written."""
        _seed_ten(db)
        for bad in (0, 30, 90, 121, 300):
            _raises(lambda: _open(db, duration=bad), 422)
        _nothing_written(db)
        import twitch_mvp_poll
        assert twitch_mvp_poll.DURATION_CHOICES == (60, 120, 180)
        assert twitch_mvp_poll.PollOpenBody(match_id=1001).duration_seconds == 120

    def test_open_poll_for_match_with_stats_lists_ten_players_by_team(self, db):
        """The poll opens for the picked match_id and lists its 10 players from ingested stats, grouped by team."""
        _seed_ten(db)
        poll = _open(db)
        assert poll["match_id"] == 1001 and poll["status"] == "open"
        assert (poll["team1_name"], poll["team2_name"], poll["match_number"]) == ("Team11", "Team12", 1)
        teams = {t["team_name"]: [p["player_id"] for p in t["players"]] for t in poll["teams"]}
        assert {k: sorted(v) for k, v in teams.items()} == {"Team11": _TEN[11], "Team12": _TEN[12]}
        assert sum(len(t["players"]) for t in poll["teams"]) == 10
        assert poll["closes_at"] - poll["opened_at"] == 120
        row = _poll_row(db, poll["poll_id"])
        assert row.channel_id == _CHANNEL and row.match_id == 1001 and row.status == "open"

    def test_open_poll_for_live_match_uses_live_players(self, db):
        """A live match without stats can be polled, using its live players."""
        from tests.test_issue_139_early_mvp_selection import _LIVE_PAYLOAD, _seed_live
        _seed_live(db, _LIVE_PAYLOAD[0])
        match_id = int(_LIVE_PAYLOAD[0]["match_id"])
        poll = _open(db, match_id=match_id)
        teams = {t["team_name"]: sorted(p["player_id"] for p in t["players"]) for t in poll["teams"]}
        assert teams == {"Radiant Wolves": [500, 501, 502, 503, 504], "Dire Bears": [510, 511, 512, 513]}
        assert poll["team1_name"] and poll["team2_name"]

    def test_open_poll_requires_broadcaster_role(self, db):
        """A viewer JWT cannot open a poll (403); nothing is written."""
        _seed_ten(db)
        for role in ("viewer", "moderator"):
            _raises(lambda: _open(db, payload=_viewer(role=role)), 403)
        _nothing_written(db)

    def test_open_poll_unapproved_channel_returns_403_and_records_approval_request(self, db, monkeypatch):
        """A channel that isn't approved is refused with 403, an approval request is recorded as for MVPs, and no poll is written."""
        from models import TwitchChannelApproval
        monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", "999")
        _seed_ten(db)
        payload = {**_BROADCASTER, "channel_id": "123456"}
        _raises(lambda: _open(db, payload=payload), 403)
        _nothing_written(db)
        row = db.get(TwitchChannelApproval, "123456")
        assert row is not None and row.status == "pending"

    def test_open_poll_match_outside_series_window_returns_403(self, db):
        """A match outside the series window is refused with 403 and no poll is written."""
        _seed_ten(db, start_time=int(time.time()) + 86400)  # not started: outside the window
        _raises(lambda: _open(db), 403)
        _nothing_written(db)
        _raises(lambda: _open(db, match_id=4242), 404)
        _nothing_written(db)

    def test_open_poll_second_open_poll_on_channel_returns_409(self, db):
        """A second open poll on the same channel is refused with 409."""
        _seed_ten(db)
        _seed_ten(db, match_id=1002)
        first = _open(db)
        _raises(lambda: _open(db, match_id=1002), 409)
        from models import TwitchMvpPoll
        assert [p.id for p in db.query(TwitchMvpPoll).all()] == [first["poll_id"]]
        # Another channel may open its own poll at the same time.
        other = _open(db, match_id=1002, payload={**_BROADCASTER, "channel_id": "other_channel"})
        assert other["status"] == "open"

    def test_open_poll_after_previous_poll_closed_is_allowed(self, db, monkeypatch):
        """Once the channel's poll has closed or been cancelled, a new poll for another match can open."""
        _seed_ten(db)
        _seed_ten(db, match_id=1002)
        first = _open(db)
        _cancel(db, first["poll_id"])
        second = _open(db, match_id=1002)
        _end(db, second["poll_id"])
        third = _open(db)
        assert third["status"] == "open"
        # A poll whose timer ran out is closed on the next open.
        _clock(monkeypatch, 200)
        fourth = _open(db, match_id=1002)
        assert _poll_row(db, third["poll_id"]).status == "closed"
        assert fourth["status"] == "open"

    def test_open_poll_match_already_confirmed_returns_409(self, db, monkeypatch):
        """A match whose poll was already confirmed cannot be polled again (409)."""
        _voter(db, "Uv1")
        closed = _closed_poll(db, monkeypatch, {"Uv1": 101})
        _confirm(db, closed["poll_id"], 101)
        assert _poll_row(db, closed["poll_id"]).status == "confirmed"
        _raises(lambda: _open(db), 409)
        from models import TwitchMvpPoll
        assert db.query(TwitchMvpPoll).count() == 1

    def test_open_poll_posts_one_chat_message_with_teams_game_and_time(self, db, monkeypatch):
        """Opening posts one chat message naming the teams, game number and time left, cut to 280 chars with chat_safe_name."""
        from models import Team
        chat = _chat_recorder(monkeypatch)
        _seed_ten(db)
        db.get(Team, 11).name = "Evil\u202eTeam https://spam.example"
        db.commit()
        _open(db, duration=180)
        assert len(chat) == 1
        text = chat[0]
        assert text.startswith("MVP vote open for TBD vs Team12, game 1: vote in the Kana Cards panel.")
        assert text.endswith("Closes in 3 min.")
        assert "\u202e" not in text and "https://" not in text
        import twitch_mvp_poll
        assert (twitch_mvp_poll.open_chat_text("Team A", "Team B", 1, 120)
                == "MVP vote open for Team A vs Team B, game 1: vote in the Kana Cards panel. Closes in 2 min.")
        assert len(twitch_mvp_poll.open_chat_text("x" * 500, "y" * 500, 3, 60)) <= 280

    def test_open_poll_broadcasts_pubsub_poll_open(self, db, monkeypatch):
        """Opening sends a PubSub {"type":"mvp_poll","state":"open","poll_id":...} message to every panel."""
        sent = _pubsub(monkeypatch)
        _seed_ten(db)
        poll = _open(db)
        assert sent == [{"type": "mvp_poll", "state": "open", "poll_id": poll["poll_id"]}]

    def test_open_poll_writes_poll_opened_audit(self, db):
        """Opening writes a twitch_mvp_poll_opened audit entry."""
        _seed_ten(db)
        poll = _open(db, duration=60)
        details = _audits(db, "twitch_mvp_poll_opened")
        assert details == [f"channel={_CHANNEL} match=1001 poll={poll['poll_id']} duration=60"]

    def test_live_config_open_poll_view_shows_countdown_votes_end_now_and_cancel(self):
        """While open, the tool shows a countdown from closes_at, the vote count (polled every 5 s), End now and Cancel."""
        js, html = _live_config()
        step4 = html[html.index('id="mvp-step-4"'):]
        for needle in ('id="poll-countdown"', 'id="poll-votes"', ">End now<", ">Cancel vote<"):
            assert needle in step4, needle
        assert re.search(r"POLL_REFRESH_MS\s*=\s*5000", js)
        show = _js_function(js, "showPoll")
        assert "setInterval(refreshPoll, POLL_REFRESH_MS)" in show and "setInterval(renderCountdown, 1000)" in show
        assert "closes_at" in _js_function(js, "pollSecondsLeft")
        assert '"/end"' in _js_function(js, "endViewerVote")
        assert '"/cancel"' in _js_function(js, "cancelViewerVote")
        assert "voteCountText(p.total_votes)" in _js_function(js, "renderPoll")

    def test_cancel_poll_ends_without_result_and_posts_no_mvp(self, db, monkeypatch):
        """Cancel sets status cancelled, writes no twitch_mvp row, no bonus, no drop, broadcasts state cancelled and audits twitch_mvp_poll_cancelled."""
        from models import PlayerMatchStats, TwitchMVP, TwitchTokenDrop
        sent = _pubsub(monkeypatch)
        chat = _chat_recorder(monkeypatch)
        _seed_ten(db)
        _voter(db, "Uv1")
        _present(db, "Uv1")
        poll = _open(db)
        _vote(db, poll["poll_id"], 101, "Uv1")
        out = _cancel(db, poll["poll_id"])
        assert out == {"poll_id": poll["poll_id"], "status": "cancelled"}
        row = _poll_row(db, poll["poll_id"])
        assert row.status == "cancelled" and row.closed_at is not None and row.confirmed_player_id is None
        assert db.query(TwitchMVP).count() == 0 and db.query(TwitchTokenDrop).count() == 0
        assert not any(r.is_mvp for r in db.query(PlayerMatchStats).all())
        assert sent[-1] == {"type": "mvp_poll", "state": "cancelled", "poll_id": poll["poll_id"]}
        assert len(chat) == 1  # only the "vote open" line
        assert _audits(db, "twitch_mvp_poll_cancelled") == [f"channel={_CHANNEL} match=1001 poll={poll['poll_id']}"]
        assert _get(db) is None
        _raises(lambda: _cancel(db, poll["poll_id"]), 409)
        _raises(lambda: _confirm(db, poll["poll_id"]), 409)
        # A cancelled newer poll never brings back an earlier poll's recent result.
        _seed_ten(db, match_id=1002)
        earlier = _open(db, match_id=1002)
        _end(db, earlier["poll_id"])
        assert _get(db)["poll_id"] == earlier["poll_id"]
        newer = _open(db, match_id=1002)
        _cancel(db, newer["poll_id"])
        assert _get(db) is None

    def test_cancel_or_end_poll_by_non_broadcaster_returns_403(self, db):
        """A viewer cannot End now or Cancel a poll (403)."""
        _seed_ten(db)
        poll = _open(db)
        import twitch_mvp_poll
        _raises(lambda: twitch_mvp_poll.end_poll(poll["poll_id"], _viewer(), db), 403)
        _raises(lambda: twitch_mvp_poll.cancel_poll(poll["poll_id"], _viewer(), db), 403)
        # A broadcaster on another channel doesn't find it.
        other = {**_BROADCASTER, "channel_id": "other_channel"}
        _raises(lambda: twitch_mvp_poll.end_poll(poll["poll_id"], other, db), 404)
        _raises(lambda: twitch_mvp_poll.cancel_poll(poll["poll_id"], other, db), 404)
        assert _poll_row(db, poll["poll_id"]).status == "open"


# ---------------------------------------------------------------------------
# Story 2 — Viewers Vote in the Panel
# ---------------------------------------------------------------------------

class TestViewersVoteInPanel:

    def test_get_poll_returns_open_poll_with_players_and_countdown(self, db):
        """GET /twitch/mvp-poll returns the channel's open poll: match, closes_at, the 10 players by team, and the viewer's own vote."""
        _seed_ten(db)
        _voter(db, "Uv1")
        opened = _open(db)
        _vote(db, opened["poll_id"], 202, "Uv1")
        poll = _get(db, _viewer("Uv1"))
        assert poll["poll_id"] == opened["poll_id"] and poll["status"] == "open" and poll["match_id"] == 1001
        assert poll["closes_at"] == opened["closes_at"] and 0 < poll["seconds_left"] <= 120
        assert [t["team_name"] for t in poll["teams"]] == ["Team11", "Team12"]
        assert sum(len(t["players"]) for t in poll["teams"]) == 10
        assert poll["my_vote"] == 202 and poll["total_votes"] == 1
        assert poll["voter"] == {"can_vote": True, "reason": "ok", "votes_from": None}
        # Another viewer gets the same poll without anyone else's vote.
        assert _get(db, _viewer("Uother"))["my_vote"] is None

    def test_get_poll_with_no_poll_on_channel_returns_empty(self, db):
        """GET /twitch/mvp-poll on a channel without any poll returns no poll (not an error)."""
        import twitch_mvp_poll
        assert twitch_mvp_poll.get_poll(_viewer(), db) == {"poll": None}
        _seed_ten(db)
        _open(db, payload={**_BROADCASTER, "channel_id": "other_channel"})
        assert twitch_mvp_poll.get_poll(_viewer(), db) == {"poll": None}

    def test_panel_live_tab_shows_poll_card_and_handles_pubsub_mvp_poll(self):
        """The Live tab shows the poll card at the top, loads it via GET /twitch/mvp-poll and handles PubSub mvp_poll open/closed/cancelled."""
        html, js = _ext("panel.html"), _ext("panel.js")
        live = html[html.index('id="view-live"'):html.index('id="view-cards"')]
        assert 'id="live-poll"' in live
        assert live.index('id="live-poll"') < live.index("Latest MVPs")
        assert '"/twitch/mvp-poll"' in _js_function(js, "loadPoll")
        assert "loadPoll()" in _js_function(js, "onReady")
        pubsub = _js_function(js, "onPubSub")
        assert 'msg.type === "mvp_poll"' in pubsub and "loadPoll()" in pubsub
        render = _js_function(js, "renderPoll")
        assert "p.teams" in render and "poll-team" in render and "_escHtml(pl.player_name)" in render
        assert '"/vote"' in _js_function(js, "castVote")
        ext = _ext("extension.js")
        assert "onPubSub(msg)" in _js_function(ext, "init")

    def test_vote_by_joined_eligible_viewer_is_recorded(self, db):
        """A joined viewer eligible for drops can vote; one twitch_mvp_votes row is stored."""
        from models import TwitchMvpVote
        _seed_ten(db)
        _voter(db, "Uv1")
        poll = _open(db)
        out = _vote(db, poll["poll_id"], 103, "Uv1")
        assert out == {"poll_id": poll["poll_id"], "my_vote": 103, "total_votes": 1}
        row = db.query(TwitchMvpVote).one()
        assert (row.poll_id, row.twitch_user_id, row.player_id) == (poll["poll_id"], "Uv1", 103)

    def test_vote_by_viewer_not_joined_returns_403(self, db):
        """A viewer who hasn't joined is refused with 403 (panel shows "Join to vote")."""
        from models import TwitchMvpVote
        _seed_ten(db)
        poll = _open(db)
        _raises(lambda: _vote(db, poll["poll_id"], 101, "Unobody"), 403, "not_joined")
        assert db.query(TwitchMvpVote).count() == 0
        assert _get(db, _viewer("Unobody"))["voter"] == {"can_vote": False, "reason": "join", "votes_from": None}

    def test_vote_by_logged_out_viewer_returns_403(self, db):
        """A logged-out (A...) viewer is refused with 403."""
        from models import TwitchMvpVote
        _seed_ten(db)
        poll = _open(db)
        _raises(lambda: _vote(db, poll["poll_id"], 101, payload=_viewer("Aanon123")), 403, "twitch_login_required")
        assert db.query(TwitchMvpVote).count() == 0
        view = _get(db, _viewer("Aanon123"))
        assert view["voter"]["reason"] == "login" and view["my_vote"] is None

    def test_vote_by_too_new_soft_account_returns_403_with_votes_from_date(self, db, monkeypatch):
        """A soft account too new for drops is refused with 403; GET /twitch/mvp-poll gives the date its vote counts from."""
        from models import TwitchMvpVote
        monkeypatch.delenv("TWITCH_DROP_MIN_ACCOUNT_AGE_HOURS", raising=False)
        _seed_ten(db)
        _join(db, "Unew")
        poll = _open(db)
        _raises(lambda: _vote(db, poll["poll_id"], 101, "Unew"), 403, "too_new")
        assert db.query(TwitchMvpVote).count() == 0
        voter = _get(db, _viewer("Unew"))["voter"]
        assert voter["can_vote"] is False and voter["reason"] == "too_new"
        assert abs(voter["votes_from"] - (int(time.time()) + 24 * 3600)) <= 5
        # A website account is never too new.
        from tests.test_issue_157_twitch_extension_policy_compliance import _website_user
        _website_user(db, "alice", twitch_user_id="Ualice")
        assert _vote(db, poll["poll_id"], 101, "Ualice")["my_vote"] == 101

    def test_panel_shows_join_to_vote_and_vote_counts_from_messages(self):
        """The panel source has the "Join to vote" and "Your vote counts from <date>" states."""
        js = _ext("panel.js")
        note = _js_function(js, "pollVoterNote")
        assert '"Join to vote."' in note
        assert '"Your vote counts from "' in note and "v.votes_from" in note
        assert '"Log in to Twitch to vote."' in note
        assert "pollVoterNote(p)" in _js_function(js, "renderPoll")

    def test_vote_change_replaces_previous_vote(self, db):
        """A viewer voting again before close changes their vote; still one row per poll and voter."""
        from models import TwitchMvpVote
        _seed_ten(db)
        _voter(db, "Uv1")
        poll = _open(db)
        _vote(db, poll["poll_id"], 101, "Uv1")
        out = _vote(db, poll["poll_id"], 205, "Uv1")
        assert out["my_vote"] == 205 and out["total_votes"] == 1
        rows = db.query(TwitchMvpVote).all()
        assert len(rows) == 1 and rows[0].player_id == 205
        assert _get(db, _viewer("Uv1"))["my_vote"] == 205

    def test_vote_after_closes_at_returns_409(self, db, monkeypatch):
        """A vote after closes_at is refused with 409 and the poll is closed lazily."""
        from models import TwitchMvpVote
        _seed_ten(db)
        _voter(db, "Uv1")
        poll = _open(db, duration=60)
        _clock(monkeypatch, 61)
        _raises(lambda: _vote(db, poll["poll_id"], 101, "Uv1"), 409, "poll_closed")
        assert db.query(TwitchMvpVote).count() == 0
        row = _poll_row(db, poll["poll_id"])
        assert row.status == "closed" and row.closed_at == row.closes_at

    def test_vote_for_player_not_in_match_returns_422(self, db):
        """A vote for a player not in the poll's match is refused with 422."""
        from models import TwitchMvpVote
        _seed_ten(db)
        _seed_ten(db, match_id=1002)
        _voter(db, "Uv1")
        poll = _open(db)
        _raises(lambda: _vote(db, poll["poll_id"], 999, "Uv1"), 422)
        assert db.query(TwitchMvpVote).count() == 0

    def test_vote_on_cancelled_or_unknown_poll_is_refused(self, db):
        """A vote on a cancelled poll (409) or an unknown poll id (404) is refused."""
        _seed_ten(db)
        _voter(db, "Uv1")
        poll = _open(db)
        _cancel(db, poll["poll_id"])
        _raises(lambda: _vote(db, poll["poll_id"], 101, "Uv1"), 409, "poll_closed")
        _raises(lambda: _vote(db, 987654, 101, "Uv1"), 404)
        # A poll on another channel is unknown to this channel's viewers.
        other = _open(db, payload={**_BROADCASTER, "channel_id": "other_channel"})
        _raises(lambda: _vote(db, other["poll_id"], 101, "Uv1"), 404)

    def test_get_poll_while_open_shows_only_total_votes(self, db):
        """While open, GET /twitch/mvp-poll returns only the total vote count, no per-player counts."""
        _seed_ten(db)
        for v in ("Uv1", "Uv2", "Uv3"):
            _voter(db, v)
        poll = _open(db)
        for v, pid in (("Uv1", 101), ("Uv2", 101), ("Uv3", 201)):
            _vote(db, poll["poll_id"], pid, v)
        view = _get(db, _viewer("Uv1"))
        assert view["total_votes"] == 3
        for key in ("results", "winner_player_id", "tied_player_ids"):
            assert key not in view
        text = json.dumps(view)
        assert '"votes"' not in text and '"pct"' not in text

    def test_get_poll_after_close_shows_shares_and_own_pick(self, db, monkeypatch):
        """After close, GET /twitch/mvp-poll returns each player's share and the viewer's own pick."""
        _closed_poll(db, monkeypatch, {"Uv1": 101, "Uv2": 101, "Uv3": 201})
        view = _get(db, _viewer("Uv3"))
        assert view["status"] == "closed" and view["total_votes"] == 3 and view["my_vote"] == 201
        by_player = {r["player_id"]: (r["votes"], r["pct"]) for r in view["results"]}
        assert by_player[101] == (2, 67) and by_player[201] == (1, 33) and by_player[105] == (0, 0)
        assert len(view["results"]) == 10 and view["results"][0]["player_id"] == 101
        # The result stays visible for a while, then the panel drops it.
        import twitch_mvp_poll
        _clock(monkeypatch, twitch_mvp_poll.RESULT_SHOWN_SECONDS + 5)
        assert _get(db) is None

    def test_poll_responses_and_pubsub_contain_no_voter_ids(self, db, monkeypatch):
        """No poll response or PubSub payload carries other voters' Twitch ids."""
        sent = _pubsub(monkeypatch)
        _seed_ten(db)
        for v in ("Usecret1", "Usecret2"):
            _voter(db, v)
        poll = _open(db)
        responses = [poll, _vote(db, poll["poll_id"], 101, "Usecret1"),
                     _vote(db, poll["poll_id"], 201, "Usecret2"), _get(db, _viewer("Uthird"))]
        responses.append(_end(db, poll["poll_id"]))
        responses.append(_get(db, _viewer("Uthird")))
        responses.append(_confirm(db, poll["poll_id"], 101))
        for obj in responses + sent:
            _no_twitch_ids(obj, "Usecret1", "Usecret2")
        assert {m["type"] for m in sent} == {"mvp_poll", "mvp"}
        for m in sent:
            if m["type"] == "mvp_poll":
                assert set(m) == {"type", "state", "poll_id"}
        assert [m["state"] for m in sent if m["type"] == "mvp_poll"] == ["open", "closed"]

    def test_vote_route_rate_limited_per_ip(self, db):
        """POST /twitch/mvp-poll/{id}/vote is rate-limited per IP like the other panel actions (429 past the limit)."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from limits import parse
        from slowapi import _rate_limit_exceeded_handler
        from slowapi.errors import RateLimitExceeded
        import twitch
        import twitch_mvp_poll
        from database import get_db
        src = (REPO_ROOT / "backend" / "twitch_mvp_poll.py").read_text()
        decorators = src[src.index('@router.post("/mvp-poll/{poll_id}/vote")'):src.index("def vote_route(")]
        assert "@limiter.limit(twitch.RATE_LIMIT_TWITCH_ACTION, key_func=key_by_twitch_viewer_or_ip)" in decorators
        assert "@limiter.limit(twitch.RATE_LIMIT_TWITCH_JOIN_IP)" in decorators

        sdb = _shared_db()
        _seed_ten(sdb)
        poll = _open(sdb)
        app = FastAPI()
        app.state.limiter = twitch_mvp_poll.limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
        app.include_router(twitch_mvp_poll.router)
        app.dependency_overrides[get_db] = lambda: sdb
        app.dependency_overrides[twitch.verify_twitch_jwt] = lambda: _viewer("Unobody")
        was_enabled = twitch_mvp_poll.limiter.enabled
        twitch_mvp_poll.limiter.enabled = True
        twitch_mvp_poll.limiter.reset()
        try:
            client = TestClient(app)
            limit = min(parse(twitch.RATE_LIMIT_TWITCH_ACTION).amount, parse(twitch.RATE_LIMIT_TWITCH_JOIN_IP).amount)
            statuses = [client.post(f"/twitch/mvp-poll/{poll['poll_id']}/vote", json={"player_id": 101}).status_code
                        for _ in range(limit + 1)]
            assert statuses[:limit] == [403] * limit  # not joined, but counted per IP
            assert statuses[-1] == 429
        finally:
            twitch_mvp_poll.limiter.reset()
            twitch_mvp_poll.limiter.enabled = was_enabled
            sdb.close()


# ---------------------------------------------------------------------------
# Story 3 — The Streamer Confirms the Vote's Result
# ---------------------------------------------------------------------------

class TestStreamerConfirmsVoteResult:

    def test_get_poll_lazily_closes_expired_poll_with_tally(self, db, monkeypatch):
        """A read after closes_at sets status closed, closed_at, tally_json, and audits twitch_mvp_poll_closed once."""
        sent = _pubsub(monkeypatch)
        _seed_ten(db)
        for v in ("Uv1", "Uv2"):
            _voter(db, v)
        poll = _open(db, duration=60)
        _vote(db, poll["poll_id"], 101, "Uv1")
        _vote(db, poll["poll_id"], 101, "Uv2")
        assert _get(db)["status"] == "open"
        assert _poll_row(db, poll["poll_id"]).tally_json is None
        _clock(monkeypatch, 75)
        view = _get(db)
        assert view["status"] == "closed" and view["winner_player_id"] == 101
        row = _poll_row(db, poll["poll_id"])
        assert row.status == "closed" and row.closed_at == row.closes_at
        assert json.loads(row.tally_json) == {"101": 2}
        _get(db)
        _get(db)
        assert len(_audits(db, "twitch_mvp_poll_closed")) == 1
        assert [m["state"] for m in sent] == ["open", "closed"]

    def test_end_now_closes_poll_and_returns_tally_with_winner(self, db):
        """End now closes the poll early and returns each player's votes with the sole winner preselected."""
        _seed_ten(db)
        for v in ("Uv1", "Uv2", "Uv3"):
            _voter(db, v)
        poll = _open(db)
        for v, pid in (("Uv1", 104), ("Uv2", 104), ("Uv3", 203)):
            _vote(db, poll["poll_id"], pid, v)
        out = _end(db, poll["poll_id"])
        assert out["status"] == "closed" and out["winner_player_id"] == 104 and out["tied_player_ids"] == []
        assert out["total_votes"] == 3
        assert out["results"][0] == {"player_id": 104, "player_name": "Player104", "chat_name": "Player104",
                                     "votes": 2, "pct": 67}
        row = _poll_row(db, poll["poll_id"])
        assert row.status == "closed" and row.closed_at < row.closes_at

    def test_end_now_on_already_closed_poll_is_refused(self, db, monkeypatch):
        """End now on a poll that is not open is refused (409)."""
        _seed_ten(db)
        poll = _open(db)
        _end(db, poll["poll_id"])
        _raises(lambda: _end(db, poll["poll_id"]), 409)
        second = _open(db)
        _cancel(db, second["poll_id"])
        _raises(lambda: _end(db, second["poll_id"]), 409)
        third = _open(db, duration=60)
        _clock(monkeypatch, 61)
        _raises(lambda: _end(db, third["poll_id"]), 409)  # its timer already closed it
        assert len(_audits(db, "twitch_mvp_poll_closed")) == 2

    def test_tally_tie_lists_tied_players_without_winner(self, db, monkeypatch):
        """A tie preselects no one and lists the tied players."""
        out = _closed_poll(db, monkeypatch, {"Uv1": 101, "Uv2": 201, "Uv3": 105, "Uv4": 105, "Uv5": 101})
        assert out["winner_player_id"] is None
        assert out["tied_player_ids"] == [101, 105]
        import twitch_mvp_poll
        assert twitch_mvp_poll.poll_result({3: 1})["winner_player_id"] == 3
        assert twitch_mvp_poll.poll_result({3: 1, 4: 1})["tied_player_ids"] == [3, 4]

    def test_tally_no_votes_reports_empty_result(self, db, monkeypatch):
        """A poll with no votes reports no result so the tool falls back to Pick MVP."""
        out = _closed_poll(db, monkeypatch, {})
        assert out["total_votes"] == 0 and out["winner_player_id"] is None and out["tied_player_ids"] == []
        assert all(r["votes"] == 0 and r["pct"] == 0 for r in out["results"])
        assert _audits(db, "twitch_mvp_poll_closed")[0].endswith("votes=0 winner=none tie=False")
        # The streamer then picks the MVP as usual.
        assert _confirm(db, None, 101)["player_id"] == 101

    def test_live_config_result_view_preselects_winner_and_falls_back_on_no_votes(self):
        """The live config result view preselects the winner, lists tied players, and opens Pick MVP on no votes."""
        js, html = _live_config()
        result = html[html.index('id="poll-result"'):]
        assert ">Confirm MVP &amp; Drop Tokens<" in result and 'id="btn-poll-confirm"' in result
        render = _js_function(js, "renderPollResult")
        assert "pickAfterNoVotes()" in render and '"Tie between "' in render and "pickPollPlayer(r, div)" in render
        assert "poll_id:   _poll.poll_id" in _js_function(js, "confirmPollMVP")
        assert "selectMatch(_selectedMatch)" in _js_function(js, "pickAfterNoVotes")
        state_fn = _js_function(js, "pollResultState")
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            return
        script = state_fn + """
console.log(JSON.stringify([
  pollResultState({total_votes: 3, winner_player_id: 7, tied_player_ids: []}),
  pollResultState({total_votes: 4, winner_player_id: null, tied_player_ids: [7, 9]}),
  pollResultState({total_votes: 0, winner_player_id: null, tied_player_ids: []}),
]));"""
        out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        winner, tie, none = json.loads(out.stdout)
        assert winner == {"kind": "winner", "preselect": 7, "tied": []}
        assert tie == {"kind": "tie", "preselect": None, "tied": [7, 9]}
        assert none == {"kind": "none", "preselect": None, "tied": []}

    def test_poll_closed_audit_has_votes_winner_tie_and_no_voter_ids(self, db, monkeypatch):
        """twitch_mvp_poll_closed records votes, winner and tie, with no voter ids."""
        out = _closed_poll(db, monkeypatch, {"Uvoter1": 101, "Uvoter2": 101, "Uvoter3": 202})
        details = _audits(db, "twitch_mvp_poll_closed")
        assert details == [f"channel={_CHANNEL} match=1001 poll={out['poll_id']} votes=3 winner=101 tie=False"]
        from models import AuditLog
        for a in db.query(AuditLog).filter(AuditLog.action.like("twitch_mvp_poll_%")).all():
            assert "Uvoter" not in (a.detail or "")

    def test_set_mvp_with_poll_id_sets_mvp_bonus_drop_and_confirms_poll(self, db, monkeypatch):
        """POST /twitch/mvp with poll_id writes the MVP row, bonus, drop, PubSub and audit as today, and marks the poll confirmed."""
        from models import PlayerMatchStats, TwitchMVP, TwitchTokenDrop
        sent = _pubsub(monkeypatch)
        out = _closed_poll(db, monkeypatch, {"Uv1": 102, "Uv2": 102, "Uv3": 201})
        _present(db, "Uv1")
        _present(db, "Uv2")
        result = _confirm(db, out["poll_id"], 102)
        assert result["player_id"] == 102 and result["token_drop"]["winner_count"] == 2
        assert db.query(TwitchMVP).one().player_id == 102
        assert db.query(PlayerMatchStats).filter_by(match_id=1001, player_id=102).one().is_mvp is True
        assert db.query(TwitchTokenDrop).one().count == 2
        row = _poll_row(db, out["poll_id"])
        assert row.status == "confirmed" and row.confirmed_player_id == 102
        assert sent[-1]["type"] == "mvp" and sent[-1]["player_name"] == "Player102"
        mvp_audit = _audits(db, "twitch_mvp_set")
        assert len(mvp_audit) == 1 and f"poll={out['poll_id']}" in mvp_audit[0] and "override" not in mvp_audit[0]

    def test_set_mvp_with_poll_id_drops_tokens_once_per_channel_and_match(self, db, monkeypatch):
        """A confirmed vote drops tokens once per channel and match; a later confirm does not drop again."""
        from models import TwitchTokenDrop, User
        out = _closed_poll(db, monkeypatch, {"Uv1": 101})
        _present(db, "Uv1")
        first = _confirm(db, out["poll_id"], 101)
        assert first["token_drop"]["winner_count"] == 1
        tokens = db.query(User).filter(User.twitch_user_id == "Uv1").one().tokens
        second = _confirm(db, None, 103)  # a later Pick MVP on the same match
        assert second["token_drop"]["already_dropped"] is True and second["token_drop"]["winner_count"] == 0
        db.expire_all()
        assert db.query(User).filter(User.twitch_user_id == "Uv1").one().tokens == tokens
        assert db.query(TwitchTokenDrop).count() == 1
        _raises(lambda: _confirm(db, out["poll_id"], 101), 409)  # already confirmed

    def test_set_mvp_with_open_poll_returns_409(self, db):
        """Confirming with a poll that is still open (or cancelled/confirmed) is refused and nothing is written."""
        from models import TwitchMVP, TwitchTokenDrop
        _seed_ten(db)
        _voter(db, "Uv1")
        poll = _open(db)
        _vote(db, poll["poll_id"], 101, "Uv1")
        _raises(lambda: _confirm(db, poll["poll_id"], 101), 409)
        _cancel(db, poll["poll_id"])
        _raises(lambda: _confirm(db, poll["poll_id"], 101), 409)
        assert db.query(TwitchMVP).count() == 0 and db.query(TwitchTokenDrop).count() == 0
        assert _audits(db, "twitch_mvp_set") == []

    def test_confirm_racing_a_cancel_writes_nothing(self, db, monkeypatch):
        """Security fix 1: a cancel landing between the closed check and the confirm
        leaves no MVP, drop, chat or 'by viewer vote' audit (409)."""
        import twitch_mvp_poll
        from models import TwitchMVP, TwitchTokenDrop
        out = _closed_poll(db, monkeypatch, {"Uv1": 101})
        chat = _chat_recorder(monkeypatch)
        original = twitch_mvp_poll.confirmable_poll

        def racing(db_, poll_id, channel_id, match_id):
            poll = original(db_, poll_id, channel_id, match_id)
            _cancel(db_, poll_id)  # the concurrent cancel commits first
            from sqlalchemy.orm.attributes import set_committed_value
            set_committed_value(poll, "status", "closed")  # the confirm's stale read
            return poll

        monkeypatch.setattr(twitch_mvp_poll, "confirmable_poll", racing)
        _raises(lambda: _confirm(db, out["poll_id"], 101), 409)
        assert db.query(TwitchMVP).count() == 0 and db.query(TwitchTokenDrop).count() == 0
        assert _audits(db, "twitch_mvp_set") == [] and chat == []
        assert _poll_row(db, out["poll_id"]).status == "cancelled"

    def test_vote_racing_a_close_is_refused_and_not_stored(self, db, monkeypatch):
        """Security fix 2: a close landing between the vote's open check and its insert
        refuses the vote (409), so no vote is stored outside the tally."""
        import twitch_mvp_poll
        from models import TwitchMvpVote
        from sqlalchemy.orm.attributes import set_committed_value
        _seed_ten(db)
        _voter(db, "Uv1")
        _voter(db, "Uv2")
        poll = _open(db)
        _vote(db, poll["poll_id"], 101, "Uv1")
        original = twitch_mvp_poll.close_if_due

        def racing(db_, poll_obj, now=None):
            original(db_, poll_obj, now)
            twitch_mvp_poll._close(db_, poll_obj, int(time.time()), broadcast=False)
            set_committed_value(poll_obj, "status", "open")  # the vote's stale read

        monkeypatch.setattr(twitch_mvp_poll, "close_if_due", racing)
        _raises(lambda: _vote(db, poll["poll_id"], 202, "Uv2"), 409, "poll_closed")
        db.expire_all()
        assert [(v.twitch_user_id, v.player_id) for v in db.query(TwitchMvpVote).all()] == [("Uv1", 101)]
        row = _poll_row(db, poll["poll_id"])
        assert row.status == "closed" and json.loads(row.tally_json) == {"101": 1}

    def test_set_mvp_with_poll_for_other_match_or_channel_is_refused(self, db, monkeypatch):
        """A poll_id for another match or another channel is refused and nothing is written."""
        from models import TwitchMVP
        _seed_ten(db, match_id=1002)
        out = _closed_poll(db, monkeypatch, {"Uv1": 101})
        _raises(lambda: _confirm(db, out["poll_id"], 101, match_id=1002), 409)
        other = {**_BROADCASTER, "channel_id": "other_channel"}
        _raises(lambda: _confirm(db, out["poll_id"], 101, payload=other), 404)
        _raises(lambda: _confirm(db, 987654, 101), 404)
        assert db.query(TwitchMVP).count() == 0
        assert _poll_row(db, out["poll_id"]).status == "closed"
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            _mvp_body(poll_id=2**63)

    def test_set_mvp_without_poll_id_unchanged(self, db, monkeypatch):
        """Pick MVP without poll_id works as today (no poll required)."""
        from models import TwitchMVP
        chat = _chat_recorder(monkeypatch)
        _seed_ten(db)
        result = _confirm(db, None, 105)
        assert result["player_id"] == 105 and db.query(TwitchMVP).one().player_id == 105
        assert chat == ["Match MVP: Player105! No tokens were dropped: no joined viewers were watching."]
        assert "poll=" not in _audits(db, "twitch_mvp_set")[0]
        import twitch
        assert twitch.MVPBody(match_id=1, player_id=2).poll_id is None

    def test_confirmed_vote_chat_text_uses_vote_message_and_drop_sentence(self, db, monkeypatch):
        """Confirming the sole winner posts "Match MVP by viewer vote: {name} ({pct}% of {votes} votes)!" plus the drop sentence, within 280 chars with chat_safe_name."""
        from models import Player
        chat = _chat_recorder(monkeypatch)
        out = _closed_poll(db, monkeypatch, {"Uv1": 102, "Uv2": 102, "Uv3": 201})
        db.get(Player, 102).name = "Sa\u200bvu"
        db.commit()
        _present(db, "Uv1")
        _confirm(db, out["poll_id"], 102)
        assert chat[-1] == "Match MVP by viewer vote: Savu (67% of 3 votes)! 1 viewer received a token."
        import twitch
        assert twitch._mvp_chat_text("X", 0, True, vote=(100, 1)) == (
            "Match MVP by viewer vote: X (100% of 1 vote)! No tokens were dropped: no joined viewers were watching.")
        assert len(twitch._mvp_chat_text("Y" * 400, 3, False, vote=(50, 4))) <= 280

    def test_confirm_other_player_uses_existing_chat_text_and_override_audit(self, db, monkeypatch):
        """Confirming someone other than the vote's winner posts the existing "Match MVP: {name}!" text and audits override=True."""
        chat = _chat_recorder(monkeypatch)
        out = _closed_poll(db, monkeypatch, {"Uv1": 102, "Uv2": 102, "Uv3": 201})
        _confirm(db, out["poll_id"], 201)
        assert chat[-1].startswith("Match MVP: Player201!")
        assert "viewer vote" not in chat[-1]
        detail = _audits(db, "twitch_mvp_set")[0]
        assert f"poll={out['poll_id']}" in detail and "override=True" in detail
        assert _poll_row(db, out["poll_id"]).confirmed_player_id == 201


# ---------------------------------------------------------------------------
# Story 4 — Votes Are Kept Only as Long as Needed
# ---------------------------------------------------------------------------

class TestVoteRetention:

    def test_cleanup_deletes_votes_of_polls_ended_over_30_days_ago(self, db, monkeypatch):
        """The daily cleanup deletes individual votes of polls ended over 30 days ago; the poll keeps tally_json."""
        import twitch_mvp_poll
        from models import TwitchMvpVote
        out = _closed_poll(db, monkeypatch, {"Uv1": 101, "Uv2": 101, "Uv3": 202})
        row = _poll_row(db, out["poll_id"])
        tally = row.tally_json
        now = row.closed_at + 31 * 86400
        assert twitch_mvp_poll.cleanup_votes(db, now) == 3
        assert db.query(TwitchMvpVote).count() == 0
        row = _poll_row(db, out["poll_id"])
        assert row.tally_json == tally and json.loads(tally) == {"101": 2, "202": 1}
        # A poll nobody read after its timer is closed (tally written) before its votes go.
        poll = _open(db, duration=60)
        _vote(db, poll["poll_id"], 103, "Uv1")
        later = _poll_row(db, poll["poll_id"]).closes_at + 31 * 86400
        assert twitch_mvp_poll.cleanup_votes(db, later) == 1
        row = _poll_row(db, poll["poll_id"])
        assert row.status == "closed" and json.loads(row.tally_json) == {"103": 1}

    def test_cleanup_keeps_votes_of_recent_and_open_polls(self, db, monkeypatch):
        """Votes of open polls and of polls ended under 30 days ago are kept."""
        import twitch_mvp_poll
        from models import TwitchMvpVote
        out = _closed_poll(db, monkeypatch, {"Uv1": 101, "Uv2": 202})
        closed_at = _poll_row(db, out["poll_id"]).closed_at
        poll = _open(db)
        _vote(db, poll["poll_id"], 103, "Uv1")
        assert twitch_mvp_poll.cleanup_votes(db) == 0
        assert _poll_row(db, poll["poll_id"]).status == "open"
        assert twitch_mvp_poll.cleanup_votes(db, closed_at + 29 * 86400) == 0
        assert db.query(TwitchMvpVote).count() == 3

    def test_daily_task_runs_vote_cleanup(self):
        """main's daily cleanup task calls the vote retention cleanup."""
        import inspect
        import main
        loop = inspect.getsource(main._week_maintenance_loop)
        assert "_run_mvp_vote_cleanup(db)" in loop
        assert "_MVP_VOTE_CLEANUP_INTERVAL" in loop and main._MVP_VOTE_CLEANUP_INTERVAL == 86400
        calls = []
        import twitch_mvp_poll
        orig = twitch_mvp_poll.cleanup_votes
        try:
            twitch_mvp_poll.cleanup_votes = lambda db, now: calls.append(now) or 0
            main._run_mvp_vote_cleanup(object())
        finally:
            twitch_mvp_poll.cleanup_votes = orig
        assert len(calls) == 1 and abs(calls[0] - time.time()) < 5

        class _Broken:
            rolled_back = False

            def rollback(self):
                self.rolled_back = True
        broken = _Broken()
        main._run_mvp_vote_cleanup(broken)  # a failure is logged, never raised
        assert broken.rolled_back

    def test_leave_kana_cards_deletes_soft_account_votes(self, db):
        """Leave Kana Cards deletes the soft account's votes."""
        import twitch
        from models import TwitchMvpVote
        _seed_ten(db)
        _voter(db, "Uv1")
        poll = _open(db)
        _vote(db, poll["poll_id"], 101, "Uv1")
        assert twitch.leave(_viewer("Uv1"), db) == {"left": True, "deleted": True}
        assert db.query(TwitchMvpVote).count() == 0
        # A website account leaving the panel loses its votes too.
        from tests.test_issue_157_twitch_extension_policy_compliance import _website_user
        _website_user(db, "alice", twitch_user_id="Ualice")
        _vote(db, poll["poll_id"], 102, "Ualice")
        assert twitch.leave(_viewer("Ualice"), db) == {"left": True, "deleted": False}
        assert db.query(TwitchMvpVote).count() == 0
        # The idle soft-account purge goes through the same delete.
        import soft_accounts
        _voter(db, "Uidle")
        _vote(db, poll["poll_id"], 103, "Uidle")
        soft_accounts.purge_inactive_soft_accounts(db, int(time.time()) + 400 * 86400, 365)
        assert db.query(TwitchMvpVote).count() == 0

    def test_leave_kana_cards_keeps_other_viewers_votes(self, db):
        """Leave deletes only the leaving viewer's votes, not other viewers'."""
        import twitch
        from models import TwitchMvpVote
        _seed_ten(db)
        _voter(db, "Uv1")
        _voter(db, "Uv2")
        poll = _open(db)
        _vote(db, poll["poll_id"], 101, "Uv1")
        _vote(db, poll["poll_id"], 201, "Uv2")
        twitch.leave(_viewer("Uv1"), db)
        assert [(v.twitch_user_id, v.player_id) for v in db.query(TwitchMvpVote).all()] == [("Uv2", 201)]

    def test_privacy_page_mentions_votes_and_retention(self):
        """frontend/privacy.html says what is stored for votes and for how long (30 days)."""
        from html.parser import HTMLParser

        class _Text(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts = []

            def handle_data(self, data):
                self.parts.append(data)
        parser = _Text()
        parser.feed((REPO_ROOT / "frontend" / "privacy.html").read_text(encoding="utf-8"))
        text = " ".join(" ".join(parser.parts).split())
        assert "MVP votes." in text
        assert "We store each vote with your opaque Twitch id, the player you chose and the time" in text
        assert "Individual votes are deleted 30 days after the vote ends" in text
        assert "at once when you leave Kana Cards" in text
        assert "never who voted for whom" in text

    def test_review_notes_walkthrough_and_changelog_name_both_chat_messages(self):
        """The review docs have a poll walkthrough step and the 1.4.0 change log lists both new chat messages."""
        import twitch
        import twitch_mvp_poll
        doc = (REPO_ROOT / "markdown" / "features" / "reference" / "twitch-extension-review-submission.md").read_text()
        open_msg = twitch_mvp_poll.open_chat_text("Team A", "Team B", 1, 120)
        vote_msg = twitch._mvp_chat_text("PlayerName", 3, False, vote=(60, 5))
        # Chat capability disclosure
        disclosure = doc[doc.index("### From version 1.4.0: MVP viewer vote"):doc.index("## Monetization")]
        assert open_msg in disclosure and vote_msg in disclosure
        # Walkthrough step in the Testing Instructions
        steps = doc[doc.index("## Steps to reproduce"):doc.index("## Security fix made for this submission")]
        flow = steps[steps.index("**Flow 6"):]
        for needle in ("Start viewer vote", "Open vote", "End now", "Cancel vote", "Vote saved.",
                       "Confirm MVP & Drop Tokens", "Match MVP by viewer vote:", "MVP vote open for"):
            assert needle in flow, needle
        # 1.4.0 change log names both messages, and its description fits the listing field
        log = doc[doc.index("### 2026-11 — Version 1.4.0 change log"):]
        assert open_msg in log and vote_msg in log
        desc_block = log[log.index("**Description for 1.4.0**"):log.index("**Changes since the last review (1.4.0")]
        desc = "\n".join(l[1:].strip() for l in desc_block.splitlines() if l.startswith(">")).replace("**", "")
        assert desc.startswith("Twitch Chat:") and len(desc) <= 1000
        assert "Match MVP by viewer vote: PlayerName (60% of 5 votes)!" in desc and open_msg in desc
        for case in (twitch._mvp_chat_text("PlayerName", 3, False), twitch._mvp_chat_text("PlayerName", 0, True),
                     twitch._mvp_chat_text("PlayerName", 0, True, only_new_accounts=True),
                     twitch._mvp_chat_text("PlayerName", 0, False)):
            assert case in desc, case
        changes = log[log.index("**Changes since the last review (1.4.0"):]
        assert not re.findall(r"#\d+", changes)
