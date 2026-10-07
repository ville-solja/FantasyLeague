"""
Tests for plan-issue-139-early-mvp-selection.md (resolves GitHub issue #139).

A match seen live for a monitored league is stored in a new `live_matches`
table (model `LiveMatch`) and offered in the Twitch MVP panel before its stats
are ingested. One stub per acceptance criterion, plus the primary failure path
for each story.

Since issue #161 the live source is Steam (`steam_live.get_live_league_games`,
checked by `main._live_poll_loop`); OpenDota's /live and
`ingest.get_live_matches()` are gone, and `_ingest_poll_loop` only reads
`live_matches`. Steam's games are normalised to the same entry keys
`store_live_matches()` has always read, so `_LIVE_PAYLOAD` (originally an
OpenDota /live capture) still exercises it. Steam-specific tests live in
test_issue_161_mvp_selection_delays.py.

Testing approach (copy the fixtures from the named precedent files):

  Live entry fixture (OpenDota /live shape verified 2026-09-30)
    - Use `_LIVE_PAYLOAD` below: `match_id` is a STRING, players carry
      `account_id`, `hero_id`, `team` (0 radiant, 1 dire) and `team_slot`, and
      usually NO `name`. A missing team is `0` / `""` (see the second entry).
      One player has no `account_id` and must be skipped.

  Storage / cleanup (`ingest.store_live_matches`)
    - Call them directly. If `store_live_matches` opens its own session, patch
      `monkeypatch.setattr(ingest, "SessionLocal", lambda: db)` so it uses the
      conftest `db` fixture; otherwise pass `db` explicitly.
    - Import `LiveMatch` from `models` inside each test (it does not exist yet,
      so a module-level import would break collection of every stub).

  Twitch endpoints (`twitch.current_matches`, `twitch.set_mvp`)
    - Call the router functions directly with `payload=` and `db=` (precedent:
      Story 1 of test_issue_135_security_review_fixes.py: `twitch_env`
      fixture, `_seed_match`, `_seed_world`, `_call_set_mvp`,
      `_assert_nothing_written`). `TWITCH_LOCAL_DEV=true` short-circuits
      PubSub and chat, so patch `twitch._post_chat_message` /
      `twitch._pubsub_broadcast` with recorders to assert on messages.
    - Seed `LiveMatch` rows directly with `players_json` built from
      `_LIVE_PAYLOAD` (sides "radiant"/"dire"), `first_seen_at`/`last_seen_at`
      a minute ago, and `ended_at=None` for "live" or a timestamp for ended.

  Ingest (`ingest.ingest_match`, `ingest._reapply_mvp_bonus`)
    - Follow test_opendota_parse_retry.py: patch `ingest.opendota_get_json` to
      return a canned `/matches/{id}` payload, call
      `ingest.ingest_match(db, match_id, league_id, set(), set(), weights)`
      with a `Weight(key="mvp_bonus_pct")` row seeded. Use `caplog` for the
      warning.

  Poll loop (`main._ingest_poll_loop`)
    - Follow test_issue_109_opendota_query_prioritization.py: plain
      `import main` inside the test (do NOT reload main; conftest sets
      BACKGROUND_TASKS_ENABLED=false and DEBUG=true), `_OneShotEvent` as
      `main._stop_event`, and monkeypatch `_get_monitored_league_ids`,
      `_auto_ingest`, `_run_toornament_sync`, `_has_active_week`. For the post-match check,
      patch `main.SessionLocal` to return `db`, or patch whatever helper the
      implementation exposes for "recently ended LiveMatch without stats".
      Patch the module-level interval constants rather than env vars (they are
      read at import time).

  Extension (`twitch-extension/live_config.js`)
    - No JS runtime, so static source checks (precedent:
      test_issue_115_username_xss_fix.py, test_twitch_review_resubmission.py).
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import HTTPException

# Registers every table (including live_matches) on Base before the conftest db
# fixture runs create_all.
import models  # noqa: F401, E402

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_LIVE_CONFIG_JS = os.path.join(_REPO_ROOT, "twitch-extension", "live_config.js")
_PACKAGE_SH = os.path.join(_REPO_ROOT, "twitch-extension", "package.sh")

_MONITORED_LEAGUE = 777
_OTHER_LEAGUE = 888

# Live entries in the shape store_live_matches() reads (an OpenDota /live capture
# verified on 2026-09-30; since #161 steam_live produces the same keys).
_LIVE_PAYLOAD = [
    {   # Monitored league, both teams known, one player without account_id.
        "match_id": "8100000001",
        "league_id": _MONITORED_LEAGUE,
        "team_id_radiant": 11, "team_id_dire": 12,
        "team_name_radiant": "Radiant Wolves", "team_name_dire": "Dire Bears",
        "activate_time": 1790000000, "deactivate_time": 0, "game_time": 900,
        "players": (
            [{"account_id": 500 + i, "hero_id": 1 + i, "team": 0, "team_slot": i} for i in range(5)]
            + [{"account_id": 510 + i, "hero_id": 20 + i, "team": 1, "team_slot": i} for i in range(4)]
            + [{"hero_id": 40, "team": 1, "team_slot": 4}]  # no account_id -> skipped
        ),
    },
    {   # Monitored league, team ids missing (0), names present; one player has a name.
        "match_id": "8100000002",
        "league_id": _MONITORED_LEAGUE,
        "team_id_radiant": 0, "team_id_dire": 0,
        "team_name_radiant": "Pickup Alpha", "team_name_dire": "Pickup Beta",
        "activate_time": 1790000100, "deactivate_time": 0, "game_time": 300,
        "players": (
            [{"account_id": 600, "hero_id": 5, "team": 0, "team_slot": 0, "name": "LiveNamed"}]
            + [{"account_id": 601 + i, "hero_id": 6 + i, "team": 0, "team_slot": 1 + i} for i in range(4)]
            + [{"account_id": 610 + i, "hero_id": 30 + i, "team": 1, "team_slot": i} for i in range(5)]
        ),
    },
    {   # Unmonitored league: must not be stored.
        "match_id": "8100000003",
        "league_id": _OTHER_LEAGUE,
        "team_id_radiant": 21, "team_id_dire": 22,
        "team_name_radiant": "Other A", "team_name_dire": "Other B",
        "activate_time": 1790000200, "deactivate_time": 0, "game_time": 60,
        "players": [{"account_id": 700 + i, "hero_id": i + 1, "team": i // 5, "team_slot": i % 5}
                    for i in range(10)],
    },
]


# ===========================================================================
# Shared helpers
# ===========================================================================

_BROADCASTER = {"channel_id": "test_channel", "role": "broadcaster", "opaque_user_id": "Utest"}
_SIDES = {0: "radiant", 1: "dire"}


@pytest.fixture
def twitch_env(monkeypatch):
    """No real Twitch calls: PubSub/chat short-circuit under TWITCH_LOCAL_DEV."""
    monkeypatch.setenv("TWITCH_LOCAL_DEV", "true")
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("TWITCH_MVP_CHANNEL_IDS", raising=False)


def _players_json(entry):
    return json.dumps([
        {"account_id": p["account_id"], "name": p.get("name"), "side": _SIDES.get(p.get("team"))}
        for p in entry["players"] if p.get("account_id")
    ])


def _seed_live(db, entry, first_seen=None, ended_at=None, match_id=None, **overrides):
    """Seed a LiveMatch row straight from a _LIVE_PAYLOAD entry."""
    from models import LiveMatch
    first_seen = first_seen if first_seen is not None else int(time.time()) - 60
    fields = dict(
        match_id=match_id or int(entry["match_id"]),
        league_id=entry["league_id"],
        radiant_team_id=entry["team_id_radiant"] or None,
        dire_team_id=entry["team_id_dire"] or None,
        radiant_name=entry["team_name_radiant"] or None,
        dire_name=entry["team_name_dire"] or None,
        players_json=_players_json(entry),
        first_seen_at=first_seen,
        last_seen_at=first_seen if ended_at is None else ended_at,
        ended_at=ended_at,
    )
    fields.update(overrides)
    row = LiveMatch(**fields)
    db.add(row)
    db.commit()
    return row


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


def _seed_five_newer_series(db):
    """Five ingested series (teams 10k+1 vs 10k+2), all within the last 5 hours."""
    now = int(time.time())
    for k in range(1, 6):
        _seed_match(db, 1000 + k, 10 * k + 1, 10 * k + 2, now - 3600 * k,
                    player_ids=(100 + 2 * k, 100 + 2 * k + 1))


def _add_viewer(db):
    from models import TwitchPresence, User
    db.add(User(id=50, username="viewer", tokens=0, twitch_user_id="Uviewer"))
    db.add(TwitchPresence(twitch_user_id="Uviewer", channel_id="test_channel", seen_at=int(time.time())))
    db.commit()


def _add_mvp_weight(db, value=10.0):
    from models import Weight
    db.add(Weight(key="mvp_bonus_pct", label="MVP bonus (%)", value=value))
    db.commit()


def _call_set_mvp(db, match_id, player_id, payload=_BROADCASTER):
    import twitch
    return twitch.set_mvp(twitch.MVPBody(match_id=match_id, player_id=player_id),
                          payload=dict(payload), db=db)


def _current(db):
    import twitch
    return twitch.current_matches(payload=dict(_BROADCASTER), db=db)


def _all_matches(result):
    return [m for s in result["series"] for m in s["matches"]]


def _assert_nothing_written(db):
    from models import AuditLog, PlayerMatchStats, TwitchMVP, TwitchTokenDrop
    db.expire_all()
    assert db.query(TwitchMVP).count() == 0
    assert db.query(TwitchTokenDrop).count() == 0
    assert db.query(PlayerMatchStats).filter(PlayerMatchStats.is_mvp == True).count() == 0  # noqa: E712
    assert db.query(AuditLog).filter(AuditLog.action.like("twitch_%")).count() == 0


class _OneShotEvent:
    """Stand-in for main._stop_event: runs one loop iteration and records the wait timeout."""

    def __init__(self):
        self._flag = False
        self.wait_calls = []

    def is_set(self):
        return self._flag

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        self._flag = True


def _run_poll_loop_once(monkeypatch, db, active_week=True):
    import main
    monkeypatch.setattr(main, "_get_monitored_league_ids", lambda: [_MONITORED_LEAGUE])
    monkeypatch.setattr(main, "_auto_ingest", lambda league_ids, live: None)
    monkeypatch.setattr(main, "_run_toornament_sync", lambda: None)
    monkeypatch.setattr(main, "_has_active_week", lambda: active_week)
    monkeypatch.setattr(main, "SessionLocal", lambda: db)
    monkeypatch.setattr(main, "_INGEST_POST_MATCH_FAST_POLL_MINUTES", 20)
    event = _OneShotEvent()
    monkeypatch.setattr(main, "_stop_event", event)
    main._ingest_poll_loop()
    return event.wait_calls


def _read_js():
    with open(_LIVE_CONFIG_JS, encoding="utf-8") as f:
        return f.read()


def _function_source(src, name):
    start = src.index("function " + name + "(")
    nxt = src.find("\nfunction ", start + 1)
    return src[start:nxt if nxt != -1 else len(src)]


# ===========================================================================
# Story 1 — Pick the MVP Right After the Game
# ===========================================================================

def test_store_live_matches_upserts_monitored_league_entries(db):
    """AC: the poll stores every /live game of a monitored league in live_matches."""
    import ingest
    from models import LiveMatch

    ingest.store_live_matches(_LIVE_PAYLOAD, [_MONITORED_LEAGUE], db=db, now=1000)

    rows = {r.match_id: r for r in db.query(LiveMatch).all()}
    assert set(rows) == {8100000001, 8100000002}
    first = rows[8100000001]
    assert first.league_id == _MONITORED_LEAGUE
    assert (first.radiant_team_id, first.dire_team_id) == (11, 12)
    assert (first.radiant_name, first.dire_name) == ("Radiant Wolves", "Dire Bears")
    assert first.first_seen_at == first.last_seen_at == 1000
    assert first.ended_at is None
    players = json.loads(first.players_json)
    assert players[0] == {"account_id": 500, "name": None, "side": "radiant"}
    assert {p["account_id"] for p in players if p["side"] == "dire"} == {510, 511, 512, 513}

    second = rows[8100000002]
    assert (second.radiant_team_id, second.dire_team_id) == (None, None)
    assert (second.radiant_name, second.dire_name) == ("Pickup Alpha", "Pickup Beta")
    named = [p for p in json.loads(second.players_json) if p["account_id"] == 600]
    assert named == [{"account_id": 600, "name": "LiveNamed", "side": "radiant"}]

    # Empty-string team names are stored as None.
    entry = dict(_LIVE_PAYLOAD[1], team_name_radiant="", match_id="8100000009")
    ingest.store_live_matches([entry], [_MONITORED_LEAGUE], db=db, now=1100)
    assert db.get(LiveMatch, 8100000009).radiant_name is None

    ingest.store_live_matches(_LIVE_PAYLOAD, [_MONITORED_LEAGUE], db=db, now=2000)
    db.expire_all()
    again = db.get(LiveMatch, 8100000001)
    assert again.first_seen_at == 1000
    assert again.last_seen_at == 2000
    assert again.ended_at is None


def test_store_live_matches_skips_unmonitored_leagues_and_players_without_account_id(db):
    """Failure path: unmonitored-league games are not stored and players without account_id are skipped."""
    import ingest
    from models import LiveMatch

    ingest.store_live_matches(_LIVE_PAYLOAD, [_MONITORED_LEAGUE], db=db, now=1000)

    assert db.get(LiveMatch, 8100000003) is None
    assert len(json.loads(db.get(LiveMatch, 8100000001).players_json)) == 9


def test_store_live_matches_sets_ended_at_when_match_leaves_live(db):
    """AC: first and last seen times are kept; a row no longer in /live gets ended_at."""
    import ingest
    from models import LiveMatch

    ingest.store_live_matches(_LIVE_PAYLOAD, [_MONITORED_LEAGUE], db=db, now=1000)
    ingest.store_live_matches([_LIVE_PAYLOAD[1]], [_MONITORED_LEAGUE], db=db, now=1500)
    db.expire_all()

    gone = db.get(LiveMatch, 8100000001)
    assert gone.ended_at == 1500
    assert gone.last_seen_at == 1000
    assert gone.first_seen_at == 1000
    still = db.get(LiveMatch, 8100000002)
    assert still.ended_at is None
    assert still.last_seen_at == 1500


def test_live_poll_once_stores_live_matches_each_check(monkeypatch):
    """AC: each live check stores the live games of the monitored leagues (since #161 the
    separate live thread does this, not the ingest poll)."""
    import main
    import steam_live

    stored, requested = [], []
    monkeypatch.setattr(steam_live, "STEAM_API_KEY", "TESTKEY")
    monkeypatch.setattr(steam_live, "live_checked_at", None)
    monkeypatch.setattr(main, "_get_monitored_league_ids", lambda: [_MONITORED_LEAGUE])
    monkeypatch.setattr(main.steam_live, "get_live_league_games",
                        lambda league_ids: requested.append(league_ids) or _LIVE_PAYLOAD)
    monkeypatch.setattr(main, "store_live_matches", lambda entries, monitored: stored.append((entries, monitored)))

    main._live_poll_once()

    assert requested == [[_MONITORED_LEAGUE]]
    assert stored == [(_LIVE_PAYLOAD, [_MONITORED_LEAGUE])]


def test_current_matches_includes_provisional_live_match_in_team_pair_series(db, twitch_env):
    """AC: GET /twitch/matches/current includes a stored live match without stats, in its team-pair series."""
    now = int(time.time())
    _seed_match(db, 7001, 11, 12, now - 3600, player_ids=(500, 510))
    live = _seed_live(db, _LIVE_PAYLOAD[0], first_seen=now - 60)

    result = _current(db)

    assert len(result["series"]) == 1
    matches = result["series"][0]["matches"]
    assert [m["match_id"] for m in matches] == [7001, 8100000001]
    assert matches[1]["match_number"] == 2
    assert matches[1]["start_time"] == live.first_seen_at
    assert matches[0]["provisional"] is False and matches[1]["provisional"] is True


def test_current_matches_provisional_match_outside_five_series_window_not_listed(db, twitch_env):
    """Failure path: the existing 5-series window still applies to provisional matches."""
    import twitch
    _seed_five_newer_series(db)
    _seed_live(db, _LIVE_PAYLOAD[0], first_seen=int(time.time()) - 10 * 3600,
               radiant_team_id=91, dire_team_id=92)

    offered = {m["match_id"] for m in _all_matches(_current(db))}

    assert 8100000001 not in offered
    assert offered == {1001, 1002, 1003, 1004, 1005}
    assert 8100000001 not in twitch._eligible_mvp_match_ids(db)


def test_current_matches_provisional_match_fields_and_live_flag(db, twitch_env):
    """AC: a provisional match has provisional=true, live true while in /live (false after), players with fantasy_points 0."""
    from models import Player
    now = int(time.time())
    db.add(Player(id=500, name="KnownPlayer"))
    db.commit()
    _seed_live(db, _LIVE_PAYLOAD[0], first_seen=now - 60)
    _seed_live(db, _LIVE_PAYLOAD[0], match_id=8100000005, first_seen=now - 1800, ended_at=now - 120)

    matches = {m["match_id"]: m for m in _all_matches(_current(db))}

    live, ended = matches[8100000001], matches[8100000005]
    assert live["provisional"] is True and ended["provisional"] is True
    assert live["live"] is True and ended["live"] is False
    players = {p["player_id"]: p for p in live["players"]}
    assert len(players) == 9
    assert players[500]["player_name"] == "KnownPlayer"
    assert players[501]["player_name"] == "Player 501"
    assert players[500]["team_name"] == "Radiant Wolves"
    assert players[510]["team_name"] == "Dire Bears"
    assert all(p["fantasy_points"] == 0 for p in live["players"])


def test_current_matches_ingested_match_listed_once_not_provisional(db, twitch_env):
    """AC: a match with ingested stats is listed as today with provisional=false and never twice."""
    now = int(time.time())
    _seed_match(db, 8100000001, 11, 12, now - 600, player_ids=(500, 510))
    _seed_live(db, _LIVE_PAYLOAD[0], first_seen=now - 900)

    matches = [m for m in _all_matches(_current(db)) if m["match_id"] == 8100000001]

    assert len(matches) == 1
    m = matches[0]
    assert m["provisional"] is False
    assert m["live"] is False
    assert {p["player_id"]: p["fantasy_points"] for p in m["players"]} == {500: 10.0, 510: 10.0}


def test_current_matches_live_match_missing_team_ids_grouped_by_names(db, twitch_env):
    """AC: a live match whose team ids are missing is still listed, grouped under its team names."""
    now = int(time.time())
    _seed_live(db, _LIVE_PAYLOAD[1], first_seen=now - 3000, ended_at=now - 600)
    _seed_live(db, _LIVE_PAYLOAD[1], match_id=8100000006, first_seen=now - 60)
    _seed_live(db, _LIVE_PAYLOAD[1], match_id=8100000007, first_seen=now - 120,
               radiant_name="Other One", dire_name="Other Two")

    series = _current(db)["series"]

    pickup = [s for s in series if s["team1_name"] == "Pickup Alpha"]
    assert len(pickup) == 1
    assert pickup[0]["team2_name"] == "Pickup Beta"
    assert [m["match_id"] for m in pickup[0]["matches"]] == [8100000002, 8100000006]
    other = [s for s in series if s["team1_name"] == "Other One"]
    assert len(other) == 1 and other[0]["team2_name"] == "Other Two"
    assert [m["match_id"] for m in other[0]["matches"]] == [8100000007]
    assert not any(s["team1_name"].startswith("Team ") for s in series)


# ===========================================================================
# Story 2 — Confirm an MVP Before Stats Exist
# ===========================================================================

def test_set_mvp_provisional_match_accepts_stored_live_player(db, twitch_env):
    """AC: POST /twitch/mvp accepts a provisional match id in the window when the player is a stored live player."""
    from models import Match, TwitchMVP, TwitchTokenDrop, User
    _add_mvp_weight(db)
    _seed_live(db, _LIVE_PAYLOAD[0])
    _add_viewer(db)
    assert db.get(Match, 8100000001) is None

    result = _call_set_mvp(db, 8100000001, 500)

    assert result["match_id"] == 8100000001
    assert result["player_id"] == 500
    assert result["token_drop"]["winner_count"] == 1
    assert "winners" not in result["token_drop"]
    db.expire_all()
    assert db.query(TwitchMVP).filter_by(match_id=8100000001, player_id=500).count() == 1
    assert db.query(TwitchTokenDrop).filter_by(channel_id="test_channel", series_id="8100000001").count() == 1
    assert db.get(User, 50).tokens == 1


def test_set_mvp_provisional_chat_uses_display_name_fallbacks(db, twitch_env, monkeypatch):
    """AC: the chat message, PubSub message and response use the display name (players name, else live name, else Player {id})."""
    import twitch
    from models import Player
    chat, pubsub = [], []
    monkeypatch.setattr(twitch, "_post_chat_message", lambda channel_id, message: chat.append(message))
    monkeypatch.setattr(twitch, "_pubsub_broadcast", lambda channel_id, message: pubsub.append(message))
    db.add(Player(id=500, name="KnownPlayer"))
    db.commit()
    _seed_live(db, _LIVE_PAYLOAD[0])
    _seed_live(db, _LIVE_PAYLOAD[1])

    cases = [(8100000001, 500, "KnownPlayer"), (8100000002, 600, "LiveNamed"), (8100000001, 501, "Player 501")]
    for match_id, player_id, expected in cases:
        result = _call_set_mvp(db, match_id, player_id)
        assert result["player_name"] == expected
        assert chat[-1].startswith(f"Match MVP: {expected}!")
        assert pubsub[-1]["player_name"] == expected


def test_set_mvp_provisional_writes_audit_with_provisional_flag(db, twitch_env):
    """AC: the twitch_mvp_set audit entry has provisional=True in its detail."""
    from models import AuditLog
    _add_mvp_weight(db)
    _seed_live(db, _LIVE_PAYLOAD[0])
    _seed_match(db, 7001, 11, 12, int(time.time()) - 3600, player_ids=(500, 510))

    _call_set_mvp(db, 8100000001, 501)
    _call_set_mvp(db, 7001, 500)

    logs = {log.detail.split("match=")[1].split()[0]: log.detail
            for log in db.query(AuditLog).filter_by(action="twitch_mvp_set").all()}
    assert "provisional=True" in logs["8100000001"]
    assert "player=Player 501" in logs["8100000001"]
    assert "provisional=True" not in logs["7001"]


def test_set_mvp_provisional_match_applies_no_bonus(db, twitch_env, monkeypatch):
    """AC: no fantasy bonus is applied at confirm time because there is no stats row yet."""
    import twitch
    from models import PlayerMatchStats
    _add_mvp_weight(db)
    _seed_live(db, _LIVE_PAYLOAD[0])
    calls = []
    monkeypatch.setattr(twitch, "_apply_mvp_bonus", lambda *a, **kw: calls.append((a, kw)))

    _call_set_mvp(db, 8100000001, 500)
    _call_set_mvp(db, 8100000001, 501)

    assert calls == []
    assert db.query(PlayerMatchStats).count() == 0


def test_set_mvp_provisional_player_not_in_live_players_returns_404(db, twitch_env):
    """Failure path: a player not among the match's stored live players gets 404 "Player did not play in this match"."""
    from models import Player
    db.add(Player(id=999, name="Elsewhere"))
    db.commit()
    _seed_live(db, _LIVE_PAYLOAD[0])

    with pytest.raises(HTTPException) as exc:
        _call_set_mvp(db, 8100000001, 999)

    assert exc.value.status_code == 404
    assert exc.value.detail == "Player did not play in this match"
    _assert_nothing_written(db)


def test_set_mvp_provisional_channel_not_in_allowlist_returns_403(db, twitch_env, monkeypatch):
    """AC: the channel allowlist check runs first and behaves as today for provisional matches."""
    monkeypatch.setenv("TWITCH_MVP_CHANNEL_IDS", "other_channel")
    _seed_live(db, _LIVE_PAYLOAD[0])

    for match_id, player_id in ((8100000001, 500), (8100000001, 999), (987654321, 500)):
        with pytest.raises(HTTPException) as exc:
            _call_set_mvp(db, match_id, player_id)
        assert exc.value.status_code == 403
        assert exc.value.detail == "This channel cannot set match MVPs"
    _assert_nothing_written(db)


def test_set_mvp_provisional_outside_series_window_returns_403(db, twitch_env):
    """AC: the series-window check behaves as today (unknown id 404, out-of-window live match 403)."""
    _seed_five_newer_series(db)
    _seed_live(db, _LIVE_PAYLOAD[0], first_seen=int(time.time()) - 10 * 3600,
               radiant_team_id=91, dire_team_id=92)

    with pytest.raises(HTTPException) as exc:
        _call_set_mvp(db, 8100000001, 500)
    assert exc.value.status_code == 403
    assert exc.value.detail == "Match is not in the current series window"

    with pytest.raises(HTTPException) as exc:
        _call_set_mvp(db, 8199999999, 500)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Match not found"
    _assert_nothing_written(db)


def test_set_mvp_provisional_reselect_updates_row_without_second_drop(db, twitch_env):
    """AC: changing the MVP on a provisional match updates the row and does not drop tokens again."""
    from models import TwitchMVP, TwitchTokenDrop, User
    _add_mvp_weight(db)
    _seed_live(db, _LIVE_PAYLOAD[0])
    _add_viewer(db)

    first = _call_set_mvp(db, 8100000001, 500)
    second = _call_set_mvp(db, 8100000001, 501)

    assert first["token_drop"]["already_dropped"] is False
    assert second["token_drop"]["already_dropped"] is True
    db.expire_all()
    rows = db.query(TwitchMVP).filter_by(match_id=8100000001).all()
    assert [r.player_id for r in rows] == [501]
    assert db.query(TwitchTokenDrop).count() == 1
    assert db.get(User, 50).tokens == 1


def test_current_matches_provisional_match_shows_confirmed_mvp_display_name(db, twitch_env):
    """AC (supporting): after confirming on a provisional match, current_matches reports its MVP id and display name."""
    _seed_live(db, _LIVE_PAYLOAD[0])
    _seed_live(db, _LIVE_PAYLOAD[1])
    _call_set_mvp(db, 8100000001, 501)
    _call_set_mvp(db, 8100000002, 600)

    matches = {m["match_id"]: m for m in _all_matches(_current(db))}

    assert matches[8100000001]["mvp_player_id"] == 501
    assert matches[8100000001]["mvp_player_name"] == "Player 501"
    assert matches[8100000002]["mvp_player_name"] == "LiveNamed"


# ===========================================================================
# Story 3 — Bonus Applied When Stats Arrive
# ===========================================================================

def _match_payload(start_time):
    return {
        "version": 21, "duration": 2400, "radiant_win": True, "start_time": start_time,
        "radiant_team_id": 11, "dire_team_id": 12,
        "radiant_name": "Radiant Wolves", "dire_name": "Dire Bears",
        "players": [
            {"account_id": 500, "isRadiant": True, "kills": 7, "deaths": 2, "assists": 9,
             "personaname": "Wolf500"},
            {"account_id": 510, "isRadiant": False, "kills": 3, "deaths": 5, "assists": 4,
             "personaname": "Bear510"},
        ],
    }


def test_ingest_match_applies_bonus_to_early_mvp(db, twitch_env, monkeypatch):
    """AC: when the match is ingested, _reapply_mvp_bonus sets is_mvp and the bonus on the chosen player's row."""
    import ingest
    from models import LiveMatch, PlayerMatchStats, Weight
    from scoring import fantasy_score
    _add_mvp_weight(db, 10.0)
    db.add(Weight(key="kills", label="Kills", value=3.0))
    db.add(Weight(key="assists", label="Assists", value=1.5))
    db.commit()
    now = int(time.time())
    _seed_live(db, _LIVE_PAYLOAD[0], first_seen=now - 2400, ended_at=now - 60)
    _call_set_mvp(db, 8100000001, 500)

    payload = _match_payload(now - 2400)
    monkeypatch.setattr(ingest, "opendota_get_json", lambda url, label=None: payload)
    weights = {w.key: w.value for w in db.query(Weight).all()}
    ingest.ingest_match(db, 8100000001, _MONITORED_LEAGUE, set(), set(), weights)

    db.expire_all()
    mvp_row = db.query(PlayerMatchStats).filter_by(match_id=8100000001, player_id=500).one()
    other = db.query(PlayerMatchStats).filter_by(match_id=8100000001, player_id=510).one()
    base = fantasy_score(payload["players"][0], weights)
    assert base > 0
    assert mvp_row.is_mvp is True
    assert mvp_row.fantasy_points == pytest.approx(base * 1.10, abs=1e-3)
    assert other.is_mvp is False
    assert other.fantasy_points == pytest.approx(fantasy_score(payload["players"][1], weights))
    assert db.get(LiveMatch, 8100000001) is None

    listed = [m for m in _all_matches(_current(db)) if m["match_id"] == 8100000001]
    assert len(listed) == 1
    assert listed[0]["provisional"] is False
    assert {p["player_id"]: p["fantasy_points"] for p in listed[0]["players"]}[500] == \
        round(mvp_row.fantasy_points, 1)
    assert listed[0]["mvp_player_name"] == "Wolf500"


def test_reapply_mvp_bonus_logs_warning_when_mvp_has_no_stats_row(db, caplog):
    """Failure path: if the chosen player has no stats row in the ingested match, a warning names the match and player."""
    import ingest
    from models import PlayerMatchStats, TwitchMVP
    _add_mvp_weight(db)
    _seed_match(db, 8100000001, 11, 12, int(time.time()) - 600, player_ids=(500,))
    db.add(TwitchMVP(match_id=8100000001, player_id=999, channel_id="test_channel", selected_at=1))
    db.commit()

    with caplog.at_level(logging.WARNING, logger="ingest"):
        ingest._reapply_mvp_bonus(db, 8100000001)

    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("8100000001" in m and "999" in m for m in warnings), warnings
    db.expire_all()
    row = db.query(PlayerMatchStats).filter_by(match_id=8100000001).one()
    assert row.is_mvp is False
    assert row.fantasy_points == pytest.approx(10.0)


def test_store_live_matches_deletes_row_once_match_has_stats(db):
    """AC: once a match has stats rows, its live_matches row is deleted."""
    import ingest
    from models import LiveMatch
    now = int(time.time())
    _seed_live(db, _LIVE_PAYLOAD[0], first_seen=now - 600, ended_at=now - 60)
    _seed_live(db, _LIVE_PAYLOAD[1], first_seen=now - 600, ended_at=now - 60)
    _seed_match(db, 8100000001, 11, 12, now - 600, player_ids=(500, 510))

    ingest.store_live_matches([], [_MONITORED_LEAGUE], db=db, now=now)

    db.expire_all()
    assert db.get(LiveMatch, 8100000001) is None
    assert db.get(LiveMatch, 8100000002) is not None


def test_store_live_matches_deletes_row_ended_over_24_hours_ago(db, twitch_env):
    """AC: a live match not ingested 24 h after it was last seen is deleted and no longer listed; its MVP row stays."""
    import ingest
    import twitch
    from models import LiveMatch, TwitchMVP
    now = int(time.time())
    _seed_live(db, _LIVE_PAYLOAD[0], first_seen=now - 26 * 3600, ended_at=now - 25 * 3600)
    _seed_live(db, _LIVE_PAYLOAD[1], first_seen=now - 24 * 3600, ended_at=now - 23 * 3600)
    db.add(TwitchMVP(match_id=8100000001, player_id=500, channel_id="test_channel", selected_at=now - 25 * 3600))
    db.commit()
    assert 8100000001 in twitch._eligible_mvp_match_ids(db)

    ingest.store_live_matches([], [_MONITORED_LEAGUE], db=db, now=now)

    db.expire_all()
    assert db.get(LiveMatch, 8100000001) is None
    assert db.get(LiveMatch, 8100000002) is not None
    assert db.query(TwitchMVP).filter_by(match_id=8100000001).count() == 1
    assert 8100000001 not in {m["match_id"] for m in _all_matches(_current(db))}
    assert 8100000001 not in twitch._eligible_mvp_match_ids(db)


# ===========================================================================
# Story 4 — Faster Ingest Right After a Game Ends
# ===========================================================================

def test_ingest_poll_loop_uses_live_match_interval_after_game_ends_without_stats(db, monkeypatch):
    """AC: while a stored live match has ended without ingested stats, the loop keeps INGEST_LIVE_MATCH_POLL_INTERVAL."""
    import main
    now = int(time.time())
    _seed_live(db, _LIVE_PAYLOAD[0], first_seen=now - 2400, ended_at=now - 5 * 60)

    waits = _run_poll_loop_once(monkeypatch, db)

    assert waits == [main._INGEST_LIVE_MATCH_POLL_INTERVAL]


def test_ingest_poll_loop_falls_back_after_post_match_fast_poll_window(db, monkeypatch):
    """Failure path: fast polling stops INGEST_POST_MATCH_FAST_POLL_MINUTES (default 20) after the match ended."""
    import main
    if "INGEST_POST_MATCH_FAST_POLL_MINUTES" not in os.environ:
        assert main._INGEST_POST_MATCH_FAST_POLL_MINUTES == 20
    now = int(time.time())
    _seed_live(db, _LIVE_PAYLOAD[0], first_seen=now - 3600, ended_at=now - 21 * 60)

    waits = _run_poll_loop_once(monkeypatch, db)

    assert waits == [main._INGEST_LIVE_POLL_INTERVAL]


def test_ingest_poll_loop_intervals_unchanged_without_live_or_recent_matches(db, monkeypatch):
    """AC: with no live or recently ended matches, intervals are unchanged."""
    import main

    assert _run_poll_loop_once(monkeypatch, db, active_week=True) == [main._INGEST_LIVE_POLL_INTERVAL]
    assert _run_poll_loop_once(monkeypatch, db, active_week=False) == [main._INGEST_POLL_INTERVAL]

    # A recently ended match that already has stats does not keep the fast interval.
    now = int(time.time())
    _seed_live(db, _LIVE_PAYLOAD[0], first_seen=now - 2400, ended_at=now - 5 * 60)
    _seed_match(db, 8100000001, 11, 12, now - 2400, player_ids=(500, 510))
    assert _run_poll_loop_once(monkeypatch, db, active_week=True) == [main._INGEST_LIVE_POLL_INTERVAL]


# ===========================================================================
# Story 5 — Panel Shows Which Matches Are Provisional (extension release)
# ===========================================================================

def test_live_config_js_labels_provisional_match_live_or_stats_pending():
    """AC: a provisional match row shows "Live" while live is true, otherwise "Stats pending"."""
    src = _function_source(_read_js(), "selectSeries")
    assert re.search(r'match\.provisional\s*\?\s*.*\(match\.live\s*\?\s*"Live"\s*:\s*"Stats pending"\)', src), src


def test_live_config_js_provisional_tiles_show_team_without_points():
    """AC: player tiles of a provisional match show the team name without a points value."""
    src = _function_source(_read_js(), "selectMatch")
    m = re.search(r"var ptag = match\.provisional\s*\?\s*([^:]+):([^;]+);", src)
    assert m, src
    provisional_branch, stats_branch = m.group(1), m.group(2)
    assert provisional_branch.strip() == "_escHtml(teamName)"
    assert "fantasy_points" not in provisional_branch
    assert 'p.fantasy_points + " pts"' in stats_branch
    assert "_escHtml(teamName)" in stats_branch
    assert "ptag" in src.split("var ptag")[1].split(";", 1)[1]


def test_live_config_js_confirmation_says_bonus_applied_when_stats_arrive():
    """AC: after confirming on a provisional match, the confirmation says the bonus is applied when the stats arrive."""
    src = _function_source(_read_js(), "confirmMVP")
    m = re.search(r'_selectedMatch\.provisional\s*\?\s*"([^"]*)"', src)
    assert m, src
    assert "bonus" in m.group(1).lower() and "stats arrive" in m.group(1)
    assert "bonusMsg" in src.split("showBanner(el(\"banner\"), \"MVP: \"")[1]


def test_live_config_js_empty_state_no_longer_mentions_ingest_cycle():
    """AC: the empty-state text no longer says to wait for the next ingest cycle."""
    src = _read_js()
    assert "next ingest cycle" not in src
    assert "ingest" not in _function_source(src, "loadSeries").lower()


_NAME_FIELD = re.compile(r"\b(?:player_name|team_name|team1_name|team2_name|mvp_player_name|teamName)\b")


def _unescaped_names(src):
    """Name fields in HTML-building statements (innerHTML assignments and the
    string pieces feeding them) that are not wrapped in _escHtml(...)."""
    offenders = []
    for stmt in re.split(r";", src):
        if not re.search(r"innerHTML\s*=|var (?:ptag|mvpNote|statusNote)\s*=", stmt):
            continue
        stripped = re.sub(r"_escHtml\([^()]*\)", "", stmt)
        # A truthiness test (`match.mvp_player_name ? ... : ""`) inserts nothing.
        stripped = re.sub(r"[\w.]+\s*\?", "", stripped)
        offenders += _NAME_FIELD.findall(stripped)
    return offenders


def test_live_config_js_escapes_all_new_names():
    """Failure path: every name added to innerHTML (live display names, stored team names) goes through _escHtml."""
    assert _unescaped_names(_read_js()) == []
    # The checker itself flags a raw name.
    assert _unescaped_names('div.innerHTML = "<b>" + p.player_name + "</b>";') == ["player_name"]
    assert _unescaped_names('var ptag = match.provisional ? teamName : "";') == ["teamName"]


def test_extension_package_sh_self_check_passes(tmp_path):
    """AC: live_config.js passes the extension package self-check (twitch-extension/package.sh)."""
    if shutil.which("zip") is None:
        pytest.skip("zip is not installed")
    ext = tmp_path / "twitch-extension"
    shutil.copytree(os.path.dirname(_PACKAGE_SH), ext, ignore=shutil.ignore_patterns("*.zip"))

    result = subprocess.run(["bash", str(ext / "package.sh"), "99.0.0", "--ebs-origin", "https://kana-cards.com"],
                            capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    with zipfile.ZipFile(ext / "twitch-extension-99.0.0.zip") as zf:
        assert "live_config.js" in zf.namelist()
